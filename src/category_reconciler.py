"""Geography-first category reconciliation for SkySakhNews.

Publisher identity is never accepted as story geography. Local stories require
actual Sakhalin geography in the headline/article. This prevents syndicated
Habarovsk/travel/other-region content from a local-media domain entering the
Sakhalin stream.
"""

from urllib.parse import urlparse

import editorial_gate as gate

WORLD_MEDIA = ("bbc", "reuters", "guardian", "associated press", " ap ")
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online")
TECH_MEDIA = ("technology", "tech")

EXTRA_FOREIGN = (
    "армени", "пашинян", "казахстан", "белорус", "груз", "азербайдж", "молдов", "куб",
    "турц", "сири", "ирак", "афган", "инд", "пакистан", "серб", "венгр", "польш", "финлян",
    "норвег", "швец", "итал", "испан", "нидерланд", "бельг", "австри", "швейцар",
    "armenia", "kazakhstan", "belarus", "georgia", "azerbaijan", "moldova", "cuba", "turkey",
    "syria", "iraq", "india", "pakistan", "poland", "italy", "spain",
)

INTERNATIONAL_PATHS = (
    "/world/", "/international/", "/foreign/", "/mezhdunarodnaya-panorama/",
    "/mezhdunarodnaya-politika/",
)


def _low(value):
    return str(value or "").lower()


def _contains_any(text, markers):
    low = _low(text)
    return any(x in low for x in markers)


def _content_topics(candidate):
    blob = f"{candidate.get('title','')} {candidate.get('source_text','')}"
    topics = set(gate.infer_topics(blob))
    if _contains_any(blob, EXTRA_FOREIGN):
        topics.add("foreign")
    return topics


def _title_topics(candidate):
    title = str(candidate.get("title") or "")
    topics = set(gate.infer_topics(title))
    if _contains_any(title, EXTRA_FOREIGN):
        topics.add("foreign")
    return topics


def _source_is_world_media(candidate):
    source = " " + _low(candidate.get("source")) + " "
    return any(x in source for x in WORLD_MEDIA)


def _source_is_local_media(candidate):
    source = _low(candidate.get("source"))
    host = urlparse(str(candidate.get("url") or "")).netloc.lower()
    return any(x in source or x in host for x in LOCAL_MEDIA)


def _source_is_tech_media(candidate):
    source = _low(candidate.get("source"))
    return any(x in source for x in TECH_MEDIA)


def _international_section(candidate):
    path = urlparse(str(candidate.get("url") or "")).path.lower()
    return any(x in path for x in INTERNATIONAL_PATHS)


def suggest_category(candidate):
    """Return the semantically preferred category key, or None for off-topic."""
    current = str(candidate.get("category_key") or "")
    content = _content_topics(candidate)
    title = _title_topics(candidate)

    # Technology needs actual technology semantics; a generic source/page label is
    # not enough to turn another subject into IT.
    if "it" in title or ("it" in content and (current == "it" or _source_is_tech_media(candidate))):
        return "it"

    # A local-media publisher can syndicate material from other regions. Therefore
    # local provenance NEVER supplies locality. There must be an explicit Sakhalin
    # marker in title/article content.
    actual_local = "local" in content
    if actual_local:
        if "quake" in title or "quake" in content:
            return "sakh_quake"
        if "weather" in title and "incident" not in title:
            return "sakh"
        if "incident" in title or "incident" in content:
            return "sakh_chp"
        return "sakh"

    # A Sakhalin-focused source without any Sakhalin geography is syndicated/noise
    # for this channel. Do not silently reinterpret a Habarovsk bus-stop or travel
    # advert as Russian politics/economy.
    if _source_is_local_media(candidate):
        return None

    # Geography is evaluated before topic. Any clearly foreign-focused headline
    # from a Russian publisher is geopolitics; from independent world media, a
    # story specifically about Russia is World about Russia.
    if "foreign" in title:
        if _source_is_world_media(candidate) and "russia" in content:
            return "world_ru"
        return "geo"

    # Russian publisher's international desk is international by story section,
    # not a domestic Russia stream. This catches titles whose country name was not
    # in our marker dictionary.
    if _international_section(candidate):
        if _source_is_world_media(candidate) and "russia" in content:
            return "world_ru"
        return "geo" if "foreign" in content or "russia" in content else None

    if _source_is_world_media(candidate) and "russia" in content:
        return "world_ru"

    # Domestic event type only after geography has been settled.
    if "security" in title or "security" in content:
        return "ru_security"
    if "incident" in title or "incident" in content:
        return "ru_incident"
    if "economy" in title or "economy" in content:
        return "ru_eco"
    if "politics" in title or "politics" in content:
        return "ru_pol"

    if "foreign" in content:
        return "geo"

    # Existing world/IT categories can survive only when their semantics remain
    # supported; general/ambiguous material is safer to drop than mislabel.
    if current == "geo" and "foreign" in content:
        return "geo"
    if current == "world_ru" and "russia" in content:
        return "world_ru"
    if current == "it" and "it" in content:
        return "it"
    return None
