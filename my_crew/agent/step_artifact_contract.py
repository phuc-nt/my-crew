"""Artifact contracts for team-task steps — the hand-off shape a step OWES its dependents.

Context-crew rule: a role is a capability tuple (tools, permissions, model) plus the
artifact it must leave behind; the next step reads that artifact, never a conversation.
The contract is therefore the ONE place a step's output is judged by code before an LLM
grader ever sees it — the same deterministic-first policy `deterministic_step_check`
applies to acceptance criteria, applied to the artifact KIND:

  - `findings`  a dep-less collect step (`needs_web`, nothing to read from). Owes its
                dependents evidence they can cite: at least one URL. A sourceless
                findings artifact is the exact shape that laundered invented prices
                into a downstream table (v72 UAT), so it fails here, not at the judge.
  - `draft`     any intermediate produce step. Owes non-empty text (the empty-result
                guard already lives in self-check; the contract line in the prompt is
                what this kind adds).
  - `final`     the terminal deliverable (`final_deliverable`). Owes a body the CEO can
                read as an answer, not a stub — a floor, not a quality bar.
  - `verdict`   a review row. Graded by `review_graph` with its own JSON schema; the
                contract here is descriptive only (no gap check).

Fail-open by construction: an unknown kind or blank text contributes no gap beyond what
self-check already reports, so a caller that never wired a contract grades as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ARTIFACT_KINDS: tuple[str, ...] = ("findings", "draft", "final", "verdict")

#: Minimum body for a terminal deliverable. Well under any real answer; catches the
#: "Đã xong." / one-line refusal that a self-check with blank criteria would pass.
FINAL_MIN_CHARS = 200

_URL_RE = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class ArtifactContract:
    """What one step owes: its artifact kind, whether it must carry web evidence, and
    how many distinct source URLs its deps handed it.

    `upstream_sources` is the provenance contract: a draft or final fed by sourced
    findings must keep at least one of those links, or the sources are lost exactly at
    the step whose output the CEO reads ("aggregate mất nguồn" in the crew assessment).
    Counted over the DEPS' artifacts only — never the CEO brief — so a link the CEO
    pasted into the request cannot make this demand fire.
    """

    kind: str
    needs_web: bool = False
    upstream_sources: int = 0


def upstream_source_count(dep_text: str) -> int:
    """Distinct URLs in the deps' hand-off text; 0 for blank input."""
    return len(set(_URL_RE.findall(dep_text or "")))


def artifact_kind_for(step) -> str:
    """Derive the artifact kind from the step's own DAG position and flags.

    Reads only fields every `TeamStep`/`TeamStepPlan` carries; a step whose type is
    `review` is a verdict regardless of position, a terminal step (`final_deliverable`,
    derived by the store from the DAG) is `final`, a dep-less web collect is `findings`,
    everything else is a `draft`.
    """
    if str(getattr(step, "step_type", "work") or "work") == "review":
        return "verdict"
    if bool(getattr(step, "final_deliverable", False)):
        return "final"
    if bool(getattr(step, "needs_web", False)) and not tuple(getattr(step, "deps", ()) or ()):
        return "findings"
    return "draft"


def contract_for(step, dep_text: str = "") -> ArtifactContract:
    """`dep_text` is the deps' hand-off as the step will read it (the runner passes the
    same read the work-order writer records); "" ⇒ no provenance demand."""
    return ArtifactContract(
        kind=artifact_kind_for(step), needs_web=bool(getattr(step, "needs_web", False)),
        upstream_sources=upstream_source_count(dep_text),
    )


def artifact_contract_gaps(contract: ArtifactContract | None, text: str) -> list[str]:
    """Deterministic contract misses, phrased as self-check failures (Vietnamese, one
    line each) so they ride the existing rework loop unchanged. Empty ⇒ contract met or
    nothing to check."""
    if contract is None:
        return []
    body = (text or "").strip()
    if not body:
        return []  # the empty-result guard in self-check already owns this case
    gaps: list[str] = []
    if contract.kind == "findings" and contract.needs_web and not _URL_RE.search(body):
        gaps.append(
            "bước thu thập phải để lại ít nhất một link nguồn (http…) cho bước sau trích dẫn "
            "— kết quả chưa có URL nào"
        )
    if (
        contract.kind in ("draft", "final")
        and contract.upstream_sources > 0
        and not _URL_RE.search(body)
    ):
        gaps.append(
            f"bước trước để lại {contract.upstream_sources} link nguồn — bản này phải giữ ít "
            "nhất một link (http…) bên cạnh số liệu lấy từ đó, nếu không CEO không kiểm "
            "chứng được"
        )
    if contract.kind == "final" and len(body) < FINAL_MIN_CHARS:
        gaps.append(
            f"bản nộp cuối quá ngắn ({len(body)} ký tự, cần ≥ {FINAL_MIN_CHARS}) — "
            "đây là thứ CEO đọc trực tiếp, phải là câu trả lời đầy đủ chứ không phải ghi chú"
        )
    return gaps


def artifact_contract_line(contract: ArtifactContract | None) -> str:
    """One prompt line telling the worker what artifact it owes. "" when no contract."""
    if contract is None:
        return ""
    if contract.kind == "findings":
        base = ("Bàn giao: bản THU THẬP cho bước sau dùng — mỗi dữ kiện kèm link nguồn "
                "(http…), không diễn giải thêm.")
        if not contract.needs_web:
            base = "Bàn giao: bản THU THẬP cho bước sau dùng — ghi rõ nguồn của mỗi dữ kiện."
        return base
    if contract.kind == "verdict":
        return "Bàn giao: VERDICT soát chéo theo rubric cố định."
    if contract.kind == "final":
        base = ("Bàn giao: BẢN NỘP CUỐI — CEO đọc trực tiếp, phải là câu trả lời hoàn chỉnh, "
                "tự đứng được, không tham chiếu 'bước trước'.")
    else:
        base = ("Bàn giao: BẢN NHÁP cho bước sau tiếp tục — đủ nội dung để người sau không "
                "phải hỏi lại.")
    if contract.upstream_sources > 0:
        base += (" Giữ link nguồn của bước trước bên cạnh mỗi số liệu lấy từ đó — bản không "
                 "còn link là bản mất nguồn.")
    return base
