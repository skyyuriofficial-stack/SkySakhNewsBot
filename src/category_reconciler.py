"""Title-first, geography-first stream reconciliation for SkySakhNews.

A publisher is never treated as the geography of a story. The source headline
is the primary signal; only the beginning of the article is used as a fallback.
Topic markers are matched by token prefixes, never by arbitrary substrings.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import editorial_gate as gate

WORLD_MEDIA = ("bbc", "reuters", "guardian", "associated press", " ap ")
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online")
TECH_MEDIA = ("technology", "tech", "wired", "verge")
RUSSIAN_MEDIA = ("interfax", "интерфакс", "tass", "тасс")


# District centres, islands and settlements frequently used without the word
# "Sakhalin" in otherwise local headlines.
gate.LOCAL_MARKERS = gate.LOCAL_MARKERS + (
    "анив", "макаров", "смирных", "тымовск", "томари", "шахтерск",
    "горнозаводск", "чехов", "быков", "синегорск", "троицк", "лугов",
    "новоалександровск", "лютог", "итуруп", "кунашир", "шикотан",
    "монерон", "рейдово", "малокурильск", "курильск", "охотское море",
)

# Avoid ambiguous three-letter fragments such as "инд", "груз" and "куб".
# They previously classified "индекс", "грузовик" and Kuban-related stories
# as foreign. Token-aware matching below also prevents NATO from being found
# inside the word "санаторий".
gate.FOREIGN = (
    "сша", "америк", "трамп", "канада", "канад", "мексик", "иран",
    "израил", "китай", "тайван", "нато", "натов", "евросоюз", "британ",
    "франц", "герман", "япон", "корея", "кореи", "корее", "корею",
    "корей", "украин", "зеленск", "турц", "сири", "ирак", "индия",
    "индии", "индией", "индий", "пакистан", "армени", "казахстан",
    "белорус", "грузия", "грузии", "грузией", "грузин", "азербайдж",
    "молдов", "куба", "кубы", "кубе", "кубу", "кубой", "кубин",
    "white house", "usa", "canada", "mexico", "iran", "israel", "china",
    "taiwan", "nato", "ukraine", "japan", "germany", "france", "britain",
    "turkey", "syria", "india", "georgia", "cuba",
)

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
    "российск", "рф", "кабмин", "новороссийск", "фнс", "росстат",
)

# Consumer advice, travel SEO, recipes and similar syndicated service content
# do not belong to any SkySakhNews stream unless a real hard-news event is the
# central subject of the headline.
TRAVEL_LIFESTYLE = (
    "санатори", "отдых", "курорт", "туризм", "турист", "пляж", "отпуск",
    "путевк", "отел", "гостиниц", "жиль", "дач", "пенсионер",
    "путешеств", "поездк", "море", "лазаревск", "анап", "ейск", "сочи",
    "крым", "бронирован",
)
SEO_PROMO = (
    "райск", "по карману", "сентябрьский хит", "хит с жиль", "от 1000 руб",
    "недорог", "дешев", "выгодн", "сэконом", "где отдохнуть",
    "лучшие места", "не санаторий и не дача", "без переплат", "секрет",
)
SERVICE_CONTENT = (
    "гороскоп", "рецепт", "головолом", "тест на внимательность", "церковный праздник",
    "народные приметы", "как выбрать", "как сэкономить", "лайфхак", "совет дачник",
    "что приготовить", "куда поехать", "где отдохнуть",
)
INSTITUTIONAL_ECONOMY = (
    "центробанк", "цб рф", "минфин", "правительств", "госдум", "налог",
    "бюджет", "тариф", "инфляц", "ключев ставк", "росстат", "фнс",
    "рынок труда", "безработиц", "экспорт", "импорт",
)


def _low(value) -> str:
    return str(value or "").lower().replace("ё", "е")


def _normalized_tokens(value: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+", gate._norm(value), flags=re.I)


def _marker_matches(text: str, marker: str) -> bool:
    """Match a word/phrase only at token starts, never inside another word."""
    text_tokens = _normalized_tokens(text)
    marker_tokens = _normalized_tokens(marker)
    if not marker_tokens or not text_tokens:
        return False

    width = len(marker_tokens)
    for start in range(0, len(text_tokens) - width + 1):
        window = text_tokens[start:start + width]
        if all(word.startswith(prefix) for word, prefix in zip(window, marker_tokens)):
            return True
    return False


def _token_aware_contains(text: str, markers) -> bool:
    return any(_marker_matches(text, marker) for marker in markers)


# editorial_gate.infer_topics calls this function dynamically. Replacing the
# old substring matcher fixes all topic groups, not only this one regression.
gate._contains = _token_aware_contains


def _contains_any(text: str, markers) -> bool:
    return _token_aware_contains(text, markers)


def _hit_count(text: str, markers) -> int:
    return sum(1 for marker in markers if _marker_matches(text, marker))


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


def _soft_content_offtopic(
    candidate,
    title_text: str,
    lead_text: str,
    title_topics: set[str],
    lead_topics: set[str],
) -> bool:
    combined = f"{title_text} {lead_text}"
    all_topics = title_topics | lead_topics

    hard_topics = {"security", "incident", "politics", "quake", "weather", "it"}
    if hard_topics & title_topics:
        return False

    # An economy story is hard news only when the title contains an actual
    # institution/indicator, not merely a price in rubles for a holiday offer.
    institutional_economy = _contains_any(title_text, INSTITUTIONAL_ECONOMY)
    if "economy" in title_topics and institutional_economy:
        return False

    travel_hits = _hit_count(combined, TRAVEL_LIFESTYLE)
    promo_hits = _hit_count(combined, SEO_PROMO)
    service_hits = _hit_count(combined, SERVICE_CONTENT)

    if travel_hits >= 2 and promo_hits >= 1:
        return True
    if service_hits >= 1 and not (hard_topics & all_topics):
        return True
    if (
        _source_is_local_media(candidate)
        and "local" not in all_topics
        and travel_hits >= 2
    ):
        return True
    return False


def suggest_category(candidate):
    """Return the semantically preferred category key, or None for off-topic."""

    current = str(candidate.get("category_key") or "")
    title_text = _title(candidate)
    lead_text = _lead(candidate)
    title_topics = _title_topics(candidate)
    lead_topics = _lead_topics(candidate)

    if _soft_content_offtopic(
        candidate,
        title_text,
        lead_text,
        title_topics,
        lead_topics,
    ):
        return None

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
