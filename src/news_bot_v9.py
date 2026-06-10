# v9: strict stream classification overlay over v8.
# Fixes:
# - Non-Russia world stories cannot be labelled as "Мир о России".
# - Russia drone / airspace / airport stories are "Россия / безопасность", not generic politics.
# - Same image cannot be used twice in one run or across recent saved posts.
# - Same security topic cluster cannot fill the whole release.

import re
import time
import hashlib
import urllib.parse
import news_bot_v8 as b

b.CAT["ru_security"] = ("🇷🇺 Россия / безопасность", "РОССИЯ | БЕЗОПАСНОСТЬ")

RUSSIA_MARKERS = [
    "russia", "russian", "moscow", "kremlin", "putin", "lavrov",
    "россия", "россии", "россию", "россией", "рф", "российск", "москва", "кремль", "путин", "лавров",
]

GEO_MARKERS = [
    "iran", "иран", "israel", "израиль", "usa", "u.s.", "сша", "america", "американ",
    "trump", "трамп", "nato", "нато", "china", "китай", "taiwan", "тайвань", "g7", "g20",
    "war", "война", "conflict", "конфликт", "strike", "attack", "удар", "удары", "missile", "ракета",
    "drone", "дрон", "military", "военн", "base", "база", "air defense", "пво",
    "sanctions", "санкц", "oil", "нефть", "gas", "газ", "middle east", "ближн", "йемен", "yemen",
]

SECURITY_MARKERS = [
    "беспилот", "бпла", "дрон", "дроны", "пво", "минобороны", "атака", "атаковали", "угроза", "опасность",
    "воздушная опасность", "режим опасности", "омич", "аэропорт", "аэропорты", "росавиация", "воздушное судно",
    "ограничения", "план ковер", "всу", "обломки", "ракета", "ракет", "перехват", "сбили", "сбит",
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

    is_local = src_type == "sakhalin" or bool(b.terms(text, b.LOCAL))
    if is_local:
        if b.terms(text, b.QUAKE):
            return "sakh_quake", weight + 36, "local_quake"
        if b.terms(text, b.LOCAL_EVENT):
            return "sakh_chp", weight + 32, "local_chp"
        if len(b.clean(rss_text + " " + desc)) >= 180:
            return "sakh", weight + 18, "local_general"
        return None, 0, "local_low_signal"

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
        if has_marker(text, SECURITY_MARKERS):
            return "ru_security", weight + 18, "ru_security"
        if b.terms(text, b.ECO):
            return "ru_eco", weight + 12, "ru_eco"
        if b.terms(text, b.POL) or has_marker(text, RUSSIA_MARKERS):
            return "ru_pol", weight + 10, "ru_pol"
        if count_markers(text, GEO_MARKERS) >= 2:
            return "geo", weight + 6, "ru_geo"
        return None, 0, "ru_not_in_stream"

    return _old_classify(src_type, weight, title, rss_text, desc, url)


b.classify = classify

_old_collect = b.collect


def image_hash(item):
    data = item.get("image")
    if isinstance(data, (bytes, bytearray)) and data:
        return hashlib.sha1(bytes(data)).hexdigest()
    url = item.get("image_url") or ""
    return hashlib.sha1(url.encode("utf-8")).hexdigest() if url else ""


def topic_cluster(item):
    text = f"{item.get('title','')} {item.get('source_text','')}".lower()
    cat = item.get("category_key", "")
    if cat == "ru_security":
        if any(x in text for x in ("аэропорт", "росавиац", "воздушн", "беспилот", "бпла", "дрон", "пво", "опасност")):
            return "ru_security_airspace_drone"
        return "ru_security_general"
    if cat == "sakh_quake":
        return "sakh_quake"
    words = [w for w in b.norm(item.get("title", "")).split() if len(w) >= 5][:4]
    return cat + ":" + "_".join(words)


def collect(state):
    items = _old_collect(state)
    recent_hashes = {p.get("image_hash") for p in state.get("last_posts", [])[-60:] if p.get("image_hash")}
    recent_urls = {p.get("image_url") for p in state.get("last_posts", [])[-60:] if p.get("image_url")}
    seen_hashes, seen_urls, seen_clusters = set(), set(), set()
    filtered = []

    for item in items:
        body = f"{item.get('title', '')} {item.get('source_text', '')}".lower()

        if item.get("category_key") == "world_ru" and not has_marker(body, RUSSIA_MARKERS):
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log("skip stream mismatch: " + item.get("title", "")[:90])
            continue

        ih = image_hash(item)
        iu = item.get("image_url") or ""
        if ih and (ih in seen_hashes or ih in recent_hashes):
            b.STATS["bad_image_skip"] = b.STATS.get("bad_image_skip", 0) + 1
            b.log("skip duplicate image: " + item.get("title", "")[:90])
            continue
        if iu and (iu in seen_urls or iu in recent_urls):
            b.STATS["bad_image_skip"] = b.STATS.get("bad_image_skip", 0) + 1
            b.log("skip duplicate image url: " + item.get("title", "")[:90])
            continue

        cluster = topic_cluster(item)
        if cluster in seen_clusters and item.get("category_key") in ("ru_security", "ru_pol", "ru_eco", "geo"):
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log("skip duplicate topic cluster: " + item.get("title", "")[:90])
            continue

        item["image_hash"] = ih
        seen_hashes.add(ih)
        if iu:
            seen_urls.add(iu)
        seen_clusters.add(cluster)
        filtered.append(item)

    return filtered


b.collect = collect


def ordered(cands):
    local = [c for c in cands if c["category_key"] in ("sakh_quake", "sakh_chp", "sakh")]
    priority = []
    for key in ("world_ru", "ru_security", "ru_pol", "ru_eco", "geo", "it"):
        priority += [c for c in cands if c["category_key"] == key]
    out = []
    if local:
        out.append(local[0])
    for c in priority:
        if len(out) >= b.POSTS_PER_RUN:
            break
        if c not in out:
            out.append(c)
    for c in local[1:] + priority + cands:
        if c not in out:
            out.append(c)
    return out


b.ordered = ordered


def main():
    state = b.load_state()
    b.log("Сбор кандидатов")
    cands = b.collect(state)
    b.log(f"Кандидатов после строгого фильтра: {len(cands)}")
    published = 0
    for c in b.ordered(cands):
        if published >= b.POSTS_PER_RUN:
            break
        if c["url"] in state.get("published_urls", []):
            continue
        row = b.valid_post(c)
        if not row:
            b.log(f"candidate skipped by editor: {c['title'][:90]}")
            continue
        try:
            cap = b.caption(row, c)
            b.log(f"publish photo-card: {c['category']} | {c['source']} | {c['title'][:90]}")
            result = b.send_photo(c, cap)
        except Exception as ex:
            b.STATS["telegram_fail"] += 1
            b.log(f"telegram failed: {c['title'][:90]} | {ex}")
            continue
        if result.get("ok"):
            state.setdefault("published_urls", []).append(c["url"])
            state.setdefault("published_title_hashes", []).append(c["title_hash"])
            state.setdefault("last_posts", []).append({
                "time_sakhalin": b.datetime.now(b.TZ).isoformat(timespec="seconds"),
                "source": c["source"],
                "category": c["category"],
                "category_key": c.get("category_key"),
                "title": row.get("title_ru") or c["title"],
                "url": c["url"],
                "image_url": c.get("image_url"),
                "image_hash": c.get("image_hash"),
                "published_at": c.get("published_at"),
                "with_image": True,
                "publish_method": "sendPhoto/uploaded_jpeg",
            })
            published += 1
            b.STATS["published"] = published
            time.sleep(12)
    b.log(f"Опубликовано: {published}")
    b.report()
    b.save_state(state)


b.main = main

if __name__ == "__main__":
    b.main()
