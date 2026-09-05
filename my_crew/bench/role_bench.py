"""Role scorecard: which model roles hold up on the fleet model.

The fleet resolves every LLM call to one of `MODEL_ROLES`, and a single model now
serves all of them. This bench asks, per role, "does production code get what it
needs from this model on this role?" — by driving fixed inputs through each role's
REAL prompt builder and REAL parser (`role_bench_probes_*`) and scoring the result
deterministically. Nothing is judged by a second model.

Each probe is replayed `k` times, because one sample rounds noise into a verdict. A
role's rate is pooled over all its probe runs; the Wilson interval says how little
that rate should be trusted at this sample size. Verdict thresholds are deliberately
coarse (good / watch / weak) — the scorecard exists to tell the CEO where to spend a
better model, not to rank roles to two decimals.

Failure kinds are tallied per role and per probe so a weak role reads as WHY it is
weak: `parse` says the model cannot hold the JSON shape, `wrong` says it can and
still answers badly, `empty`/`truncated` say the call never delivered.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from my_crew.bench.hypothesis_stats import verdict_calibration, wilson_interval
from my_crew.bench.role_bench_probe_kit import FAIL_KINDS, Probe, ProbeOutcome
from my_crew.config.settings import MODEL_ROLES

FORMAT_VERSION = 1
DEFAULT_K = 3
#: Pooled pass rate at or above which a role is `good`; at or below `ROLE_WEAK_MAX`
#: it is `weak`; between, `watch`. A role with no runs is `unmeasured`.
ROLE_GOOD_MIN = 0.9
ROLE_WEAK_MAX = 0.7
COMPARED_FIELDS = ("rate", "verdict")


def all_probes(intake: Callable | None = None) -> list[Probe]:
    """Every probe of every role. `intake` is the plan role's offline seam."""
    from my_crew.bench.role_bench_probes_content import (
        aggregate_probes,
        content_probes,
        sprint_low_probes,
    )
    from my_crew.bench.role_bench_probes_plan import plan_probes
    from my_crew.bench.role_bench_probes_review import review_probes
    from my_crew.bench.role_bench_probes_util_advisor import advisor_probes, util_probes

    return (plan_probes(intake) + review_probes() + content_probes() + sprint_low_probes()
            + aggregate_probes() + util_probes() + advisor_probes())


def uncovered_roles(probes: list[Probe]) -> list[str]:
    """Roles in `MODEL_ROLES` no probe measures — a role added to the fleet without a
    probe would otherwise silently read as `unmeasured` forever."""
    covered = {p.role for p in probes}
    return [r for r in MODEL_ROLES if r not in covered]


def run_probe(probe: Probe, client: Any) -> tuple[ProbeOutcome, float]:
    """One replay → (outcome, wall seconds). A raise is the `error` kind, not a crash:
    the scorecard must finish so the other roles still get measured."""
    started = time.monotonic()
    try:
        outcome = probe.run(client)
    except Exception as exc:  # noqa: BLE001 — a probe must report, not abort the suite
        outcome = ProbeOutcome.failed("error", f"{type(exc).__name__}: {exc}")
    return outcome, time.monotonic() - started


def role_verdict(ok: int, n: int) -> str:
    if n == 0:
        return "unmeasured"
    rate = ok / n
    if rate >= ROLE_GOOD_MIN:
        return "good"
    if rate <= ROLE_WEAK_MAX:
        return "weak"
    return "watch"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def run_suite(client: Any, *, k: int = DEFAULT_K, roles: list[str] | None = None,
              probes: list[Probe] | None = None, model: str = "") -> dict[str, Any]:
    """Replay every selected probe `k` times and fold the outcomes per role.

    `roles` narrows the run (a cheap re-measure of one role after a prompt change);
    `probes` is the offline seam. Unknown role names raise rather than measuring an
    empty set and printing a clean report for a typo.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    selected = all_probes() if probes is None else list(probes)
    if roles is not None:
        unknown = sorted(set(roles) - set(MODEL_ROLES))
        if unknown:
            raise ValueError(f"unknown roles {unknown}; choose from {list(MODEL_ROLES)}")
        selected = [p for p in selected if p.role in roles]

    per_role: dict[str, dict[str, Any]] = {}
    for probe in selected:
        role = per_role.setdefault(probe.role, {
            "n": 0, "ok": 0, "fails": Counter(), "latencies": [], "costs": [],
            "tallies": Counter(), "probes": [],
        })
        fails: Counter = Counter()
        oks, latencies, costs, details = 0, [], [], []
        for _ in range(k):
            outcome, wall = run_probe(probe, client)
            latencies.append(wall)
            if outcome.cost_usd is not None:
                costs.append(outcome.cost_usd)
            if outcome.ok:
                oks += 1
            else:
                fails[outcome.kind] += 1
            details.append(f"{outcome.kind}: {outcome.detail}" if outcome.detail
                           else outcome.kind)
            if outcome.tallies:
                role["tallies"].update(outcome.tallies)
        role["n"] += k
        role["ok"] += oks
        role["fails"].update(fails)
        role["latencies"] += latencies
        role["costs"] += costs
        role["probes"].append({
            "name": probe.name, "n": k, "ok": oks, "fails": dict(fails),
            "mean_latency_s": _mean(latencies), "mean_cost_usd": _mean(costs),
            "details": details,
        })

    report_roles: dict[str, Any] = {}
    for role_name in MODEL_ROLES:
        if roles is not None and role_name not in roles:
            continue
        r = per_role.get(role_name)
        if r is None:
            report_roles[role_name] = {"n": 0, "ok": 0, "rate": None, "verdict": "unmeasured",
                                       "probes": []}
            continue
        low, high = wilson_interval(r["ok"], r["n"])
        entry: dict[str, Any] = {
            "n": r["n"], "ok": r["ok"], "rate": round(r["ok"] / r["n"], 3),
            "wilson_low": round(low, 3), "wilson_high": round(high, 3),
            "mean_latency_s": _mean(r["latencies"]), "mean_cost_usd": _mean(r["costs"]),
            "verdict": role_verdict(r["ok"], r["n"]),
            "fails": {kind: r["fails"][kind] for kind in FAIL_KINDS if r["fails"][kind]},
            "probes": r["probes"],
        }
        t = r["tallies"]
        if t.get("clean_graded") or t.get("seeded"):
            h4 = verdict_calibration(
                false_fails=t["false_fails"], clean_graded=t["clean_graded"],
                caught=t["caught"], seeded=t["seeded"])
            entry["h4"] = {"keep": h4.keep, "reasons": list(h4.reasons), **h4.metrics}
        report_roles[role_name] = entry

    return {"format_version": FORMAT_VERSION, "model": model, "k": k, "roles": report_roles}


def compare_roles(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-role and per-probe cells that differ, in `_print_delta` row shape.

    Refuses a format or `k` mismatch for the same reason `compare_reliability` does:
    rates over different denominators, or fields with different meanings, produce a
    delta table that reads like behaviour change and is not.
    """
    b_ver, c_ver = baseline.get("format_version", 0), candidate.get("format_version", 0)
    if b_ver != c_ver:
        raise ValueError(f"role report format_version lệch nhau ({b_ver} vs {c_ver}) — "
                         "chạy lại baseline bằng bản script hiện tại trước khi so")
    b_k, c_k = baseline.get("k"), candidate.get("k")
    if b_k != c_k:
        raise ValueError(f"role report chạy khác k ({b_k} vs {c_k}) — rate hai bên khác "
                         "mẫu số nên không so trực tiếp được")
    rows: list[dict[str, Any]] = []
    b_roles, c_roles = baseline.get("roles", {}), candidate.get("roles", {})
    for role in sorted(set(b_roles) | set(c_roles)):
        b, c = b_roles.get(role), c_roles.get(role)
        if b is None or c is None:
            rows.append({"case": role, "field": "role", "baseline": "—" if b is None else "có",
                         "candidate": "—" if c is None else "có"})
            continue
        for field in COMPARED_FIELDS:
            if b.get(field) != c.get(field):
                rows.append({"case": role, "field": field,
                             "baseline": b.get(field), "candidate": c.get(field)})
        b_probes = {p["name"]: p for p in b.get("probes", [])}
        c_probes = {p["name"]: p for p in c.get("probes", [])}
        for name in sorted(set(b_probes) | set(c_probes)):
            bp, cp = b_probes.get(name), c_probes.get(name)
            b_cell = "—" if bp is None else f"{bp['ok']}/{bp['n']}"
            c_cell = "—" if cp is None else f"{cp['ok']}/{cp['n']}"
            if b_cell != c_cell:
                rows.append({"case": f"{role}/{name}", "field": "ok",
                             "baseline": b_cell, "candidate": c_cell})
    return rows
