"""Headline-first and geography-first stream reconciliation for SkySakhNews.

The publisher domain is never treated as the geography of the story. The
headline is authoritative; the article lead is only a controlled fallback.
Topic markers are matched on token boundaries to avoid false positives such as
NATO inside the Russian word "санаторий".
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import editorial_gate as gate

WORLD_MEDIA = ("bbc", "reuters", "guardian", "associated press", " ap ")
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online")
TECH_MEDIA = ("technology", "tech", "wired", "verge")
RUSSIAN_MEDIA = ("interfax", "интерфакс", "tass", "тасс")

gate.LOCAL_MARKERS = gate.LOCAL_MARKERS + (
    "анив", "макаров", "смирных", "тымовск", "томари", "шахтерск",
    "горнозаводск", "чехов", "быков", "синегорск", "троицк", "лугов",
    "новоалександровск", "лютог", "итуруп", "кунашир", "шикотан",
    "монерон", "рейдово", "малокурильск", "курильск", "охотское море",
)

gate.INCIDENT = gate.INCIDENT + (
    "лишилась денег", "лишился денег", "выманил", "обманули", "мошенничество",
    "наркотик", "нелегальный улов", "опрокидывание", "сошел с проезжей части",
)

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

EXACT_TOPIC_MARKERS = {
    "сша", "нато",
    "индия", "индии", "индией",
    "грузия", "грузии", "грузией",
    "корея", "кореи", "корее", "корею",
    "куба", "кубы", "кубе", "кубу", "кубой",
    "usa", "nato", "india", "georgia", "cuba",
}

INTERNATIONAL_PATHS = (
    "/world/", "/international/", "/foreign/",
    "/mezhdunarodnaya-panorama/", "/mezhdunarodnaya-politika/",
)
DOMESTIC_PATHS = (
    "/russia/", "/business/", "/economy/", "/politics/",
    "/politika/", "/ekonomika/",
)

GLOBAL_ECONOMY = (
    "brent", "wti", "opec", "опек", "ice futures", "фьючерс",
    "wall street", "nasdaq", "s&p", "dow jones",
    "нефть дорожает", "нефть дешевеет", "мировые цены",
    "ецб", "фрс", "банк китая", "китайский цб",
)
DOMESTIC_ECONOMY = (
    "втб", "россельхозбанк", "сбер", "сбербанк", "газпром", "роснефт",
    "мосбирж", "imoex", "минфин", "центробанк", "цб рф", "рубль",
    "российск", "рф", "кабмин", "новороссийск", "фнс", "росстат",
    "рынок сбережений", "трлн рублей", "газификац", "дфо",
)
DOMESTIC_POLITICS = (
    "путин", "кремл", "госдум", "совфед", "правительств", "кабмин",
    "министр", "губернатор", "президент россии", "мид россии", "совбез",
)
LOCAL_HARM_TITLE = (
    "погиб", "пострад", "дтп", "авари", "пожар", "лишилась денег",
    "лишился денег", "выманил", "задержали", "задержан", "наркотик",
    "мошенн", "пропал", "разыскивают", "уголовное дело", "опрокинулся",
)

TRAVEL_LIFESTYLE = (
    "санатори", "отдых", "курорт", "туризм", "турист", "пляж", "отпуск",
    "путевк", "отел", "гостиниц", "жиль", "дач", "пенсионер",
    "путешеств", "поездк", "лазаревск", "анап", "ейск", "сочи",
    "крым", "бронирован",
)
SEO_PROMO = (
    "райск", "по карману", "сентябрьский хит", "хит с жиль", "от 1000 руб",
    "недорог", "дешев", "выгодн", "сэконом", "где отдохнуть",
    "лучшие места", "не санаторий и не дача", "без переплат",
)
SERVICE_CONTENT = (
    "гороскоп", "рецепт", "головолом", "тест на внимательность",
    "церковный праздник", "народные приметы", "как выбрать",
    "как сэкономить", "лайфхак", "что приготовить", "куда поехать",
)
INSTITUTIONAL_ECONOMY = (
    "втб", "центробанк", "цб рф", "минфин", "правительств", "госдум",
    "налог", "бюджет", "тариф", "инфляц", "ключев ставк", "росстат",
    "фнс", "рынок труда", "безработиц", "экспорт", "импорт",
    "рынок сбережений", "трлн рублей", "газификац",
)


def _low(value) -> str:
    return str(value or "").lower().replace("ё", "е")


def _normalized_tokens(value: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+", gate._norm(value), flags=re.I)


def _marker_matches(text: str, marker: str) -> bool:
    text_tokens = _normalized_tokens(text)
    marker_tokens = _normalized_tokens(marker)
    if not marker_tokens or not text_tokens:
        return False

    if len(marker_tokens) == 1 and marker_tokens[0] in EXACT_TOPIC_MARKERS:
        return marker_tokens[0] in text_tokens

    width = len(marker_tokens)
    for start in range(0, len(text_tokens) - width + 1):
        window = text_tokens[start:start + width]
        if all(word.startswith(prefix) for word, prefix in zip(window, marker_tokens)):
            return True
    return False


def _token_aware_contains(text: str, markers) -> bool:
    return any(_marker_matches(text, marker) for marker in markers)


gate._contains = _token_aware_contains


def _contains_any(text: str, markers) -> bool:
    return _token_aware_contains(text, markers)


def _hit_count(text: str, markers) -> int:
    return sum(1 for marker in markers if _marker_matches(text, marker))


def _title(candidate) -> str:
    return str(candidate.get("title") or "")


def _lead(candidate, limit: int = 900) -> str:
    return str(candidate.get("source_text") or "")[:limit]


def _topics(text: str):
    return set(gate.infer_topics(text))


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


def _local_category(title_topics: set[str], title: str) -> str:
    if "quake" in title_topics:
        return "sakh_quake"
    if "incident" in title_topics or _contains_any(title, LOCAL_HARM_TITLE):
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


def _soft_content_offtopic(candidate, title_text, lead_text, title_topics, lead_topics) -> bool:
    combined = f"{title_text} {lead_text}"
    hard_topics = {"security", "incident", "politics", "quake", "weather", "it"}

    travel_hits = _hit_count(combined, TRAVEL_LIFESTYLE)
    promo_hits = _hit_count(combined, SEO_PROMO)
    service_hits = _hit_count(combined, SERVICE_CONTENT)

    if travel_hits >= 2 and promo_hits >= 1:
        return True
    if service_hits >= 1 and not (hard_topics & title_topics):
        return True

    institutional_economy = _contains_any(title_text, INSTITUTIONAL_ECONOMY)
    if "economy" in title_topics and institutional_economy:
        return False

    if _source_is_local_media(candidate) and "local" not in title_topics and travel_hits >= 2:
        return True
    return False


def _nonlocal_domestic_from_title(candidate, title_text, lead_text, title_topics):
    direct = _domestic_topic_from_title(title_topics)

    if direct == "ru_eco" or _contains_any(title_text, DOMESTIC_ECONOMY):
        if _contains_any(title_text, GLOBAL_ECONOMY) and not _contains_any(
            title_text + " " + lead_text, DOMESTIC_ECONOMY
        ):
            return "geo"
        if (
            _contains_any(title_text + " " + lead_text, DOMESTIC_ECONOMY)
            or "russia" in title_topics
            or (_source_is_russian_media(candidate) and _domestic_section(candidate))
            or _source_is_local_media(candidate)
        ):
            return "ru_eco"
        return None

    if direct == "ru_pol" or _contains_any(title_text, DOMESTIC_POLITICS):
        if "foreign" in title_topics and "russia" not in title_topics:
            return "geo"
        if (
            "russia" in title_topics
            or _contains_any(title_text + " " + lead_text, DOMESTIC_POLITICS)
            or _source_is_russian_media(candidate)
            or _source_is_local_media(candidate)
        ):
            return "ru_pol"
        return None

    if direct == "ru_security":
        if "foreign" in title_topics and "russia" not in title_topics:
            return "geo"
        return "ru_security"

    if direct == "ru_incident":
        if "foreign" in title_topics and "russia" not in title_topics:
            return "geo"
        return "ru_incident"

    return None


def suggest_category(candidate):
    """Return the semantically preferred category key, or None for off-topic."""
    current = str(candidate.get("category_key") or "")
    title_text = _title(candidate)
    lead_text = _lead(candidate)
    title_topics = _topics(title_text)
    lead_topics = _topics(lead_text)
    all_topics = title_topics | lead_topics

    if _soft_content_offtopic(candidate, title_text, lead_text, title_topics, lead_topics):
        return None

    if "it" in title_topics:
        return "it"
    if _source_is_tech_media(candidate) and "it" in lead_topics:
        return "it"

    # Geography in the headline is authoritative.
    if "local" in title_topics:
        return _local_category(title_topics, title_text)

    if "foreign" in title_topics:
        if _source_is_world_media(candidate) and "russia" in all_topics:
            return "world_ru"
        return "geo"

    domestic = _nonlocal_domestic_from_title(candidate, title_text, lead_text, title_topics)
    if domestic:
        return domestic

    # Local publishers frequently syndicate federal content. Their site name or
    # boilerplate in the article body is never enough to create a local story.
    if _source_is_local_media(candidate):
        if _contains_any(title_text, DOMESTIC_ECONOMY):
            return "ru_eco"
        if _contains_any(title_text, DOMESTIC_POLITICS):
            return "ru_pol"
        return None

    # For non-local publishers, a clear Sakhalin lead may recover a headline
    # which omitted the region, but only when the lead itself has a real event.
    if "local" in lead_topics:
        if "quake" in all_topics:
            return "sakh_quake"
        if "incident" in all_topics or _contains_any(title_text, LOCAL_HARM_TITLE):
            return "sakh_chp"
        return "sakh"

    if _international_section(candidate):
        if _source_is_world_media(candidate) and "russia" in all_topics:
            return "world_ru"
        if "foreign" in all_topics or "russia" in all_topics:
            return "geo"
        return None

    if _source_is_world_media(candidate):
        if "russia" in all_topics:
            return "world_ru"
        if "foreign" in all_topics:
            return "geo"

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
