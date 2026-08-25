"""Title-first, geography-first stream reconciliation for SkySakhNews.

A publisher is never treated as the geography of a story.  The source headline
is the primary signal; only the beginning of the article is used as a fallback.
"""

from __future__ import annotations

from urllib.parse import urlparse

import editorial_gate as gate

WORLD_MEDIA = ("bbc", "reuters", "guardian", "associated press", " ap ")
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online")
TECH_MEDIA = ("technology", "tech", "wired", "verge")
RUSSIAN_MEDIA = ("interfax", "интерфакс", "tass", "тасс")

INTERNATIONAL_PATHS = (
    "/world/",
    "/international/",
    "/foreign/",
    "/mezhdunarodnaya-panorama/",
    "/mezhdunarodnaya-politika/",
)
DOMESTIC_PATHS = (
    "/russia/",
    "/business/",
    "/economy/",
    "/politics/",
    "/politika/",
    "/ekonomika/",
)

GLOBAL_ECONOMY = (
    "brent", "wti", "opec", "опек", "ice futures", "фьючерс",
    "wall street", "nasdaq", "s&p", "dow jones",
    "нефть дорожает", "нефть дешевеет", "мировые цены",
    "евц", "ецб", "фрс", "банк китая", "китайский цб",
)
DOMESTIC_ECONOMY = (
    "россельхозбанк", "сбер", "сбербанк", "втб", "газпром", "роснефт",
    "мосбирж", "imoex", "минфин", "центробанк", "цб рф", "рубль",
    "российск", "рф ", "кабмин", "новороссийск", "фнс", "росстат",
)


def _low(value) -> str:
    return str(value or "").lower()


def _contains_any(text: str, markers) -> bool:
    low = _low(text)
    return any(marker in low for marker in markers)


def _title(candidate) -> str:
    return str(candidate.get("title") or "")


def _lead(candidate, limit: int = 1100) -> str:
    return str(candidate.get("source_text") or "")[:limit]


def _topics(text: str):
    return set(gate.infer_topics(text))


def _title_topics(candidate):
    return _topics(_title(candidate))


def _lead_topics(candidate):
    return _topics(_lead(candidate))


def _source_name(candidate) -> str:
    return " " + _low(candidate.get("source")) + " "


def _host(candidate) -> str:
    return urlparse(str(candidate.get("url") or "")).netloc.lower()


def _path(candidate) -> str:
    return urlparse(str(candidate.get("url") or "")).path.lower()


def _source_is_world_media(candidate) -> bool:
    return any(marker in _source_name(candidate) for marker in WORLD_MEDIA)


def _source_is_local_media(candidate) -> bool:
    source = _source_name(candidate)
    host = _host(candidate)
    return any(marker in source or marker in host for marker in LOCAL_MEDIA)


def _source_is_tech_media(candidate) -> bool:
    return any(marker in _source_name(candidate) for marker in TECH_MEDIA)


def _source_is_russian_media(candidate) -> bool:
    return any(marker in _source_name(candidate) for marker in RUSSIAN_MEDIA)


def _international_section(candidate) -> bool:
    return any(marker in _path(candidate) for marker in INTERNATIONAL_PATHS)


def _domestic_section(candidate) -> bool:
    return any(marker in _path(candidate) for marker in DOMESTIC_PATHS)


def _local_from_title(title_topics):
    if "quake" in title_topics:
        return "sakh_quake"
    if "weather" in title_topics and "incident" not in title_topics:
        return "sakh"
    if "incident" in title_topics:
        return "sakh_chp"
    return "sakh"


def _domestic_topic_from_title(title_topics):
    if "security" in title_topics:
        return "ru_security"
    if "incident" in title_topics:
        return "ru_incident"
    if "economy" in title_topics:
        return "ru_eco"
    if "politics" in title_topics:
        return "ru_pol"
    return None


def suggest_category(candidate):
    """Return the semantically preferred category key, or None for off-topic."""

    current = str(candidate.get("category_key") or "")
    title_text = _title(candidate)
    lead_text = _lead(candidate)
    title_topics = _title_topics(candidate)
    lead_topics = _lead_topics(candidate)

    if "it" in title_topics:
        return "it"
    if _source_is_tech_media(candidate) and "it" in lead_topics:
        return "it"

    if "local" in title_topics and (
        "quake" in title_topics
        or "weather" in title_topics
        or "incident" in title_topics
    ):
        return _local_from_title(title_topics)

    if "foreign" in title_topics:
        if _source_is_world_media(candidate) and "russia" in (
            title_topics | lead_topics
        ):
            return "world_ru"
        return "geo"

    if "local" in title_topics:
        return _local_from_title(title_topics)

    if "local" in lead_topics:
        if "quake" in title_topics or (
            "quake" in lead_topics and _source_is_local_media(candidate)
        ):
            return "sakh_quake"
        if "weather" in title_topics:
            return "sakh"
        if "incident" in title_topics:
            return "sakh_chp"
        return "sakh"

    if _source_is_local_media(candidate):
        return None

    if _international_section(candidate):
        if _source_is_world_media(candidate) and "russia" in (
            title_topics | lead_topics
        ):
            return "world_ru"
        return "geo" if (
            "foreign" in title_topics
            or "foreign" in lead_topics
            or "russia" in title_topics
            or "russia" in lead_topics
        ) else None

    if _source_is_world_media(candidate):
        if "russia" in title_topics or "russia" in lead_topics:
            return "world_ru"
        if "foreign" in title_topics or "foreign" in lead_topics:
            return "geo"

    direct = _domestic_topic_from_title(title_topics)
    if direct == "ru_eco":
        if _contains_any(title_text, GLOBAL_ECONOMY):
            return "geo"
        if (
            "russia" in title_topics
            or _contains_any(title_text, DOMESTIC_ECONOMY)
            or (_source_is_russian_media(candidate) and _domestic_section(candidate))
        ):
            return "ru_eco"
        return None
    if direct == "ru_pol":
        if "foreign" in title_topics and "russia" not in title_topics:
            return "geo"
        if (
            "russia" in title_topics
            or _source_is_russian_media(candidate)
            or _domestic_section(candidate)
        ):
            return "ru_pol"
        return None
    if direct in {"ru_security", "ru_incident"}:
        if "foreign" in title_topics and "russia" not in title_topics:
            return "geo"
        return direct

    if _source_is_russian_media(candidate) and _domestic_section(candidate):
        if "security" in lead_topics:
            return "ru_security"
        if "incident" in lead_topics:
            return "ru_incident"
        if "economy" in lead_topics:
            if _contains_any(title_text + " " + lead_text, GLOBAL_ECONOMY):
                return "geo"
            if _contains_any(title_text + " " + lead_text, DOMESTIC_ECONOMY):
                return "ru_eco"
        if "politics" in lead_topics:
            return "ru_pol"

    if "foreign" in lead_topics:
        return "geo"

    if current == "it" and "it" in lead_topics:
        return "it"
    return None
