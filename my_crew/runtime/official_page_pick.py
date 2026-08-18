"""Pick the OFFICIAL page URL for an entity out of a search bundle — pure code, no LLM.

Why this exists (measured, not assumed): sprint mode collects only through
`collect_prefetch` → `web_search_tool`, and that tool is deliberately snippets-only
("NEVER a follow-up GET to any result URL"). A provider snippet for a vendor's own
page rarely carries the figure being asked for — a price, a tier name — so the model
was forced down to resellers and blog posts, and the blind judge docked the `nguon`
axis for it 3 rounds running. Fixing the prompt did not move the score: the model
obeyed and labelled its sources honestly, which does not make a secondary source good.

The pick is CODE, not a model call, on purpose. Sprint mode exists because a code-paced
pipeline beat the tool loop on wall-clock; spending an LLM call to choose a link would
give that back at the exact point the mode was built to avoid.

`SearchResult.source` URLs already ride inside the formatted bundle body (v73, so a
tool-loop agent could chain search → scrape), so this reads the bundle the sprint step
already has. It adds NO search, NO egress, and no new parsing of provider payloads.
"""

from __future__ import annotations

import re
import unicodedata

#: A result URL as `_safe_url` writes it into a formatted bundle body: its own line.
_URL_RE = re.compile(r"https?://[^\s\]\[<>\"']+", re.IGNORECASE)

#: Hosts that are never the entity's own site even when the entity name appears in the
#: URL. Aggregators/resellers/encyclopaedias are exactly what the judge marks down, so
#: a "chính thức" pick must refuse them rather than pick the highest-ranked lookalike.
_NON_OFFICIAL_HOST_MARKERS = (
    "wikipedia.", "wikimedia.", "facebook.", "twitter.", "x.com", "instagram.",
    "youtube.com", "tiktok.", "reddit.", "medium.", "blogspot.", "wordpress.",
    "quora.", "pinterest.", "linkedin.", "amazon.", "shopee.", "lazada.",
    "tiki.vn", "sendo.vn", "ebay.", "alibaba.", "google.", "bing.", "yahoo.",
)


#: Two-part public suffixes common for the vendors this runs against, so `spotify.co.uk`
#: and `vtv.com.vn` still resolve to their brand label. Not a full public-suffix list —
#: an unknown two-part suffix degrades to "not official", i.e. one fewer page fetched,
#: which is the safe direction. A full PSL dependency is not warranted for that.
_TWO_PART_SUFFIXES = frozenset({
    "co.uk", "com.vn", "net.vn", "org.vn", "com.au", "co.jp", "co.kr", "com.br",
    "co.in", "com.sg", "com.my", "co.th", "com.tw", "co.nz", "com.hk", "com.cn",
})


#: TLDs where a brand-name domain is far more likely a squat than the vendor's own site.
#: The registrable-label rule below asks "is this label the brand?" and deliberately does
#: NOT ask "is this the brand's real TLD" — it cannot, without a per-vendor mapping. That
#: leaves `spotify.xyz` indistinguishable from `spotify.com`, and free/abuse TLDs are the
#: ordinary home of such squats, not an exotic case. Rejecting them costs at most one
#: skipped page (the snippet bundle still stands); accepting one costs a fetch of, and a
#: citation to, somebody else's page.
_ABUSE_TLDS = frozenset({"tk", "ml", "ga", "cf", "gq", "xyz", "top", "buzz", "click"})


def _fold(text: str) -> str:
    """Lowercase + strip diacritics, so "Nhaccuatui" matches "nhaccuatui" and a
    Vietnamese entity name with dấu still matches its ASCII domain."""
    decomposed = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _host_of(url: str) -> str:
    match = re.match(r"https?://([^/:?#]+)", url, re.IGNORECASE)
    return match.group(1).lower() if match else ""


#: Generic product words that are part of a brand's NAME but not of its domain. "Apple
#: Music" lives on apple.com, "YouTube Music" on youtube.com — so the full-name key
#: alone would skip the official page of every brand shaped this way, which is 2 of the
#: 5 entities in the brief that motivated this module.
_GENERIC_BRAND_TAILS = frozenset({"music", "premium", "vn", "vietnam", "app", "online"})


def _entity_key(entity: str) -> str:
    """The entity name reduced to the letters a domain would keep: "Zing MP3" → "zingmp3",
    "YouTube Music" → "youtubemusic". Domains drop spaces and punctuation, so the
    comparison has to as well or every multi-word brand fails to match its own site."""
    return re.sub(r"[^a-z0-9]", "", _fold(entity))


def _entity_keys(entity: str) -> list[str]:
    """Every domain label that would legitimately represent `entity`.

    The full name first ("youtubemusic"), then the name minus a trailing generic product
    word ("youtube"), so both `zingmp3.vn` and `apple.com` can be recognised. The tail is
    only dropped when something remains: "Music" alone must not reduce to "".
    """
    keys = [_entity_key(entity)]
    words = [w for w in re.split(r"[\s_-]+", _fold(entity)) if w]
    if len(words) > 1 and words[-1] in _GENERIC_BRAND_TAILS:
        head = re.sub(r"[^a-z0-9]", "", "".join(words[:-1]))
        if head:
            keys.append(head)
    return [k for k in keys if k]


def _domain_labels(host: str) -> list[str]:
    """The host's labels with `www.` dropped: "open.spotify.com" → [open, spotify, com]."""
    labels = [lbl for lbl in _fold(host).split(".") if lbl]
    if labels and labels[0] == "www":
        labels = labels[1:]
    return labels


#: Hosts on an aggregator domain that ARE a product's own home and do carry its pricing.
#: `youtube.com` must stay blocked (a video page is not a source for a subscription
#: price) while `music.youtube.com` is exactly the official page this round wants.
_AGGREGATOR_EXCEPTIONS = frozenset({"music.youtube.com"})


def _is_aggregator(host: str) -> bool:
    """True for a known aggregator/reseller/encyclopaedia host.

    Matched against the host's own labels rather than as a substring, so a vendor whose
    name merely contains an aggregator's (say `amazonia-music.vn`) is not swept up.
    """
    host = _fold(host)
    if host in _AGGREGATOR_EXCEPTIONS:
        return False
    labels = _domain_labels(host)
    for marker in _NON_OFFICIAL_HOST_MARKERS:
        marker_labels = [lbl for lbl in marker.strip(".").split(".") if lbl]
        if not marker_labels:
            continue
        # The marker's labels must appear as a contiguous run of WHOLE host labels.
        for i in range(len(labels) - len(marker_labels) + 1):
            if labels[i : i + len(marker_labels)] == marker_labels:
                return True
    return False


def _is_official_host(host: str, entity: str) -> bool:
    """True when `host` looks like the entity's OWN site.

    The entity's letters must equal a WHOLE domain label — never a substring of the host.
    Substring matching is unsafe here because the picked URL is then fetched, and
    search results are attacker-influenceable: `spotify.com.evil.tld`,
    `notspotify.com` and `my-spotify-hack.ru` all contain "spotify" and all passed a
    substring test, which would have turned "prefer the official source" into "fetch
    whatever ranked well and mentioned the brand".

    Only the last two labels are eligible (the registrable domain plus its TLD), so a
    brand name parked in a left-hand label — the `spotify.com.evil.tld` shape — cannot
    qualify, while real subdomains like `open.spotify.com` still do.

    The aggregator check runs first and dominates the name match: `youtube.com`
    contains "youtube" but a YouTube Music price does not live on a video page, and
    `amazon.../spotify-gift-card` is a reseller.
    """
    if not host:
        return False
    if _is_aggregator(host):
        return False
    keys = _entity_keys(entity)
    if not keys:
        return False
    labels = _domain_labels(host)
    if not labels:
        return False
    # Exactly ONE eligible label: the registrable domain. Dropping a two-part public
    # suffix first (`spotify.co.uk` → spotify) rather than allowing the last two labels
    # generally, because the general form also admits `spotify.evil.com`, where the
    # brand is a subdomain of somebody else's domain.
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_PART_SUFFIXES:
        registrable = labels[-3]
    elif len(labels) >= 2:
        registrable = labels[-2]
    else:
        registrable = labels[0]
    if labels[-1] in _ABUSE_TLDS:
        return False
    return re.sub(r"[^a-z0-9]", "", registrable) in set(keys)


def urls_in_bundle(bundle: str) -> list[str]:
    """Every result URL in a formatted search bundle, in bundle order, de-duplicated."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.finditer(str(bundle or "")):
        url = match.group(0).rstrip(".,;)")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


#: Path words marking the page of a vendor's site that carries subscription figures.
#: Folded and matched against the URL path, never the host — a host label is the brand's
#: identity and is already decided by `_is_official_host`; these only choose BETWEEN pages
#: of a host already accepted as official, so a match here can never redirect a fetch to
#: another site. Ordered by how directly the word implies a published price.
_PRICING_PATH_HINTS = (
    "premium", "pricing", "price", "plans", "plan", "subscription", "subscribe",
    "gia", "banggia", "goi", "upgrade", "student", "family", "duo",
)

#: Path words marking a page that is on the right host but deliberately NOT the priced
#: one. "free" is the trap this exists for: a vendor's free-tier page ranks first for the
#: brand and is a legitimate official page, so nothing else in this module rejects it.
_NON_PRICING_PATH_HINTS = ("free", "signup", "sign-up", "register", "download", "login")


def _path_of(url: str) -> str:
    """The URL's path+query, folded — everything after the host. Returns "" for a bare
    host, which scores as neutral rather than matching any hint."""
    without_scheme = re.sub(r"^https?://", "", str(url or ""), flags=re.IGNORECASE)
    _, sep, rest = without_scheme.partition("/")
    return _fold(rest) if sep else ""


def _pricing_affinity(url: str) -> int:
    """How likely this page of an official site carries the subscription figures: +1 for a
    pricing word in the path, -1 for an explicitly non-pricing one, 0 when neither.

    Why this is needed even though the host is already right (measured, not assumed): on
    the live bundle for the streaming brief, `spotify.com` contributed `/vn-vi/free/`,
    `/vn-vi/premium/`, `/vn-en/free/` and `/vn-vi/signup`. Provider rank put `/free/`
    first, so the picker fetched it — 1785 chars, ZERO price tokens — while `/premium/`
    sat unfetched in the same bundle carrying 27 of them ("33.000 ₫ cho 3 tháng, sau đó
    là 65.000 ₫/tháng"). The fetch round worked exactly as designed and still delivered
    nothing the brief asked for, because relevance-to-the-QUERY (what rank encodes) is
    not the same question as which-page-holds-the-NUMBER.
    """
    path = _path_of(url)
    if not path:
        return 0
    # Non-pricing wins ties: `/premium/signup` is a signup form, not a price list, and
    # over-fetching a form page costs one of only three page slots.
    if any(hint in path for hint in _NON_PRICING_PATH_HINTS):
        return -1
    if any(hint in path for hint in _PRICING_PATH_HINTS):
        return 1
    return 0


def pick_official_urls(bundle: str, entities: list[str], *, limit: int) -> list[str]:
    """At most one official-looking URL per entity, capped at `limit`, in entity order.

    Returns [] when nothing qualifies — the caller must treat that as "fetch nothing"
    and carry on with the snippet bundle unchanged, never as an error.

    Among a host's official pages the one whose PATH implies pricing wins, with provider
    rank as the tie-break (see `_pricing_affinity`). Rank alone picked the free-tier page
    over the priced one on real data, which made the round fire correctly and return no
    usable figure.

    De-duplicated by HOST, not by URL: related entities legitimately share one site
    ("Apple" and "Apple Music" both resolve to apple.com, and `_entity_keys` stripping
    generic product tails makes that collision likelier), and two pages of the same
    vendor would spend two of very few page slots to re-read one source.
    """
    if limit <= 0:
        return []
    urls = urls_in_bundle(bundle)
    if not urls:
        return []
    picked: list[str] = []
    taken_hosts: set[str] = set()
    for entity in entities:
        # Every official URL for this entity, still in bundle order, then the best page
        # among them. Collecting first (rather than breaking on the first match) is the
        # whole change: the previous loop could not see that a better page existed.
        candidates = [
            url for url in urls
            if _host_of(url) not in taken_hosts and _is_official_host(_host_of(url), entity)
        ]
        if not candidates:
            continue
        # `max` keeps the FIRST of equal scores, preserving provider rank as the tie-break.
        best = max(candidates, key=_pricing_affinity)
        picked.append(best)
        taken_hosts.add(_host_of(best))
        if len(picked) >= limit:
            break
    return picked[:limit]
