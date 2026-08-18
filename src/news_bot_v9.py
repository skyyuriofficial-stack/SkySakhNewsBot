# SkySakhNews stable production overlay over v8.
# Production goals:
# - source type is classified before geography;
# - wrong source/stream pairs are rejected;
# - bad or duplicate images degrade to text-only instead of killing the news;
# - no Habr hobby noise in production;
# - direct TASS RSS is used for a reliable Russian news stream;
# - every run writes a health record to state.json.

import json
import re
import time
import hashlib
import urllib.parse
from datetime import datetime

import requests
import news_bot_v8 as b

VERSION = "stable-v9.3"

# Liveness first: a good story without a safe photo may be published as text.
# A wrong/duplicate picture must never be used merely to satisfy IMAGE_REQUIRED.
b.IMAGE_REQUIRED = False

# Remove the noisy broad Habr feed from production and add a direct, verified RSS source.
b.SOURCES = [s for s in b.SOURCES if s[0] != "Habr"]
if not any(s[0] == "TASS" for s in b.SOURCES):
    b.SOURCES.append(("TASS", "ru", "https://tass.ru/rss/v2.xml", 98))

b.CAT["ru_security"] = ("🇷🇺 Россия / безопасность", "РОССИЯ | БЕЗОПАСНОСТЬ")

RUSSIA_MARKERS = [
    "russia", "russian", "moscow", "kremlin", "putin", "lavrov",
    "россия", "россии", "россию", "россией", "рф", "российск",
    "москва", "кремль", "путин", "лавров",
]
GEO_MARKERS = [
    "iran", "иран", "israel", "израиль", "usa", "u.s.", "сша", "america", "американ",
    "trump", "трамп", "nato", "нато", "china", "китай", "taiwan", "тайвань", "g7", "g20",
    "war", "война", "conflict", "конфликт", "strike", "attack", "удар", "удары",
    "missile", "ракета", "drone", "дрон", "military", "военн", "base", "база",
    "air defense", "пво", "sanctions", "санкц", "oil", "нефть", "gas", "газ",
    "middle east", "ближн", "йемен", "yemen",
]
SECURITY_MARKERS = [
    "беспилот", "бпла", "дрон", "дроны", "пво", "минобороны", "атака", "атаковали",
    "угроза", "опасность", "воздушная опасность", "режим опасности", "аэропорт",
    "аэропорты", "росавиация", "воздушное судно", "ограничения", "план ковер",
    "всу", "обломки", "ракета", "ракет", "перехват", "сбили", "сбит",
]
IT_STRICT = [
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini", "google", "microsoft",
    "apple", "meta", "nvidia", "amd", "intel", "tsmc", "semiconductor", "chip", "chips",
    "cyberattack", "cybersecurity", "ransomware", "malware", "android", "ios", "linux",
    "windows", "telegram", "artificial intelligence", "llm", "neural network",
    "ии", "нейросет", "искусственный интеллект", "кибератак", "кибербезопас",
    "утечка данных", "чип", "процессор", "видеокарт", "сервер", "программирован",
    "разработчик", "софт", "приложение", "операционная система",
]

def hit(text, term):
    raw = (text or "").lower()
    t = term.lower().strip()
    if not t:
        return False
    if " " in t or "-" in t:
        return t in raw
    if re.fullmatch(r"[a-z0-9.]{1,4}", t):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw))
    if re.fullmatch(r"[a-z0-9.]+", t):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw))
    return t in raw

def hits(text, markers):
    return [m for m in markers if hit(text, m)]

def classify(src_type, weight, title, rss_text, desc, url):
    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if b.terms(text, b.NOISE):
        return None, 0, "noise"

    # 1) SOURCE TYPE FIRST. IT/world feeds can never accidentally become Sakhalin.
    if src_type == "it":
        return ("it", weight + 10, "it_strict") if hits(text, IT_STRICT) else (None, 0, "it_not_relevant")

    if src_type == "sakhalin":
        if b.terms(text, b.QUAKE):
            return "sakh_quake", weight + 36, "local_quake"
        if b.terms(text, b.LOCAL_EVENT):
            return "sakh_chp", weight + 32, "local_chp"
        if b.terms(text, b.LOCAL) or len(b.clean(rss_text + " " + desc)) >= 140:
            return "sakh", weight + 18, "local_general"
        return None, 0, "local_low_signal"

    if src_type == "world":
        if hits(text, RUSSIA_MARKERS):
            return "world_ru", weight + 20, "world_about_russia"
        if len(set(hits(text, GEO_MARKERS))) >= 2:
            return "geo", weight + 10, "geo"
        return None, 0, "world_not_in_stream"

    if src_type == "ru":
        if "/moscow/" in path:
            return None, 0, "moscow_noise"

        # A national source may enter the local stream only with explicit Sakhalin geography.
        if b.terms(text, b.LOCAL):
            if b.terms(text, b.QUAKE):
                return "sakh_quake", weight + 24, "ru_local_quake"
            if b.terms(text, b.LOCAL_EVENT):
                return "sakh_chp", weight + 20, "ru_local_chp"
            return "sakh", weight + 12, "ru_local"

        if hits(text, SECURITY_MARKERS):
            return "ru_security", weight + 18, "ru_security"
        if b.terms(text, b.ECO):
            return "ru_eco", weight + 12, "ru_eco"
        if b.terms(text, b.POL) or hits(text, RUSSIA_MARKERS):
            return "ru_pol", weight + 10, "ru_pol"
        if len(set(hits(text, GEO_MARKERS))) >= 2:
            return "geo", weight + 6, "ru_geo"
        return None, 0, "ru_not_in_stream"

    return None, 0, "unknown_source_type"

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
    if cat == "ru_security" and any(x in text for x in (
        "аэропорт", "росавиац", "воздушн", "беспилот", "бпла", "дрон", "пво", "опасност"
    )):
        return "ru_security_airspace_drone"
    if cat == "sakh_quake":
        return "sakh_quake"
    words = [w for w in b.norm(item.get("title", "")).split() if len(w) >= 5][:5]
    return cat + ":" + "_".join(words)

def valid_source_stream(item):
    cat = item.get("category_key", "")
    src = (item.get("source") or "").lower()
    url = (item.get("url") or "").lower()
    body = f"{item.get('title','')} {item.get('source_text','')}".lower()

    if cat in ("sakh", "sakh_chp", "sakh_quake"):
        # Trusted local publishers are allowed; otherwise explicit local geography is mandatory.
        trusted_local = any(x in src + " " + url for x in (
            "astv", "sakhalinmedia", "sakh.online", "sakh.com", "sakhalin google"
        ))
        if not trusted_local and not b.terms(body, b.LOCAL):
            return False, "local_without_geo"

    if cat == "world_ru" and not hits(body, RUSSIA_MARKERS):
        return False, "world_ru_without_russia"

    if ("bbc technology" in src or "guardian technology" in src) and cat != "it":
        return False, "it_source_wrong_stream"

    return True, "ok"

def collect(state):
    items = _old_collect(state)
    recent_hashes = {
        p.get("image_hash") for p in state.get("last_posts", [])[-60:] if p.get("image_hash")
    }
    recent_urls = {
        p.get("image_url") for p in state.get("last_posts", [])[-60:] if p.get("image_url")
    }
    seen_hashes, seen_urls, seen_clusters = set(), set(), set()
    filtered = []

    for item in items:
        ok, why = valid_source_stream(item)
        if not ok:
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log(f"skip source-stream guard [{why}]: {item.get('title','')[:90]}")
            continue

        # Never use Interfax-hosted social/title cards. Keep the story as text-only.
        if "interfax" in (item.get("source") or "").lower():
            item["image"] = None
            item["image_url"] = None

        ih = image_hash(item)
        iu = item.get("image_url") or ""

        # Duplicate visual no longer kills a good story: degrade only the image.
        if ih and (ih in seen_hashes or ih in recent_hashes):
            b.log("duplicate image -> text-only: " + item.get("title", "")[:90])
            item["image"] = None
            item["image_url"] = None
            ih = ""
            iu = ""
        elif iu and (iu in seen_urls or iu in recent_urls):
            b.log("duplicate image url -> text-only: " + item.get("title", "")[:90])
            item["image"] = None
            item["image_url"] = None
            ih = ""
            iu = ""

        cluster = topic_cluster(item)
        if cluster in seen_clusters and item.get("category_key") in ("ru_security", "ru_pol", "ru_eco", "geo"):
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log("skip duplicate topic cluster: " + item.get("title", "")[:90])
            continue

        item["image_hash"] = ih or None
        if ih:
            seen_hashes.add(ih)
        if iu:
            seen_urls.add(iu)
        seen_clusters.add(cluster)
        filtered.append(item)

    b.STATS["candidates"] = len(filtered)
    return filtered

b.collect = collect

def ordered(cands):
    local = [c for c in cands if c["category_key"] in ("sakh_quake", "sakh_chp", "sakh")]
    other = [c for c in cands if c not in local]
    out = []

    # Editorial balance: one local first when available, then one different stream.
    if local:
        out.append(local[0])
    for key in ("world_ru", "ru_security", "ru_pol", "ru_eco", "geo", "it"):
        for c in other:
            if c["category_key"] == key and c not in out:
                out.append(c)

    for c in local[1:] + other:
        if c not in out:
            out.append(c)
    return out

b.ordered = ordered

def text_post(row, c):
    title = b.clean(row.get("title_ru"))
    body = [b.clean(x) for x in row.get("body", []) if b.clean(x)]
    text = (
        f"{b.esc(c['category'])}\n\n"
        f"<b>{b.esc(title)}</b>\n\n"
        + "\n\n".join(b.esc(x) for x in body)
        + f"\n\n{b.esc(c['footer'])} · <a href=\"{b.attr(c['url'])}\">{b.esc(c['source'])}</a>"
    )
    return text[:4000]

def send_text(row, c):
    token = b.os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = b.os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    payload = {
        "chat_id": chat,
        "text": text_post(row, c),
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(r.text[:700])
    return r.json()

def main():
    state = b.load_state()
    started = datetime.now(b.TZ).isoformat(timespec="seconds")
    run = {
        "version": VERSION,
        "started_sakhalin": started,
        "status": "running",
        "candidates": 0,
        "published": 0,
    }
    state["last_run"] = run

    try:
        b.log(f"SkySakhNews {VERSION} start")
        cands = b.collect(state)
        run["candidates"] = len(cands)
        b.log(f"Кандидатов после production-фильтра: {len(cands)}")

        published = 0
        for c in b.ordered(cands):
            if published >= b.POSTS_PER_RUN:
                break
            if c["url"] in state.get("published_urls", []):
                continue

            row = b.valid_post(c)
            if not row:
                continue

            result = None
            method = None
            with_image = bool(c.get("image"))

            if with_image:
                try:
                    result = b.send_photo(c, b.caption(row, c))
                    method = "sendPhoto/stable-v9.3"
                except Exception as ex:
                    b.STATS["telegram_fail"] += 1
                    b.log(f"photo failed -> text fallback: {c['title'][:90]} | {ex}")
                    result = send_text(row, c)
                    method = "sendMessage/fallback-after-photo"
                    with_image = False
                    c["image"] = None
                    c["image_url"] = None
                    c["image_hash"] = None
            else:
                result = send_text(row, c)
                method = "sendMessage/no-safe-image"

            if result and result.get("ok"):
                state.setdefault("published_urls", []).append(c["url"])
                state.setdefault("published_title_hashes", []).append(c["title_hash"])
                state.setdefault("last_posts", []).append({
                    "time_sakhalin": datetime.now(b.TZ).isoformat(timespec="seconds"),
                    "source": c["source"],
                    "category": c["category"],
                    "category_key": c.get("category_key"),
                    "title": row.get("title_ru") or c["title"],
                    "url": c["url"],
                    "image_url": c.get("image_url"),
                    "image_hash": c.get("image_hash"),
                    "published_at": c.get("published_at"),
                    "with_image": with_image,
                    "publish_method": method,
                })
                published += 1
                b.STATS["published"] = published
                run["published"] = published
                time.sleep(8)

        run["status"] = "ok"
        run["finished_sakhalin"] = datetime.now(b.TZ).isoformat(timespec="seconds")
        run["stats"] = dict(b.STATS)
        b.log(f"Опубликовано: {published}")
        b.report()
        b.save_state(state)

    except Exception as ex:
        run["status"] = "error"
        run["error"] = str(ex)[:1000]
        run["finished_sakhalin"] = datetime.now(b.TZ).isoformat(timespec="seconds")
        try:
            b.save_state(state)
        finally:
            raise

b.main = main

if __name__ == "__main__":
    b.main()
