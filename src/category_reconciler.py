"""Geography-first category reconciliation for SkySakhNews.

The source publisher is never treated as the geography of the story. This module
recomputes the stream from the headline + article meaning before writing/publish.
"""

from urllib.parse import urlparse

import editorial_gate as gate

WORLD_MEDIA = ("bbc", "reuters", "guardian", "associated press", " ap ")
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online")
TECH_MEDIA = ("technology", "tech")

# More foreign geography names seen in the historical feed. They are content
# markers only; they never imply a category by publisher identity.
EXTRA_FOREIGN = (
    "армени", "пашинян", "казахстан", "белорус", "груз", "азербайдж", "молдов", "куб",
    "турц", "сири", "ирак", "афган", "инд", "пакистан", "серб", "венгр", "польш", "финлян",
    "норвег", "швец", "итал", "испан", "нидерланд", "бельг", "австри", "швейцар",
    "armenia", "kazakhstan", "belarus", "georgia", "azerbaijan", "moldova", "cuba", "turkey",
    "syria", "iraq", "india", "pakistan", "poland", "italy", "spain",
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


def suggest_category(candidate):
    """Return the semantically preferred category key, or None for off-topic."""
    current = str(candidate.get("category_key") or "")
    content = _content_topics(candidate)
    title = _title_topics(candidate)

    # Technology is a subject stream and wins only with actual technology signal.
    if "it" in title or ("it" in content and (current == "it" or _source_is_tech_media(candidate))):
        return "it"

    # Locality is based on content. A trusted local publisher may supply implicit
    # locality only when the headline is not clearly foreign-focused.
    actual_local = "local" in content or (
        _source_is_local_media(candidate)
        and "foreign" not in title
    )
    if actual_local:
        if "quake" in title or "quake" in content:
            return "sakh_quake"
        if "weather" in title and "incident" not in title:
            return "sakh"
        if "incident" in title or "incident" in content:
            return "sakh_chp"
        return "sakh"

    # The headline is the primary indicator of story geography. This catches the
    # historical errors Iran->Sakhalin, Canada tariffs->Russia/economy and foreign
    # political commentary->Russia/politics.
    if "foreign" in title and "russia" not in title:
        return "geo"

    # Foreign media explicitly discussing Russia belongs to World about Russia.
    if _source_is_world_media(candidate) and "russia" in content:
        return "world_ru"

    # Event type for domestic/non-foreign stories.
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
    if _source_is_world_media(candidate) and "russia" in title:
        return "world_ru"

    # Keep a safe already-established general local stream; otherwise off-topic.
    if current in {"sakh", "sakh_chp", "sakh_quake", "world_ru", "geo", "it"}:
        return current
    return None
