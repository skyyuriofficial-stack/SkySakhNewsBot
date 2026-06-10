# v9: strict stream classification overlay over v8.
# Goal: prevent non-Russia world stories from being labelled as "Мир о России".
# Example fixed: USA/Iran/Apache story must be "Геополитика", not "Мир о России".

import re
import urllib.parse
import news_bot_v8 as b

RUSSIA_MARKERS = [
    "russia", "russian", "moscow", "kremlin", "putin", "lavrov",
    "россия", "россии", "россию", "россией", "рф", "российск", "москва", "кремль", "путин", "лавров",
]

GEO_MARKERS = [
    "iran", "иран", "israel", "израиль", "usa", "u.s.", "us ", "сша", "america", "американ",
    "trump", "трамп", "nato", "нато", "china", "китай", "taiwan", "тайвань", "g7", "g20",
    "war", "война", "conflict", "конфликт", "strike", "attack", "удар", "удары", "missile", "ракета",
    "drone", "дрон", "military", "военн", "base", "база", "air defense", "пво",
    "sanctions", "санкц", "oil", "нефть", "gas", "газ", "middle east", "ближн", "йемен", "yemen",
]


def has_marker(text, markers):
    raw = " " + (text or "").lower() + " "
    for marker in markers:
        m = marker.lower().strip()
        if not m:
            continue
        if re.fullmatch(r"[a-z0-9.]+", m):
            if re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", raw):
                return True
        elif m in raw:
            return True
    return False


def count_markers(text, markers):
    raw = " " + (text or "").lower() + " "
    count = 0
    for marker in markers:
        m = marker.lower().strip()
        if not m:
            continue
        if re.fullmatch(r"[a-z0-9.]+", m):
            if re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", raw):
                count += 1
        elif m in raw:
            count += 1
    return count


_old_classify = b.classify


def classify(src_type, weight, title, rss_text, desc, url):
    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if b.terms(text, b.NOISE):
        return None, 0, "noise"

    # Сахалин: отдельно сейсмика/ЧП, чтобы подпись соответствовала содержанию.
    is_local = src_type == "sakhalin" or bool(b.terms(text, b.LOCAL))
    if is_local:
        if b.terms(text, b.QUAKE):
            return "sakh_quake", weight + 36, "local_quake"
        if b.terms(text, b.LOCAL_EVENT):
            return "sakh_chp", weight + 32, "local_chp"
        if len(b.clean(rss_text + " " + desc)) >= 180:
            return "sakh", weight + 18, "local_general"
        return None, 0, "local_low_signal"

    # Мир о России: только если есть явный российский маркер.
    # Trump/China/Iran/USA alone are not Russia-related.
    if src_type == "world":
        if has_marker(text, RUSSIA_MARKERS):
            return "world_ru", weight + 20, "world_about_russia_strict"
        if count_markers(text, GEO_MARKERS) >= 2:
            return "geo", weight + 10, "geo_strict"
        return None, 0, "world_not_in_stream"

    if src_type == "it":
        return ("it", weight + 10, "it") if b.terms(text, b.IT) else (None, 0, "it_not_relevant")

    if src_type == "ru":
        if "/moscow/" in path:
            return None, 0, "moscow_noise"
        if b.terms(text, b.QUAKE) and b.terms(text, b.LOCAL):
            return "sakh_quake", weight + 24, "ru_local_quake"
        if b.terms(text, b.ECO):
            return "ru_eco", weight + 12, "ru_eco"
        if b.terms(text, b.POL) or has_marker(text, RUSSIA_MARKERS):
            return "ru_pol", weight + 10, "ru_pol"
        if count_markers(text, GEO_MARKERS) >= 2:
            return "geo", weight + 6, "ru_geo"
        return None, 0, "ru_not_in_stream"

    return _old_classify(src_type, weight, title, rss_text, desc, url)


b.classify = classify

# Extra guard: if a candidate somehow remains world_ru without Russian marker, reject it before publication.
_old_collect = b.collect


def collect(state):
    items = _old_collect(state)
    filtered = []
    for item in items:
        if item.get("category_key") == "world_ru":
            body = f"{item.get('title', '')} {item.get('source_text', '')}".lower()
            if not has_marker(body, RUSSIA_MARKERS):
                b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
                b.log("skip stream mismatch: " + item.get("title", "")[:90])
                continue
        filtered.append(item)
    return filtered


b.collect = collect

if __name__ == "__main__":
    b.main()
