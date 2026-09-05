"""SkySakhNews canonical production entrypoint.

One production entrypoint, one scheduled publisher. The stable v9 core handles
collection/grounding; this module applies runtime invariants and fail-safe policy.
"""

import os
import re
import urllib.parse
from datetime import datetime, timezone

import news_bot_v9 as core

VERSION = "stable-v9.9"
core.VERSION = VERSION

# ---------------------------------------------------------------------------
# Run-local page cache
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
# Classification policy
# ---------------------------------------------------------------------------
core.b.CAT["ru_incident"] = ("🇷🇺 Россия / происшествия", "РОССИЯ | ПРОИСШЕСТВИЯ")

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

WEATHER_MARKERS = [
    "погода", "дожд", "ливень", "осадк", "снег", "метел", "циклон", "шторм",
    "ветер", "туман", "мороз", "жара", "температур", "гидромет", "росгидромет",
]

INCIDENT_MARKERS = [
    "дтп", "авари", "пожар", "погиб", "погибли", "смерт", "пострадал", "пострадали",
    "утонул", "утонула", "катер", "лодк", "крушен", "обрушен", "травм", "происшеств",
    "убийств", "ранен", "ранены", "пропал", "пропала", "розыск", "спасател", "мчс",
    "следствен", "следовател", "полици", "прокуратур", "уголовн", "судно",
]


def is_international_url(url):
    path = urllib.parse.urlparse(url or "").path.lower()
    return any(marker in path for marker in INTERNATIONAL_PATH_MARKERS)


def classify_v99(src_type, weight, title, rss_text, desc, url):
    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if core.b.terms(text, core.b.NOISE):
        return None, 0, "noise"

    if src_type in {"it", "world"}:
        return core.classify(src_type, weight, title, rss_text, desc, url)

    # Local weather is ordinary regional news unless an actual incident is present.
    if src_type == "sakhalin":
        if core.hits(text, WEATHER_MARKERS):
            return "sakh", weight + 22, "local_weather"
        if core.b.terms(text, core.b.QUAKE):
            return "sakh_quake", weight + 36, "local_quake"
        if core.b.terms(text, core.b.LOCAL_EVENT):
            return "sakh_chp", weight + 32, "local_chp"
        if core.b.terms(text, core.b.LOCAL) or len(core.b.clean(rss_text + " " + desc)) >= 140:
            return "sakh", weight + 18, "local_general"
        return None, 0, "local_low_signal"

    if src_type != "ru":
        return None, 0, "unknown_source_type"

    if core.b.terms(text, core.b.LOCAL):
        if core.hits(text, WEATHER_MARKERS):
            return "sakh", weight + 18, "ru_local_weather"
        if core.b.terms(text, core.b.QUAKE):
            return "sakh_quake", weight + 24, "ru_local_quake"
        if core.b.terms(text, core.b.LOCAL_EVENT):
            return "sakh_chp", weight + 20, "ru_local_chp"
        return "sakh", weight + 12, "ru_local"

    if "/moscow/" in path:
        return None, 0, "moscow_noise"

    # Russian publisher's international desk is classified by story geography.
    if is_international_url(url):
        if core.hits(text, core.RUSSIA_MARKERS):
            return "world_ru", weight + 18, "ru_source_world_about_russia"
        foreign_hits = set(core.hits(text, core.GEO_MARKERS + FOREIGN_CONTEXT_MARKERS))
        if len(foreign_hits) >= 2:
            return "geo", weight + 8, "ru_source_foreign_geo"
        return None, 0, "ru_source_foreign_weak"

    # Domestic event type is determined before politics/economy.
    if core.hits(text, core.SECURITY_MARKERS):
        return "ru_security", weight + 18, "ru_security"
    if core.hits(text, INCIDENT_MARKERS):
        return "ru_incident", weight + 15, "ru_incident"
    if core.b.terms(text, core.b.ECO):
        return "ru_eco", weight + 12, "ru_eco"
    if core.b.terms(text, core.b.POL):
        return "ru_pol", weight + 10, "ru_pol"
    if len(set(core.hits(text, core.GEO_MARKERS))) >= 2:
        return "geo", weight + 6, "ru_geo"
    return None, 0, "ru_not_in_stream"


core.b.classify = classify_v99

_original_source_stream_guard = core.valid_source_stream


def valid_source_stream_v99(item):
    cat = item.get("category_key", "")
    url = item.get("url") or ""
    body = f"{item.get('title','')} {item.get('source_text','')}".lower()

    if cat in {"ru_security", "ru_incident", "ru_eco", "ru_pol"} and is_international_url(url):
        if not core.hits(body, core.RUSSIA_MARKERS):
            return False, "russia_stream_foreign_story"

    if cat == "ru_incident" and not core.hits(body, INCIDENT_MARKERS):
        return False, "incident_without_incident_marker"
    if cat == "ru_pol" and not core.b.terms(body, core.b.POL):
        return False, "politics_without_politics_marker"
    if cat == "ru_eco" and not core.b.terms(body, core.b.ECO):
        return False, "economy_without_economy_marker"
    if cat == "ru_security" and not core.hits(body, core.SECURITY_MARKERS):
        return False, "security_without_security_marker"

    return _original_source_stream_guard(item)


core.valid_source_stream = valid_source_stream_v99


def ordered_v99(cands):
    local_keys = {"sakh_quake", "sakh_chp", "sakh"}
    local = [c for c in cands if c.get("category_key") in local_keys]
    other = [c for c in cands if c not in local]
    out = []
    if local:
        out.append(local[0])
    for key in ("world_ru", "ru_security", "ru_incident", "ru_pol", "ru_eco", "geo", "it"):
        out.extend(c for c in other if c.get("category_key") == key and c not in out)
    out.extend(c for c in local[1:] if c not in out)
    out.extend(c for c in other if c not in out)
    return out


core.b.ordered = ordered_v99


# ---------------------------------------------------------------------------
# Editorial reliability
# ---------------------------------------------------------------------------
AI_CALL_BUDGET = max(0, int(os.getenv("AI_CALL_BUDGET", "4")))
_AI_CALLS = 0
_AI_CIRCUIT_OPEN = False

for _key in (
    "ai_calls", "ai_budget_exhausted", "ai_api_fail", "evidence_reject",
    "validation_reject", "extractive_fallback", "extractive_first",
):
    core.b.STATS.setdefault(_key, 0)

PROMO_TEXT = (
    "подпишись", "подписывайтесь", "читайте также", "читайте нас", "реклама",
    "самые важные новости", "в нашем telegram", "в нашем телеграм", "в max!",
)

ABBREVIATIONS = (
    "тыс.", "млн.", "млрд.", "руб.", "коп.", "г.", "ул.", "д.", "стр.",
    "ст.", "им.", "км.", "см.", "мм.", "ч.", "мин.", "сек.", "т.д.", "т.п.",
)


def _looks_russian(text):
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", text or ""))
    return cyr / len(letters) >= 0.82


def _protect_abbreviations(text):
    out = text
    for abbr in ABBREVIATIONS:
        out = re.sub(
            re.escape(abbr),
            lambda m: m.group(0).replace(".", "∯"),
            out,
            flags=re.I,
        )
    return out


def _dedupe_adjacent_words(sentence):
    """Collapse accidental desc/RSS/article concatenation: X X -> X."""
    words = sentence.split()
    norms = [core.b.norm(w) for w in words]
    n = len(words)
    for width in range(max(6, n // 4), n // 2 + 1):
        if 2 * width > n:
            break
        left = norms[:width]
        right = norms[width:2 * width]
        if left and left == right and all(left):
            trimmed = " ".join(words[:width]).rstrip(" ,;:-")
            if sentence.rstrip().endswith((".", "!", "?")) and not trimmed.endswith((".", "!", "?")):
                trimmed += sentence.rstrip()[-1]
            return trimmed
    return sentence


def _sentence_candidates(text):
    clean = core.b.clean(text)
    protected = _protect_abbreviations(clean)
    parts = re.split(
        r"(?<=[!?])\s+(?=[«\"“„(]?[А-ЯЁA-Z0-9])|(?<=\.)\s+(?=[«\"“„(]?[А-ЯЁA-Z0-9])",
        protected,
    )
    out = []
    for raw in parts:
        s = core.b.clean(raw.replace("∯", ".")).strip(" -—–")
        s = _dedupe_adjacent_words(s)
        if len(s) < 65 or len(s) > 520 or not _looks_russian(s):
            continue
        if not re.match(r'^[«\"“„(]*[А-ЯЁA-Z0-9]', s):
            continue
        low = s.lower()
        if any(x in low for x in PROMO_TEXT):
            continue
        if any(core.b.too_similar(s, old) for old in out):
            continue
        out.append(s)
    return out


def _display_title(c):
    title = core.b.clean(c.get("title"))
    title = re.sub(
        r"\s*(?:[-–—|]\s*)?(?:SakhalinMedia(?:\.ru)?|ASTV(?:\.ru)?|Sakh\.online|Interfax|Интерфакс|TASS|ТАСС)\s*$",
        "",
        title,
        flags=re.I,
    ).strip(" -–—|")
    return title or core.b.clean(c.get("title"))


def _extractive_fallback(c):
    """Russian fail-safe: copy source sentences, never invent or paraphrase."""
    source = core.b.clean(c.get("source_text"))
    title = _display_title(c)
    if not _looks_russian(title + " " + source):
        return None

    candidates = _sentence_candidates(source)
    body = []
    for sentence in candidates:
        if core.b.too_similar(sentence, title):
            continue
        if any(core.b.too_similar(sentence, old) for old in body):
            continue
        body.append(sentence)
        if len(body) == 2:
            break
    if len(body) < 2:
        return None

    row = {
        "reject": False,
        "title_ru": title[:220],
        "body": body,
        "footer": c.get("footer"),
        "editorial_mode": "extractive_fallback",
    }
    joined = row["title_ru"] + " " + " ".join(body)
    source_all = core.b.clean(c.get("title")) + " " + source
    if len(row["title_ru"]) < 24 or len(row["title_ru"].split()) < 4:
        return None
    if len(joined) < 180 or len(joined) > 1650:
        return None
    if core.b.ratio_latin(joined) > 0.10:
        return None
    if core.b.nums(joined) - core.b.nums(source_all):
        return None
    if any(p in joined.lower() for p in core.b.BAD_TEXT):
        return None
    if core.validate_quake(row, c):
        return None
    # Every fallback paragraph must remain traceable to the source text.
    source_norm = core.b.norm(source)
    if any(core.b.norm(x) not in source_norm for x in body):
        return None
    return row


def _validate_generated_v99(row, c):
    if row.get("reject") is True:
        return ["model_rejected"]

    title = core.b.clean(row.get("title_ru"))
    body = row.get("body") if isinstance(row.get("body"), list) else []
    body = [core.b.clean(x) for x in body if core.b.clean(x)]
    joined = title + " " + " ".join(body)
    source = c.get("title", "") + " " + c.get("source_text", "")
    errors = []

    if len(title) < 24 or len(title.split()) < 4:
        errors.append("title_too_short")
    if len(body) < 2:
        errors.append("body_too_short")
    if len(joined) < 180:
        errors.append("post_too_short")
    if len(joined) > 1650:
        errors.append("post_too_long")
    # IT headlines legitimately retain brand/product names such as Nvidia,
    # Hugging Face, OpenAI and ChatGPT. The prose must still be predominantly
    # Russian, but those proper names are not translation failures.
    latin_limit = 0.28 if c.get("category_key") == "it" else 0.10
    if core.b.ratio_latin(joined) > latin_limit:
        errors.append("latin_ratio_high")
    if any(len(x) < 55 for x in body):
        errors.append("paragraph_too_short")
    if any(len(x) > 560 for x in body):
        errors.append("paragraph_too_long")
    low = joined.lower()
    for phrase in core.b.BAD_TEXT:
        if phrase in low:
            errors.append("bad_phrase:" + phrase)
    invented = core.b.nums(joined) - core.b.nums(source)
    if invented:
        errors.append("invented_numbers:" + ",".join(sorted(invented)))
    if re.search(
        r"\b(the|who|has|said|will|after|before|with|from|this|that|over|under|against|faces|keeps|what|why|how)\b",
        joined,
        re.I,
    ):
        errors.append("english_words_left")
    evidence_errors = core.validate_evidence(row, c)
    if evidence_errors:
        core.b.STATS["evidence_reject"] += 1
        errors.extend(evidence_errors)
    errors.extend(core.validate_quake(row, c))
    return errors


def _api_failure_is_systemic(ex):
    s = str(ex).lower()
    return any(x in s for x in (
        "429", "rate limit", "rate-limit", "quota", "too many requests",
        "temporarily unavailable", "timeout", "timed out", "502", "503", "504",
        "openrouter failed", "circuit is open",
    ))


def valid_post_v99(c):
    global _AI_CALLS, _AI_CIRCUIT_OPEN
    last_error = ""
    attempts = 0

    # Russian-language articles do not need an LLM rewrite. Publishing two
    # exact, validated source sentences is both safer and substantially more
    # reliable than spending free-model quota on stylistic paraphrasing.
    fallback = _extractive_fallback(c)
    if fallback:
        core.b.STATS["extractive_fallback"] += 1
        core.b.STATS["extractive_first"] += 1
        core.b.log(f"extractive-first accepted: {c['title'][:80]}")
        return fallback

    while attempts < 2 and _AI_CALLS < AI_CALL_BUDGET:
        attempts += 1
        _AI_CALLS += 1
        core.b.STATS["ai_calls"] = _AI_CALLS
        try:
            row = core.generate_grounded(c, last_error)
            errors = _validate_generated_v99(row, c)
            if not errors:
                return row
            core.b.STATS["validation_reject"] += 1
            last_error = "; ".join(errors)[:500]
            core.b.STATS["rewrite_retry"] += 1
            core.b.log(f"rewrite required: {c['title'][:70]} | {last_error}")
        except Exception as ex:
            core.b.STATS["ai_api_fail"] += 1
            core.b.STATS["rewrite_retry"] += 1
            last_error = str(ex)[:500]
            core.b.log(f"AI generation failed: {c['title'][:70]} | {last_error}")
            # Transient provider failures are isolated to this attempt.
            # The global release must continue to the next model/candidate.
            if any(code in str(ex).lower() for code in ("401", "403", "invalid api key")):
                _AI_CIRCUIT_OPEN = True
                core.b.log("AI authentication failure; disabling further AI calls for this run")
                break

    if _AI_CALLS >= AI_CALL_BUDGET:
        core.b.STATS["ai_budget_exhausted"] = 1

    core.b.STATS["editorial_skip"] += 1
    return None


core.b.valid_post = valid_post_v99


# ---------------------------------------------------------------------------
# Duplicate-run protection
# ---------------------------------------------------------------------------
RUN_COOLDOWN_MINUTES = max(0, int(os.getenv("RUN_COOLDOWN_MINUTES", "20")))


def _recent_publish_in_cooldown():
    if os.getenv("FORCE_RUN", "0") == "1" or RUN_COOLDOWN_MINUTES <= 0:
        return False
    try:
        state = core.b.load_state()
        run = state.get("last_run") or {}
        if run.get("status") != "ok" or int(run.get("published") or 0) <= 0:
            return False
        raw = run.get("finished_sakhalin")
        if not raw:
            return False
        finished = datetime.fromisoformat(raw)
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=core.b.TZ)
        age = datetime.now(timezone.utc) - finished.astimezone(timezone.utc)
        return 0 <= age.total_seconds() < RUN_COOLDOWN_MINUTES * 60
    except Exception:
        return False


def main():
    if _recent_publish_in_cooldown():
        core.b.log(f"skip duplicate run: successful publication within {RUN_COOLDOWN_MINUTES} minutes")
        return
    core.b.main()


if __name__ == "__main__":
    main()
