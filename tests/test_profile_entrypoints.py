"""Slice 3: entrypoints take --profile (default `default` = v1-equivalent)."""

from __future__ import annotations


def _fake_loaded(tmp_path, *, api_key="k", soul="", project="", memory=""):
    """A LoadedProfile stand-in so the dispatch runs without a real profile dir."""
    settings = type("S", (), {"openrouter_api_key": api_key, "data_dir": tmp_path})()
    return type(
        "LP", (),
        {
            "settings": settings, "config": object(),
            "soul": soul, "project": project, "memory": memory,
            "profile_id": "default",
        },
    )()


# --- profile id parsing (cli + cron) ---


def test_cli_parse_profile_default():
    from src.entrypoints.cli import _parse_profile

    assert _parse_profile([]) == "default"
    assert _parse_profile(["report", "--daily"]) == "default"
    assert _parse_profile(["report", "--profile", "acme"]) == "acme"


def test_cron_parse_profile_default():
    from src.entrypoints.cron import _profile_id

    assert _profile_id([]) == "default"
    assert _profile_id(["--okr", "--profile", "beta"]) == "beta"


# --- the v1-equivalence WIRING anchor: no --profile ⇒ load "default", config reaches graph ---


def test_no_profile_flag_loads_default_and_config_reaches_graph(monkeypatch, tmp_path):
    import src.agent.report_graph as report_graph_mod
    from src.entrypoints import cli

    seen = {}
    loaded = _fake_loaded(tmp_path, soul="PERSONA", project="PROJ", memory="MEM")

    def fake_load_profile(profile_id):
        seen["profile_id"] = profile_id
        return loaded

    class _FakeGraph:
        def invoke(self, _state, config):
            return {"report_text": "x", "cost_usd": None, "delivered": True,
                    "delivery_summary": "s"}

    def fake_build(cp, *, config=None, settings=None, context=None,
                   report_kind="daily", audience="internal"):
        seen["config"] = config
        seen["context"] = context
        return _FakeGraph()

    monkeypatch.setattr(cli, "load_profile", fake_load_profile)
    monkeypatch.setattr(cli, "_checkpointer", lambda settings: None)
    monkeypatch.setattr(report_graph_mod, "build_report_graph", fake_build)

    assert cli.main(["report", "--daily"]) == 0
    assert seen["profile_id"] == "default"  # no --profile ⇒ default
    assert seen["config"] is loaded.config  # the loaded config reached the graph
    # persona/project/memory from the profile flowed into the prompt context.
    assert seen["context"].persona == "PERSONA"
    assert seen["context"].project == "PROJ"
    assert seen["context"].memory == "MEM"


def test_explicit_profile_flag_loads_that_profile(monkeypatch, tmp_path):
    import src.agent.report_graph as report_graph_mod
    from src.entrypoints import cli

    seen = {}
    monkeypatch.setattr(
        cli, "load_profile",
        lambda pid: seen.update(pid=pid) or _fake_loaded(tmp_path),
    )
    monkeypatch.setattr(cli, "_checkpointer", lambda settings: None)
    monkeypatch.setattr(
        report_graph_mod, "build_report_graph",
        lambda cp, **kw: type("G", (), {"invoke": lambda self, s, config: {
            "report_text": "x", "delivered": True, "delivery_summary": "", "cost_usd": None}})(),
    )
    assert cli.main(["report", "--daily", "--profile", "acme"]) == 0
    assert seen["pid"] == "acme"


# --- bad --profile ⇒ clear error, non-zero exit, no traceback ---


def test_cli_bad_profile_returns_error(monkeypatch, capsys):
    from src.entrypoints import cli

    def boom(profile_id):
        raise FileNotFoundError(f"Profile {profile_id!r} not found: ...")

    monkeypatch.setattr(cli, "load_profile", boom)
    rc = cli.main(["report", "--daily", "--profile", "nope"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "nope" in err and "error:" in err


def test_cron_bad_profile_returns_one(monkeypatch, capsys):
    from src.entrypoints import cron

    def boom(profile_id):
        raise FileNotFoundError(f"Profile {profile_id!r} not found")

    monkeypatch.setattr(cron, "load_profile", boom)
    assert cron.main(["--daily", "--profile", "nope"]) == 1
    assert "nope" in capsys.readouterr().err


# --- misconfigured profile (config RuntimeError) ⇒ clean exit, not a crash ---


def test_cli_misconfigured_profile_audit_stays_clean(monkeypatch, capsys):
    # A profile whose reporting config fails validation (stakeholder not in external)
    # must NOT crash `audit` with a traceback — it exits non-zero with a clear error.
    from src.entrypoints import cli

    def boom(profile_id):
        raise RuntimeError("SLACK_EXTERNAL_CHANNELS: stakeholder channel must be listed")

    monkeypatch.setattr(cli, "load_profile", boom)
    assert cli.main(["audit", "--limit", "1"]) == 1
    assert "error:" in capsys.readouterr().err  # clean message, no traceback


def test_cron_misconfigured_profile_returns_one(monkeypatch, capsys):
    from src.entrypoints import cron

    monkeypatch.setattr(
        cron, "load_profile",
        lambda pid: (_ for _ in ()).throw(RuntimeError("bad reporting config")),
    )
    assert cron.main(["--daily"]) == 1
    assert "error:" in capsys.readouterr().err


# --- bad profile is a typo, not a crash: FileNotFoundError is the only swallowed error ---


def test_cli_real_default_profile_loads(monkeypatch):
    # Integration-ish: the committed profiles/default/ actually loads (no network),
    # and a missing key short-circuits to exit 1 (proves the real load path works).
    from src.entrypoints import cli

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SLACK_STAKEHOLDER_CHANNEL", raising=False)
    monkeypatch.delenv("SLACK_EXTERNAL_CHANNELS", raising=False)
    # Block the loader's .env load so the deleted key stays absent (else the real .env
    # key would be reloaded and the hello path would hit the network).
    monkeypatch.setattr("src.profile.loader.load_dotenv", lambda *a, **k: None)
    # hello path: loads the real default profile, then _require_key fails (no key) ⇒ 1.
    assert cli.main(["hello"]) == 1
