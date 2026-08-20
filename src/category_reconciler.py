"""Geography-first category reconciliation for SkySakhNews."""

from urllib.parse import urlparse
import editorial_gate as gate

WORLD_MEDIA = ("bbc", "reuters", "guardian", "associated press", " ap ")
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online")
TECH_MEDIA = ("technology", "tech")
EXTRA_FOREIGN = (
    "армени", "пашинян", "казахстан", "белорус", "груз", "азербайдж", "молдов", "куб",
    "турц", "сири", "ирак", "афган", "инд", "пакистан", "серб", "венгр", "польш", "финлян",
    "норвег", "швец", "итал", "испан", "нидерланд", "бельг", "австри", "швейцар",
    "ближн вост", "оаэ", "сауд", "катар", "армения", "казахстан",
    "armenia", "kazakhstan", "belarus", "georgia", "azerbaijan", "moldova", "cuba", "turkey",
    "syria", "iraq", "india", "pakistan", "poland", "italy", "spain", "middle east",
)
GLOBAL_ECON = (
    "brent", "wti", "opec", "опек", "ice futures", "фьючерс", "евц", "ецб", "фрс",
    "wall street", "nasdaq", "s&p", "dow jones", "нефть дорожает", "нефть дешевеет",
)
DOMESTIC_ECON = (
    "россельхозбанк", "сбер", "втб", "газпром", "роснефт", "мосбирж", "imoex", "минфин",
    "центробанк", "цб рф", "рубл", "российск", "рф ", "кабмин", "новороссийск",
)
INTERNATIONAL_PATHS = (
    "/world/", "/international/", "/foreign/", "/mezhdunarodnaya-panorama/",
    "/mezhdunarodnaya-politika/",
)


def _low(v): return str(v or "").lower()
def _contains_any(text, markers):
    low = _low(text); return any(x in low for x in markers)
def _content(c): return f"{c.get('title','')} {c.get('source_text','')}"
def _title(c): return str(c.get("title") or "")
def _topics(text):
    out = set(gate.infer_topics(text))
    if _contains_any(text, EXTRA_FOREIGN): out.add("foreign")
    return out
def _content_topics(c): return _topics(_content(c))
def _title_topics(c): return _topics(_title(c))
def _source_is_world_media(c): return any(x in (" " + _low(c.get("source")) + " ") for x in WORLD_MEDIA)
def _source_is_local_media(c):
    source = _low(c.get("source")); host = urlparse(str(c.get("url") or "")).netloc.lower()
    return any(x in source or x in host for x in LOCAL_MEDIA)
def _source_is_tech_media(c): return any(x in _low(c.get("source")) for x in TECH_MEDIA)
def _international_section(c):
    path = urlparse(str(c.get("url") or "")).path.lower()
    return any(x in path for x in INTERNATIONAL_PATHS)


def _local_category(title, content):
    if "quake" in title or "quake" in content: return "sakh_quake"
    if "weather" in title and "incident" not in title: return "sakh"
    if "incident" in title or "incident" in content: return "sakh_chp"
    return "sakh"


def suggest_category(candidate):
    """Return preferred stream, or None when the story has no safe stream."""
    current = str(candidate.get("category_key") or "")
    title_text = _title(candidate)
    content, title = _content_topics(candidate), _title_topics(candidate)

    if "it" in title or ("it" in content and (current == "it" or _source_is_tech_media(candidate))):
        return "it"

    # Central headline geography has priority. A Japan/Russia story that merely
    # mentions Kurils/Sakhalin in the body is not automatically local news.
    if "local" in title:
        return _local_category(title, content)
    if "foreign" in title:
        if _source_is_world_media(candidate) and "russia" in content: return "world_ru"
        return "geo"

    # Without foreign focus in the headline, an explicit Sakhalin marker in the
    # article body is enough for a local story. Publisher identity alone is never enough.
    if "local" in content:
        return _local_category(title, content)
    if _source_is_local_media(candidate):
        return None

    if _international_section(candidate):
        if _source_is_world_media(candidate) and "russia" in content: return "world_ru"
        return "geo" if ("foreign" in content or "russia" in content) else None
    if _source_is_world_media(candidate) and "russia" in content:
        return "world_ru"

    if "security" in title or "security" in content: return "ru_security"
    if "incident" in title or "incident" in content: return "ru_incident"

    # A Russian business publisher/article is not automatically Russia/economy.
    if "economy" in title or "economy" in content:
        if _contains_any(title_text, GLOBAL_ECON) or ("foreign" in content and not _contains_any(title_text, DOMESTIC_ECON)):
            return "geo"
        if "russia" in title or _contains_any(title_text, DOMESTIC_ECON):
            return "ru_eco"
        if current == "ru_eco":
            return None
        return "ru_eco"

    if "politics" in title or "politics" in content: return "ru_pol"
    if "foreign" in content: return "geo"
    if current == "geo" and "foreign" in content: return "geo"
    if current == "world_ru" and "russia" in content: return "world_ru"
    if current == "it" and "it" in content: return "it"
    return None
