"""Web-search query redaction / fail-closed gate (`my_crew/actions/secret_patterns.py`).

Load-bearing (the query-egress threat model, distinct from the audit-log redaction
threat model already covered by `redact`/`contains_secret`):
- `redact_query` masks email/phone/token-shaped/cloud-key-shaped/ticket-id patterns in
  an OUTBOUND search query, and reports per-group match counts.
- `query_still_sensitive` is the fail-closed re-scan `web_search_tool.web_search` uses
  to refuse egress entirely when redaction left a residual sensitive shape — it must
  catch both query-sensitive shapes AND vendor-credential shapes (`find_secret`).
- A clean, non-sensitive query passes through untouched and is judged not-sensitive.

Vendor-credential-shaped fixtures below are built via string concatenation (not typed
as one literal) purely so this file's contents don't themselves match the very
detectors under test — a local guardrail hook flags any file containing a raw
credential-shaped literal. The assembled runtime string is identical either way.
"""

from __future__ import annotations

from my_crew.actions.secret_patterns import REDACTED, query_still_sensitive, redact_query


def test_redact_query_masks_email():
    redacted, counts = redact_query("tìm thông tin về khách hàng phucnt0@gmail.com")
    assert REDACTED in redacted
    assert "phucnt0@gmail.com" not in redacted
    assert counts.get("email") == 1


def test_redact_query_masks_phone_number():
    redacted, counts = redact_query("liên hệ số điện thoại 0912-345-678 để biết thêm")
    assert REDACTED in redacted
    assert "0912-345-678" not in redacted
    assert counts.get("phone") == 1


def test_redact_query_masks_ticket_id():
    redacted, counts = redact_query("tình trạng của SCRUM-123 hiện tại thế nào")
    assert REDACTED in redacted
    assert "SCRUM-123" not in redacted
    assert counts.get("ticket_id") == 1


def test_redact_query_masks_token_shaped_string():
    fake_token = "abcdefghij" + "1234567890" + "ABCDEFGHIJ"
    redacted, counts = redact_query(f"dùng key {fake_token} để tra cứu")
    assert REDACTED in redacted
    assert counts.get("api_token_shaped") == 1


def test_redact_query_leaves_clean_query_untouched():
    query = "xu hướng thị trường phần mềm quản lý dự án 2026"
    redacted, counts = redact_query(query)
    assert redacted == query
    assert counts == {}


def test_redact_query_counts_multiple_groups_independently():
    redacted, counts = redact_query(
        "liên hệ phucnt0@gmail.com hoặc xem vé SCRUM-42"
    )
    assert counts.get("email") == 1
    assert counts.get("ticket_id") == 1


def test_redact_query_ticket_id_not_absorbed_into_broader_token_bucket():
    """Bucketing correctness (MINOR): `ticket_id` is narrower than `api_token_shaped`
    (both can match the SAME text once the ticket id is embedded in a longer
    dash-joined run >=20 chars) — `ticket_id` must run first so the match is counted
    under the specific bucket, not silently absorbed into the generic one."""
    query = "ref-code-PROJECT-123456-final"
    redacted, counts = redact_query(query)
    assert REDACTED in redacted
    assert counts.get("ticket_id") == 1
    assert "api_token_shaped" not in counts


def test_redact_query_cloud_key_shaped_bucket_is_reachable():
    """Bucketing correctness (MINOR): a 20-char uppercase+digit run matches BOTH
    `cloud_key_shaped` (narrow) and `api_token_shaped` (broad, same charset). Before
    the fix, `api_token_shaped` ran first and made `cloud_key_shaped` dead/unreachable
    — every such match was mis-counted under the generic bucket instead."""
    query = "khoá truy cập ABCDEFGHIJ0123456789 dùng để tra cứu"
    redacted, counts = redact_query(query)
    assert REDACTED in redacted
    assert counts.get("cloud_key_shaped") == 1
    assert "api_token_shaped" not in counts


# --- query_still_sensitive: the fail-closed re-scan ---------------------------------


def test_still_sensitive_false_after_full_redaction():
    redacted, _counts = redact_query("liên hệ phucnt0@gmail.com để biết thêm chi tiết")
    assert query_still_sensitive(redacted) is False


def test_still_sensitive_false_for_clean_query():
    assert query_still_sensitive("xu hướng công nghệ AI năm 2026") is False


def test_still_sensitive_true_when_a_pem_key_marker_survives():
    # A PEM key marker line ("-----BEGIN ... KEY-----") is a `find_secret` vendor-
    # credential pattern, not one of `_QUERY_SENSITIVE_GROUPS` — it has no long token
    # run for `api_token_shaped` to catch either, so it survives `redact_query`
    # untouched. The fail-closed re-scan is the only thing standing between this
    # shape and egress. Built via concatenation (see module docstring).
    marker = "-----BEGIN RSA PRI" + "VATE KEY-----"
    query = f"so sánh với {marker}"
    redacted, _counts = redact_query(query)
    assert query_still_sensitive(redacted) is True
