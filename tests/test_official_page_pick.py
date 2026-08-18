"""The official-page picker: does it find the vendor's own page, and does it refuse the
reseller that merely mentions the vendor's name?

The second half is the point. The measured failure was not "no URL was found" — search
always returns something — it was that what came back was an aggregator, and citing an
aggregator is exactly what cost the `nguon` axis three benchmark rounds in a row.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.official_page_pick import (
    pick_official_urls,
    urls_in_bundle,
)


def _bundle(*urls: str) -> str:
    """A bundle shaped like `format_search_results` writes one: the URL on its own line
    inside the delimiters, snippet under it."""
    blocks = []
    for i, url in enumerate(urls, start=1):
        blocks.append(
            f"<<<EXTERNAL>>>\n[EXTERNAL_DATA source=host rank={i}]\nTiêu đề\n{url}\n"
            f"đoạn trích {i}\n<<<END>>>"
        )
    return "\n\n".join(blocks)


def test_urls_are_read_back_out_of_a_formatted_bundle_in_order():
    bundle = _bundle("https://www.spotify.com/vn/premium/", "https://zingmp3.vn/vip")
    assert urls_in_bundle(bundle) == [
        "https://www.spotify.com/vn/premium/",
        "https://zingmp3.vn/vip",
    ]


def test_duplicate_urls_collapse():
    bundle = _bundle("https://zingmp3.vn/vip", "https://zingmp3.vn/vip")
    assert urls_in_bundle(bundle) == ["https://zingmp3.vn/vip"]


def test_the_vendors_own_page_is_picked_for_each_entity():
    bundle = _bundle(
        "https://www.spotify.com/vn/premium/",
        "https://zingmp3.vn/vip",
    )
    picked = pick_official_urls(bundle, ["Spotify", "Zing MP3"], limit=5)
    assert picked == ["https://www.spotify.com/vn/premium/", "https://zingmp3.vn/vip"]


def test_a_multi_word_brand_matches_its_spaceless_domain():
    """"Zing MP3" → zingmp3.vn. Comparing raw names against hosts fails here, and this
    brief's entity list is mostly multi-word brands."""
    bundle = _bundle("https://zingmp3.vn/vip")
    assert pick_official_urls(bundle, ["Zing MP3"], limit=5) == ["https://zingmp3.vn/vip"]


def test_a_reseller_that_merely_mentions_the_brand_is_refused():
    """The precise failure the benchmark punished: an Amazon gift-card page for Spotify
    is not a Spotify source, however well it ranks."""
    bundle = _bundle("https://www.amazon.com/spotify-gift-card/dp/B07")
    assert pick_official_urls(bundle, ["Spotify"], limit=5) == []


def test_wikipedia_is_not_treated_as_official():
    bundle = _bundle("https://vi.wikipedia.org/wiki/Spotify")
    assert pick_official_urls(bundle, ["Spotify"], limit=5) == []


def test_youtube_com_is_refused_even_for_youtube_music():
    """The host literally contains the entity name, so a naive substring match picks it —
    but a YouTube Music subscription price does not live on a youtube.com video page."""
    bundle = _bundle("https://www.youtube.com/watch?v=abc")
    assert pick_official_urls(bundle, ["YouTube Music"], limit=5) == []


def test_at_most_one_url_per_entity():
    bundle = _bundle(
        "https://www.spotify.com/vn/premium/",
        "https://www.spotify.com/vn/free/",
    )
    assert pick_official_urls(bundle, ["Spotify"], limit=5) == [
        "https://www.spotify.com/vn/premium/"
    ]


def test_the_limit_caps_the_pick():
    bundle = _bundle(
        "https://www.spotify.com/vn/premium/",
        "https://zingmp3.vn/vip",
        "https://www.nhaccuatui.com/vip",
    )
    picked = pick_official_urls(
        bundle, ["Spotify", "Zing MP3", "Nhaccuatui"], limit=2
    )
    assert len(picked) == 2


def test_a_zero_or_negative_limit_picks_nothing():
    bundle = _bundle("https://www.spotify.com/vn/premium/")
    assert pick_official_urls(bundle, ["Spotify"], limit=0) == []


def test_an_empty_bundle_or_entity_list_is_not_an_error():
    assert pick_official_urls("", ["Spotify"], limit=3) == []
    assert pick_official_urls(_bundle("https://a.com"), [], limit=3) == []


def test_a_sentinel_only_bundle_yields_nothing_to_fetch():
    """A provider outage bundle carries no URLs — the picker must return [] so the
    caller skips fetching rather than treating the sentinel text as a target."""
    sentinel = (
        "[LỖI NGUỒN TÌM KIẾM] (truy vấn: giá Spotify) Không truy cập được web search"
    )
    assert pick_official_urls(sentinel, ["Spotify"], limit=3) == []


# --- host matching must not be a substring test ---------------------------------------
#
# The picked URL is FETCHED, and search results are attacker-influenceable, so a
# substring match ("does the host contain the brand name?") is both a source-quality bug
# and an unwanted-fetch-target bug. Each case below passed that substring test.


@pytest.mark.parametrize(
    "host",
    [
        "spotify.com.evil.tld",  # brand parked in a left-hand label
        "notspotify.com",  # brand as a suffix of a different word
        "my-spotify-hack.ru",  # brand embedded in a longer label
        "spotify.evil.com",  # brand as a subdomain of someone else's domain
    ],
)
def test_a_lookalike_host_is_not_official(host):
    bundle = _bundle(f"https://{host}/gia")
    assert pick_official_urls(bundle, ["Spotify"], limit=3) == []


@pytest.mark.parametrize(
    "host",
    ["www.spotify.com", "open.spotify.com", "spotify.co.uk"],
)
def test_the_real_domain_and_its_subdomains_stay_official(host):
    bundle = _bundle(f"https://{host}/premium")
    assert pick_official_urls(bundle, ["Spotify"], limit=3) == [f"https://{host}/premium"]


def test_a_two_part_public_suffix_still_resolves_to_the_brand():
    bundle = _bundle("https://vtv.com.vn/gia")
    assert pick_official_urls(bundle, ["VTV"], limit=3) == ["https://vtv.com.vn/gia"]


@pytest.mark.parametrize(
    ("host", "entity"),
    [("music.apple.com", "Apple Music"), ("www.apple.com", "Apple Music")],
)
def test_a_brand_whose_domain_drops_a_generic_product_word_still_matches(host, entity):
    """"Apple Music" lives on apple.com. Requiring the full name to equal the label
    skipped the official page of 2 of the 5 services in the brief that motivated this."""
    bundle = _bundle(f"https://{host}/")
    assert pick_official_urls(bundle, [entity], limit=3) == [f"https://{host}/"]


def test_that_allowance_does_not_open_the_door_to_a_lookalike():
    bundle = _bundle("https://apple.evil.com/")
    assert pick_official_urls(bundle, ["Apple Music"], limit=3) == []


def test_youtube_music_home_is_official_while_a_video_page_is_not():
    """`youtube.com` must stay refused — a video page is not a source for a subscription
    price — without also refusing YouTube Music's actual home."""
    assert pick_official_urls(
        _bundle("https://music.youtube.com/"), ["YouTube Music"], limit=3
    ) == ["https://music.youtube.com/"]
    assert pick_official_urls(
        _bundle("https://www.youtube.com/watch?v=abc"), ["YouTube Music"], limit=3
    ) == []


def test_a_vendor_whose_name_merely_contains_an_aggregators_is_not_swept_up():
    """The aggregator list is matched on whole labels, so `amazonia-music.vn` is not
    treated as Amazon."""
    bundle = _bundle("https://amazonia-music.vn/gia")
    assert pick_official_urls(bundle, ["Amazonia Music"], limit=3) == [
        "https://amazonia-music.vn/gia"
    ]


# --- a brand-name label on any TLD is not proof of officiality -------------------------


@pytest.mark.parametrize("host", ["spotify.xyz", "spotify.tk", "spotify.top"])
def test_a_brand_name_on_an_abuse_tld_is_refused(host):
    """The registrable-label rule asks "is this label the brand?" and cannot ask "is this
    the brand's real TLD" without a per-vendor mapping. Squatted brand domains on free /
    abuse TLDs are the ordinary case, and the picked URL gets FETCHED."""
    bundle = _bundle(f"https://{host}/gia")
    assert pick_official_urls(bundle, ["Spotify"], limit=3) == []


def test_the_tld_guard_does_not_reject_ordinary_vendor_tlds():
    for host in ("www.spotify.com", "zingmp3.vn", "spotify.co.uk", "vtv.com.vn"):
        entity = {"zingmp3.vn": "Zing MP3", "vtv.com.vn": "VTV"}.get(host, "Spotify")
        assert pick_official_urls(_bundle(f"https://{host}/x"), [entity], limit=3) == [
            f"https://{host}/x"
        ]


# --- one vendor must not spend two of very few page slots -----------------------------


def test_two_entities_sharing_one_site_yield_one_page():
    """"Apple" and "Apple Music" both resolve to apple.com, and dropping generic product
    tails makes that collision likelier. Two pages of one vendor would re-read one source
    at the cost of another vendor's page."""
    bundle = _bundle(
        "https://www.apple.com/apple-music/",
        "https://www.apple.com/vn/music/",
    )
    assert pick_official_urls(bundle, ["Apple Music", "Apple"], limit=5) == [
        "https://www.apple.com/apple-music/"
    ]


def test_distinct_vendors_are_still_both_picked():
    bundle = _bundle("https://www.spotify.com/vn/", "https://zingmp3.vn/vip")
    assert pick_official_urls(bundle, ["Spotify", "Zing MP3"], limit=5) == [
        "https://www.spotify.com/vn/",
        "https://zingmp3.vn/vip",
    ]


def test_a_subdomain_counts_as_the_same_host_slot_only_when_identical():
    """`open.spotify.com` and `www.spotify.com` are different hosts, so both remain
    eligible — dedup is per-host, deliberately not per-registrable-domain, because a
    vendor's regional and product sites do carry different figures."""
    bundle = _bundle("https://open.spotify.com/x", "https://www.spotify.com/vn/")
    assert pick_official_urls(bundle, ["Spotify"], limit=5) == ["https://open.spotify.com/x"]


# --- Which PAGE of the right host: the free-tier trap -------------------------------
# Picking an official host is necessary but not sufficient. On the live streaming-brief
# bundle the picker chose the correct site and still returned no price, because that
# site's free-tier page outranked its priced one.


def test_the_priced_page_wins_over_the_free_page_on_the_same_official_host():
    # Exactly the live bundle order that produced 0 price tokens: /free/ came first.
    bundle = _bundle(
        "https://www.spotify.com/vn-vi/free/",
        "https://www.spotify.com/vn-vi/premium/",
        "https://www.spotify.com/vn-en/free/",
        "https://www.spotify.com/vn-vi/signup",
    )
    picked = pick_official_urls(bundle, ["Spotify"], limit=3)
    assert picked == ["https://www.spotify.com/vn-vi/premium/"], (
        "the page carrying the price must beat the higher-ranked free-tier page"
    )


def test_a_signup_page_does_not_win_just_because_it_says_premium():
    """`/premium/signup` carries a pricing hint AND a non-pricing one; a form is not a
    price list, so the plain pricing page must still win."""
    bundle = _bundle(
        "https://www.spotify.com/vn-vi/premium/signup",
        "https://www.spotify.com/vn-vi/premium/",
    )
    picked = pick_official_urls(bundle, ["Spotify"], limit=3)
    assert picked == ["https://www.spotify.com/vn-vi/premium/"]


def test_provider_rank_still_decides_when_no_page_looks_priced():
    """No pricing hint anywhere: the preference must not re-order pages it knows nothing
    about."""
    bundle = _bundle("https://zingmp3.vn/", "https://zingmp3.vn/album/abc")
    picked = pick_official_urls(bundle, ["Zing MP3"], limit=3)
    assert picked == ["https://zingmp3.vn/"], "first-in-bundle stays the tie-break"


def test_a_vietnamese_pricing_path_is_recognised():
    bundle = _bundle("https://zingmp3.vn/download", "https://zingmp3.vn/bang-gia")
    picked = pick_official_urls(bundle, ["Zing MP3"], limit=3)
    assert picked == ["https://zingmp3.vn/bang-gia"]


def test_preferring_a_priced_page_never_crosses_to_another_host():
    """The ranking runs only among pages of an already-accepted official host, so a
    lookalike with a perfect pricing path must still lose to the real site's plain page."""
    bundle = _bundle(
        "https://spotify.com.evil.tld/premium/pricing",
        "https://www.spotify.com/vn-vi/",
    )
    picked = pick_official_urls(bundle, ["Spotify"], limit=3)
    assert picked == ["https://www.spotify.com/vn-vi/"]


def test_a_bare_host_is_neutral_not_penalised():
    """An empty path must score 0, not match a hint by accident."""
    bundle = _bundle("https://www.spotify.com", "https://www.spotify.com/vn-vi/free/")
    picked = pick_official_urls(bundle, ["Spotify"], limit=3)
    assert picked == ["https://www.spotify.com"], "a free page must lose to a neutral one"
