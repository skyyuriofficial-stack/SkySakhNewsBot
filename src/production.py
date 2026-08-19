"""SkySakhNews canonical production entrypoint.

One production entrypoint, one scheduled publisher. The stable v9 core handles
collection/grounding; this module applies runtime invariants and fail-safe policy.
"""

import os
import re
import urllib.parse

import news_bot_v9 as core

VERSION = "stable-v9.7"
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
# Source geography: publisher country != story geography
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


def classify_v97(src_type, weight, title, rss_text, desc, url):
    if src_type != "ru":
        return core.classify(src_type, weight, title, rss_text, desc, url)

    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if core.b.terms(text, core.b.NOISE):
        return None, 0, "noise"

    if core.b.terms(text, core.b.LOCAL):
        if core.b.terms(text, core.b.QUAKE):
            return "sakh_quake", weight + 24, "ru_local_quake"
        if core.b.terms(text, core.b.LOCAL_EVENT):
            return "sakh_chp", weight + 20, "ru_local_chp"
        return "sakh", weight + 12, "ru_local"

    if "/moscow/" in path:
        return None, 0, "moscow_noise"

    if is_international_url(url):
        if core.hits(text, core.RUSSIA_MARKERS):
            return "world_ru", weight + 18, "ru_source_world_about_russia"

        foreign_hits = set(core.hits(text, core.GEO_MARKERS + FOREIGN_CONTEXT_MARKERS))
        if len(foreign_hits) >= 2:
            return "geo", weight + 8, "ru_source_foreign_geo"
        return None, 0, "ru_source_foreign_weak"

    if core.hits(text, core.SECURITY_MARKERS):
        return "ru_security", weight + 18, "ru_security"
    if core.b.terms(text, core.b.ECO):
        return "ru_eco", weight + 12, "ru_eco"
    if core.b.terms(text, core.b.POL) or core.hits(text, core.RUSSIA_MARKERS):
        return "ru_pol", weight + 10, "ru_pol"
    if len(set(core.hits(text, core.GEO_MARKERS))) >= 2:
        return "geo", weight + 6, "ru_geo"
    return None, 0, "ru_not_in_stream"


# b.collect calls b.classify dynamically.
core.b.classify = classify_v97

_original_source_stream_guard = core.valid_source_stream


def valid_source_stream_v97(item):
    cat = item.get("category_key", "")
    url = item.get("url") or ""
    body = f"{item.get('title','')} {item.get('source_text','')}".lower()

    if cat in ("ru_security", "ru_eco", "ru_pol") and is_international_url(url):
        if not core.hits(body, core.RUSSIA_MARKERS):
            return False, "russia_stream_foreign_story"

    return _original_source_stream_guard(item)


# core.collect resolves this global at runtime.
core.valid_source_stream = valid_source_stream_v97


# ---------------------------------------------------------------------------
# Editorial reliability
# ---------------------------------------------------------------------------
# v9.6 proved the danger of applying a second AI fact-check to every candidate:
# one degraded/free-provider cycle can reject every story and create a retry storm.
# v9.7 uses ONE structured AI generation with deterministic evidence validation,
# caps AI calls per run, and has an extractive Russian-language fail-safe.
AI_CALL_BUDGET = max(0, int(os.getenv("AI_CALL_BUDGET", "8")))
_AI_CALLS = 0
_AI_CIRCUIT_OPEN = False

for _key in (
    "ai_calls",
    "ai_budget_exhausted",
    "ai_api_fail",
    "evidence_reject",
    "validation_reject",
    "extractive_fallback",
):
    core.b.STATS.setdefault(_key, 0)


def _looks_russian(text):
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", text or ""))
    return cyr / len(letters) >= 0.82


def _sentence_candidates(text):
    clean = core.b.clean(text)
    parts = re.split(r"(?<=[.!?])\s+|\s+[—–-]\s+(?=[А-ЯA-Z])", clean)
    out = []
    for raw in parts:
        s = core.b.clean(raw).strip(" -—–")
        if len(s) < 65 or len(s) > 520:
            continue
        if not _looks_russian(s):
            continue
        if any(core.b.too_similar(s, old) for old in out):
            continue
        out.append(s)
    return out


def _extractive_fallback(c):
    """Fail-safe for Russian source text. No paraphrase means no hallucination."""
    source = core.b.clean(c.get("source_text"))
    title = core.b.clean(c.get("title"))
    if not _looks_russian(title + " " + source):
        return None

    sentences = _sentence_candidates(source)
    if len(sentences) < 2:
        return None

    body = sentences[:2]
    row = {
        "reject": False,
        "title_ru": title[:220],
        "body": body,
        "footer": c.get("footer"),
        "editorial_mode": "extractive_fallback",
    }

    # Deterministic safety checks. The fallback is copied from source, so there
    # is no separate evidence field to validate.
    joined = row["title_ru"] + " " + " ".join(body)
    source_all = title + " " + source
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

    quake_errors = core.validate_quake(row, c)
    if quake_errors:
        return None
    return row


def _validate_generated_v97(row, c):
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
    if core.b.ratio_latin(joined) > 0.10:
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
    ))


def valid_post_v97(c):
    global _AI_CALLS, _AI_CIRCUIT_OPEN

    last_error = ""
    attempts = 0

    while attempts < 2 and not _AI_CIRCUIT_OPEN and _AI_CALLS < AI_CALL_BUDGET:
        attempts += 1
        _AI_CALLS += 1
        core.b.STATS["ai_calls"] = _AI_CALLS
        try:
            row = core.generate_grounded(c, last_error)
            errors = _validate_generated_v97(row, c)
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
            if _api_failure_is_systemic(ex):
                _AI_CIRCUIT_OPEN = True
                core.b.log("AI circuit opened for this run; switching to safe extractive fallback")
                break

    if _AI_CALLS >= AI_CALL_BUDGET:
        core.b.STATS["ai_budget_exhausted"] = 1

    fallback = _extractive_fallback(c)
    if fallback:
        core.b.STATS["extractive_fallback"] += 1
        core.b.log(f"extractive fallback accepted: {c['title'][:80]}")
        return fallback

    core.b.STATS["editorial_skip"] += 1
    return None


core.b.valid_post = valid_post_v97


def main():
    core.b.main()


if __name__ == "__main__":
    main()
