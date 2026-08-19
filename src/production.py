"""SkySakhNews canonical production entrypoint.

This module exists to keep emergency/operational policy out of version-file chains.
It imports the stable v9 core, applies a small set of runtime invariants, and starts
that core. Future production-only wiring belongs here; business logic should be
folded back into the core after it has proven stable in CI/runtime.
"""

import urllib.parse

import news_bot_v9 as core

VERSION = "stable-v9.6"
core.VERSION = VERSION

# ---------------------------------------------------------------------------
# Run-local page cache: Google resolution and article collection often request
# the same article twice. Cache by URL to cut latency and reduce source load.
# ---------------------------------------------------------------------------
_original_page_info = core.b.page_info
_PAGE_CACHE = {}


def cached_page_info(url):
    key = str(url or "")
    if not key:
        return {}
    if key not in _PAGE_CACHE:
        if len(_PAGE_CACHE) >= 128:
            _PAGE_CACHE.clear()
        _PAGE_CACHE[key] = _original_page_info(key)
    return _PAGE_CACHE[key]


core.b.page_info = cached_page_info


# ---------------------------------------------------------------------------
# A Russian publisher is not the same thing as a Russia story.
# Interfax /world/, TASS international sections, etc. must never become
# ru_pol/ru_eco/ru_security merely because the publisher itself is Russian.
# ---------------------------------------------------------------------------
INTERNATIONAL_PATH_MARKERS = (
    "/world/",
    "/international/",
    "/foreign/",
    "/mezhdunarodnaya-panorama/",
    "/mezhdunarodnaya-politika/",
)

FOREIGN_CONTEXT_MARKERS = [
    "canada", "канад", "mexico", "мексик", "iran", "иран", "israel", "израил",
    "china", "китай", "taiwan", "тайван", "usa", "u.s.", "сша", "america", "американ",
    "eu", "евросоюз", "европейск", "nato", "нато", "uk", "britain", "британ",
    "france", "франц", "germany", "герман", "japan", "япон", "korea", "коре",
    "tariff", "tariffs", "пошлин", "trade", "торгов", "sanctions", "санкц",
    "trump", "трамп", "white house", "белый дом",
]


def is_international_url(url):
    path = urllib.parse.urlparse(url or "").path.lower()
    return any(marker in path for marker in INTERNATIONAL_PATH_MARKERS)


def classify_v96(src_type, weight, title, rss_text, desc, url):
    # All non-Russian-source rules stay in the hardened v9.5 core.
    if src_type != "ru":
        return core.classify(src_type, weight, title, rss_text, desc, url)

    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if core.b.terms(text, core.b.NOISE):
        return None, 0, "noise"

    # Explicit Sakhalin geography is evaluated before national/international.
    if core.b.terms(text, core.b.LOCAL):
        if core.b.terms(text, core.b.QUAKE):
            return "sakh_quake", weight + 24, "ru_local_quake"
        if core.b.terms(text, core.b.LOCAL_EVENT):
            return "sakh_chp", weight + 20, "ru_local_chp"
        return "sakh", weight + 12, "ru_local"

    # Do not allow Moscow-city desk noise into national streams.
    if "/moscow/" in path:
        return None, 0, "moscow_noise"

    # International desk: classify by story geography, not publisher country.
    if is_international_url(url):
        if core.hits(text, core.RUSSIA_MARKERS):
            return "world_ru", weight + 18, "ru_source_world_about_russia"

        foreign_hits = set(core.hits(text, core.GEO_MARKERS + FOREIGN_CONTEXT_MARKERS))
        if len(foreign_hits) >= 2:
            return "geo", weight + 8, "ru_source_foreign_geo"

        # A foreign story with only one weak marker is safer to skip than to
        # mislabel as Russian politics/economy/security.
        return None, 0, "ru_source_foreign_weak"

    # Domestic Russian sections only from here down.
    if core.hits(text, core.SECURITY_MARKERS):
        return "ru_security", weight + 18, "ru_security"
    if core.b.terms(text, core.b.ECO):
        return "ru_eco", weight + 12, "ru_eco"
    if core.b.terms(text, core.b.POL) or core.hits(text, core.RUSSIA_MARKERS):
        return "ru_pol", weight + 10, "ru_pol"
    if len(set(core.hits(text, core.GEO_MARKERS))) >= 2:
        return "geo", weight + 6, "ru_geo"
    return None, 0, "ru_not_in_stream"


core.b.classify = classify_v96


_original_source_stream_guard = core.valid_source_stream


def valid_source_stream_v96(item):
    cat = item.get("category_key", "")
    url = item.get("url") or ""
    body = f"{item.get('title','')} {item.get('source_text','')}".lower()

    # Independent second barrier against the exact class of failure seen in
    # production: a foreign Interfax/TASS story labelled as a Russian stream.
    if cat in ("ru_security", "ru_eco", "ru_pol") and is_international_url(url):
        if not core.hits(body, core.RUSSIA_MARKERS):
            return False, "russia_stream_foreign_story"

    return _original_source_stream_guard(item)


core.valid_source_stream = valid_source_stream_v96


def main():
    core.b.main()


if __name__ == "__main__":
    main()
