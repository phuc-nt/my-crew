"""ads-pack ToolProvider (P6) — Meta Marketing API insights, read-only.

Reads `GET /{api_version}/act_{account_id}/insights` (spend, reach, ctr, campaign_name,
campaign_id, date_start) for a given ad account, broken out per-campaign per-day
(`level=campaign`, `time_increment=1`). stdlib `urllib` only (repo HTTP convention — see
`hr-pack/tools.py`'s `gws` CLI spawn, `telegram_write.py`'s `urllib.request` calls).

Token resolution goes through `resolve_service_credentials` (P4) — this module NEVER
reads `.env`/the credential store file directly; it only calls the resolver and reads
the returned in-memory dict. Fail-degrade convention: a request-level failure (network,
4xx, 5xx, malformed JSON) is caught here and turned into a `MetaInsightsError` carrying a
human reason; the ANALYZER (not this module) decides whether that becomes a THIẾU
sentinel in the composed report — this module either returns real rows or raises, it
never fabricates a placeholder row.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from my_crew.config.credential_resolver import resolve_service_credentials
from my_crew.config.credential_store import CredentialStoreError

#: Pinned in pack.yaml; read here so a version bump is a one-file edit, not a code change.
_DEFAULT_API_VERSION = "v25.0"
_GRAPH_API_BASE = "https://graph.facebook.com"
_INSIGHTS_FIELDS = "campaign_id,campaign_name,spend,reach,ctr,date_start,date_stop"
_REQUEST_TIMEOUT_S = 20

#: Env-only pack config (mirrors hr-pack's env-config posture — a pack owns its own
#: config source, the core reporting config gets no ads-specific field).
_AD_ACCOUNT_ID_ENV = "ADS_META_AD_ACCOUNT_ID"
_TOKEN_ENV_FALLBACK = "ADS_META_TOKEN"  # used only if no `account`/`token_env` config given
_DATE_PRESET_ENV = "ADS_META_DATE_PRESET"
_DEFAULT_DATE_PRESET = "last_7d"


class MetaInsightsError(RuntimeError):
    """Raised when the Meta Graph API call fails (network/4xx/5xx/malformed JSON).

    Never carries the access token — message is the API's own error text or an HTTP
    status line only.
    """


@dataclass(frozen=True)
class InsightRow:
    """One campaign-day insight row, normalized from the Graph API's raw JSON."""

    campaign_id: str
    campaign_name: str
    date: str
    spend: float
    reach: int
    ctr: float


def _resolve_token(settings: Any) -> str:
    """Resolve the Meta access token via the P4 credential resolver (never read env/store
    directly). `settings` may carry an `ads_credential` block (`{"account": ...}` or
    `{"token_env": ...}`); absent that, fall back to a bare `ADS_META_TOKEN` env var so
    the pack still runs in a single-operator MVP with no credential-store entry yet.
    """
    block = getattr(settings, "ads_credential", None) or {}
    if block:
        resolved = resolve_service_credentials(block)
        if resolved and resolved.get("token"):
            return str(resolved["token"])
        raise MetaInsightsError(
            "ads_credential is configured but resolved to no usable 'token' field."
        )
    resolved = resolve_service_credentials({"token_env": _TOKEN_ENV_FALLBACK})
    if resolved and resolved.get("token"):
        return str(resolved["token"])
    raise MetaInsightsError(
        f"no Meta token configured — set {_TOKEN_ENV_FALLBACK} or settings.ads_credential."
    )


def _api_version() -> str:
    """Read the pinned Marketing API version from ads-pack's own pack.yaml."""
    import yaml

    from my_crew.packs.registry import pack_dir

    manifest = pack_dir("ads") / "pack.yaml"
    try:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        return str(doc.get("meta_marketing_api_version") or _DEFAULT_API_VERSION)
    except OSError:
        return _DEFAULT_API_VERSION


def fetch_campaign_insights(
    ad_account_id: str, *, token: str, date_preset: str = _DEFAULT_DATE_PRESET,
) -> list[InsightRow]:
    """One GET to the Marketing API insights endpoint. Raises MetaInsightsError on any
    HTTP/network/parse failure — the caller (ToolProvider.read) decides how to degrade.
    """
    params = {
        "fields": _INSIGHTS_FIELDS,
        "level": "campaign",
        "time_increment": "1",
        "date_preset": date_preset,
        "access_token": token,
    }
    url = (
        f"{_GRAPH_API_BASE}/{_api_version()}/act_{ad_account_id}/insights?"
        f"{urllib.parse.urlencode(params)}"
    )
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Meta's error body is JSON `{"error": {"message": ..., "code": ...}}` — surface
        # the message only, never echo the token (it is a query param on `url`, not in
        # the error body, but we still never log/format `url` anywhere).
        detail = _extract_meta_error(exc)
        raise MetaInsightsError(f"Meta Graph API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MetaInsightsError(f"Meta Graph API network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise MetaInsightsError(
            f"Meta Graph API request timed out after {_REQUEST_TIMEOUT_S}s"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MetaInsightsError("Meta Graph API returned non-JSON body") from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise MetaInsightsError(f"Meta Graph API response missing 'data': {raw[:200]}")

    rows: list[InsightRow] = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        rows.append(
            InsightRow(
                campaign_id=str(item.get("campaign_id") or ""),
                campaign_name=str(item.get("campaign_name") or "(unnamed)"),
                date=str(item.get("date_start") or ""),
                spend=_safe_float(item.get("spend")),
                reach=_safe_int(item.get("reach")),
                ctr=_safe_float(item.get("ctr")),
            )
        )
    return rows


def _extract_meta_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        return str(body.get("error", {}).get("message") or exc.reason)
    except (OSError, json.JSONDecodeError, AttributeError):
        return str(exc.reason)


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


class AdsToolProvider:
    """ads-pack read seam: `read(kind, config, settings)` → list[InsightRow] | None.

    Returns `None` (not a raised exception) on a source failure — the graph's perceive
    node treats `None` as "THIẾU dữ liệu, degrade the report" rather than crashing the
    whole run, per the phase's fail-degrade non-functional requirement. A MISSING
    ad-account-id config, by contrast, IS a misconfiguration and raises (mirrors HR's
    fail-loud-on-no-data-source posture) — there is a real difference between "not
    configured" (operator error, should be loud) and "API call failed" (external,
    should degrade).
    """

    def read(self, kind: str, config: Any, settings: Any) -> list[InsightRow] | None:
        ad_account_id = os.environ.get(_AD_ACCOUNT_ID_ENV, "").strip()
        if not ad_account_id:
            raise RuntimeError(
                f"ads-weekly needs a data source: set {_AD_ACCOUNT_ID_ENV} in the "
                "environment (the Meta ad account id, without the 'act_' prefix)."
            )
        date_preset = os.environ.get(_DATE_PRESET_ENV, "").strip() or _DEFAULT_DATE_PRESET
        try:
            token = _resolve_token(settings)
            return fetch_campaign_insights(ad_account_id, token=token, date_preset=date_preset)
        except (MetaInsightsError, CredentialStoreError, ValueError):
            # Degrade — the analyzer renders THIẾU, never fabricates numbers. This also
            # catches the credential-resolution failures `resolve_service_credentials`
            # raises (CredentialStoreError, its subclass CredentialDecryptError, and
            # ValueError from a malformed `account`/`token_env` reference) — the most
            # common of which is simply "operator hasn't filled in ADS_META_TOKEN yet",
            # exactly the state the template tells a new user to leave until later.
            # Never format/log the exception args here: a CredentialStoreError message
            # can echo back the configured account id or env-var NAME (not a secret
            # value, but still avoid growing that habit at this call site).
            return None


#: The pack's tool provider instance. Loaded by PackRegistry into Pack.tools.
TOOL_PROVIDER = AdsToolProvider()
