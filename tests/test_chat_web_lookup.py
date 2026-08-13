"""v57 P4: web lookup 2-pass cho đường chat M11. Offline (hook/LLM inject).

Load-bearing properties:

- Marker protocol nghiêm: chỉ reply ĐÚNG-MỘT-DÒNG bắt đầu `WEB_SEARCH:` mới thành truy
  vấn; reply trộn chữ/đa dòng/quá dài ⇒ văn bản thường (model sai giao thức không được
  thưởng bằng một lượt gọi mạng).
- Gate: thiếu cờ `web_search` HOẶC thiếu key ⇒ hook None (đường QA byte-identical).
- 2-pass trong `_answer_question`: pass-1 marker → hook chạy → pass-2 có KẾT QUẢ TRA WEB
  trong user message (không bao giờ vào system) → reply cuối được gửi; cost cộng dồn;
  pass-2 lại marker ⇒ cắt vòng lặp bằng câu nói-thật trung tính.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.agent import chat_web_lookup as cwl

# --- marker protocol ---


def test_extract_query_accepts_only_single_line_marker():
    assert cwl.extract_query("WEB_SEARCH: giá vàng SJC hôm nay") == "giá vàng SJC hôm nay"
    assert cwl.extract_query("  WEB_SEARCH: x  ") == "x"
    assert cwl.extract_query("Đây là trả lời thường") is None
    assert cwl.extract_query("WEB_SEARCH: q\nvà giải thích thêm") is None  # đa dòng
    assert cwl.extract_query("WEB_SEARCH:") is None  # truy vấn rỗng
    assert cwl.extract_query("WEB_SEARCH: " + "x" * 300) is None  # quá dài


# --- gate ---


def test_hook_none_without_flag_or_key(tmp_path):
    settings = SimpleNamespace(tavily_api_key=None, brave_api_key="k", data_dir=tmp_path)
    no_flag = SimpleNamespace(web_search=False)
    assert cwl.build_chat_search_hook(no_flag, settings) is None
    flagged = SimpleNamespace(web_search=True)
    no_key = SimpleNamespace(tavily_api_key=None, brave_api_key=None, data_dir=tmp_path)
    assert cwl.build_chat_search_hook(flagged, no_key) is None
    assert cwl.build_chat_search_hook(flagged, settings) is not None


# --- 2-pass trong _answer_question ---


class _SeqLlm:
    """LLM giả trả lần lượt các content định sẵn; ghi lại messages từng lượt."""

    def __init__(self, contents):
        self.contents = list(contents)
        self.calls: list[list[dict]] = []

    def complete(self, messages, **_kw):
        self.calls.append(messages)
        return SimpleNamespace(content=self.contents.pop(0), cost_usd=0.001)


class _Pack:
    prompts: dict = {}
    allowlist: dict = {}
    report_kinds = {"briefing": None}
    tools = SimpleNamespace(read=lambda self, k, c, s: {})

    def __init__(self):
        self.tools = SimpleNamespace(read=lambda k, c, s: {})


class _Gateway:
    def execute(self, action, *, handler=None, rationale=""):
        from my_crew.actions.action_gateway import GatewayResult

        self.last = action
        return GatewayResult(status="executed", summary="ok")


def _loaded(tmp_path):
    return SimpleNamespace(
        profile_id="tk", domain="personal", soul="", project="", memory="",
        reports=("briefing",), web_search=True, company_docs=(),
        memory_config=None, config=SimpleNamespace(slack_external_channels=frozenset(),
                                                   telegram=None),
        inbox={"channel": "C1"},
    )


def test_answer_question_two_pass_web(tmp_path, monkeypatch):
    from my_crew.agent import qa_answer

    hook_queries: list[str] = []
    monkeypatch.setattr(
        "my_crew.agent.chat_web_lookup.build_chat_search_hook",
        lambda loaded, settings: (lambda q: hook_queries.append(q) or "[[kết quả web X]]"),
    )
    monkeypatch.setattr(qa_answer, "_post_reply", lambda gw, lo, m, ch, reply: SimpleNamespace(
        status="executed", summary=reply))
    llm = _SeqLlm(["WEB_SEARCH: giá vàng hôm nay", "Giá vàng hôm nay là … (nguồn: sjc.com.vn)"])
    settings = SimpleNamespace(dry_run=True, data_dir=tmp_path)
    outcome, cost = qa_answer._answer_question(
        _loaded(tmp_path), settings,
        mention={"text": "giá vàng?", "transport": "telegram", "channel": "5", "ts": "1"},
        pack=_Pack(), gateway=_Gateway(), llm=llm, channel="5",
    )
    assert hook_queries == ["giá vàng hôm nay"]
    assert len(llm.calls) == 2
    # Kết quả web nằm trong USER message pass-2, không bao giờ vào system.
    assert "[[kết quả web X]]" in llm.calls[1][1]["content"]
    assert llm.calls[1][0]["content"] == llm.calls[0][0]["content"]  # system bất biến
    assert outcome.summary.startswith("Giá vàng hôm nay")
    assert cost == 0.002  # cộng dồn 2 pass


def test_answer_question_single_pass_when_no_marker(tmp_path, monkeypatch):
    from my_crew.agent import qa_answer

    monkeypatch.setattr(
        "my_crew.agent.chat_web_lookup.build_chat_search_hook",
        lambda loaded, settings: (lambda q: "không được gọi"),
    )
    monkeypatch.setattr(qa_answer, "_post_reply", lambda gw, lo, m, ch, reply: SimpleNamespace(
        status="executed", summary=reply))
    llm = _SeqLlm(["Trả lời thẳng, không cần web."])
    outcome, _ = qa_answer._answer_question(
        _loaded(tmp_path), SimpleNamespace(dry_run=True, data_dir=tmp_path),
        mention={"text": "hỏi thường", "transport": "telegram", "channel": "5", "ts": "2"},
        pack=_Pack(), gateway=_Gateway(), llm=llm, channel="5",
    )
    assert len(llm.calls) == 1
    assert outcome.summary == "Trả lời thẳng, không cần web."


def test_answer_question_breaks_marker_loop(tmp_path, monkeypatch):
    from my_crew.agent import qa_answer

    monkeypatch.setattr(
        "my_crew.agent.chat_web_lookup.build_chat_search_hook",
        lambda loaded, settings: (lambda q: ""),
    )
    monkeypatch.setattr(qa_answer, "_post_reply", lambda gw, lo, m, ch, reply: SimpleNamespace(
        status="executed", summary=reply))
    llm = _SeqLlm(["WEB_SEARCH: a", "WEB_SEARCH: b"])  # pass-2 vẫn đòi tra ⇒ cắt
    outcome, _ = qa_answer._answer_question(
        _loaded(tmp_path), SimpleNamespace(dry_run=True, data_dir=tmp_path),
        mention={"text": "q", "transport": "telegram", "channel": "5", "ts": "3"},
        pack=_Pack(), gateway=_Gateway(), llm=llm, channel="5",
    )
    assert len(llm.calls) == 2  # không có pass 3
    assert "Chưa tra được" in outcome.summary
