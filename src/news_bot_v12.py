# v12: thematic image fallback over v10.
# Keeps previous editorial rules and adds visual fallback:
# real article image -> Pexels thematic image -> Wikimedia thematic image -> text without preview.
# Also keeps v11 publication priority: main hard news -> IT/games -> Sakhalin.

import hashlib
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

import news_bot_v10 as v10

b = v10.b
b.IMAGE_REQUIRED = False

SOURCE_IMAGE = "source"
PEXELS_IMAGE = "pexels"
WIKIMEDIA_IMAGE = "wikimedia"
NO_IMAGE = "none"

VISUAL_QUERIES = {
    "🌍 Мир о России": ["Russia diplomacy summit", "Kremlin international meeting", "Russia China diplomacy", "sanctions diplomacy economy"],
    "🇷🇺 РФ / война и безопасность": ["emergency services industrial area night", "security incident city night", "industrial emergency vehicles", "border security emergency"],
    "🇷🇺 РФ / экономика": ["oil gas refinery economy", "industrial plant economy", "currency finance economy", "pipeline industry economy"],
    "🇷🇺 РФ / законы и политика": ["parliament government law", "government building politics", "court law government", "parliament voting"],
    "📍 Сахалин": ["Sakhalin island landscape", "Yuzhno-Sakhalinsk city", "Sakhalin Russia city", "Sakhalin road winter"],
    "🧭 Геополитика": ["global diplomacy summit", "international flags diplomacy", "world leaders meeting", "UN diplomacy"],
    "🌐 Мировые IT": ["artificial intelligence server data center", "semiconductor chip technology", "cybersecurity data center", "AI servers technology"],
    "💻 IT / технологии": ["artificial intelligence server data center", "semiconductor chip technology", "cybersecurity data center", "AI servers technology"],
    "🎮 Игры / индустрия": ["video game controller", "gaming console controller", "video game development studio", "esports gaming computer"],
}

BAD_URL_TOKENS = ["logo", "icon", "sprite", "avatar", "placeholder", "button", "banner", "advert", "ads", "share", "social", "og-image", "preview-card", "facebook", "twitter", "telegram", "symbol", "emblem"]


def select_order_v12(items):
    main = [x for x in items if x["category_hint"] in (
        "🌍 Мир о России",
        "🇷🇺 РФ / война и безопасность",
        "🇷🇺 РФ / экономика",
        "🇷🇺 РФ / законы и политика",
    )]
    tech_game = [x for x in items if x["category_hint"] in (
        "🌐 Мировые IT",
        "🎮 Игры / индустрия",
    )]
    local = [x for x in items if x["category_hint"] == "📍 Сахалин"]

    ordered = []
    if main:
        ordered.append(main[0])
    if tech_game:
        ordered.append(tech_game[0])
    if local:
        ordered.append(local[0])

    for item in main + tech_game + local + items:
        if item not in ordered:
            ordered.append(item)
    return ordered


def safe_seed(item: Dict) -> str:
    raw = f"{item.get('category_hint', '')}|{item.get('title', '')}|{item.get('url', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def image_url_bad(url: Optional[str]) -> bool:
    if not url:
        return True
    u = url.lower()
    if not u.startswith(("http://", "https://")):
        return True
    if u.endswith((".svg", ".gif", ".ico")):
        return True
    return any(token in u for token in BAD_URL_TOKENS)


def visual_queries(item: Dict) -> List[str]:
    category = item.get("category_hint") or ""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    queries: List[str] = []

    if any(x in text for x in ["азс", "заправ", "промзон", "industrial"]):
        queries.append("industrial emergency services night")
    if any(x in text for x in ["нефть", "газ", "спг", "oil", "gas", "lng"]):
        queries.append("oil gas industry refinery")
    if any(x in text for x in ["цб", "рубль", "ставк", "банк", "inflation", "central bank"]):
        queries.append("finance currency economy")
    if any(x in text for x in ["openai", "chatgpt", "nvidia", "google", "microsoft", "ии", "нейросет"]):
        queries.append("artificial intelligence technology servers")
    if any(x in text for x in ["gta", "rockstar", "xbox", "playstation", "steam", "nintendo"]):
        queries.append("gaming console controller")
    if any(x in text for x in ["землетряс", "earthquake"]):
        queries.append("earthquake seismograph")
    if any(x in text for x in ["пожар", "fire"]):
        queries.append("fire emergency services")
    if any(x in text for x in ["дтп", "авария", "crash"]):
        queries.append("traffic accident emergency road")

    queries.extend(VISUAL_QUERIES.get(category, []))
    if not queries:
        queries.append("news editorial illustration")

    out: List[str] = []
    for query in queries:
        if query not in out:
            out.append(query)
    return out[:5]


def pexels_image(query: str, seed: str) -> Optional[str]:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key, "User-Agent": "SkySakhNewsBot/1.0"},
            params={"query": query, "orientation": "landscape", "per_page": 8, "locale": "en-US"},
            timeout=25,
        )
        if r.status_code >= 400:
            b.log(f"Pexels HTTP {r.status_code}: {query}")
            return None
        photos = r.json().get("photos") or []
        if not photos:
            return None
        idx = int(seed[:4], 16) % len(photos)
        for photo in photos[idx:] + photos[:idx]:
            src = photo.get("src") or {}
            url = src.get("large2x") or src.get("large") or src.get("original")
            if url and not image_url_bad(url):
                return url
    except Exception as exc:
        b.log("Pexels fallback failed: " + str(exc))
    return None


def wikimedia_image(query: str) -> Optional[str]:
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrnamespace": "6", "gsrsearch": query, "gsrlimit": "10",
                "prop": "imageinfo", "iiprop": "url|mime|size",
            },
            headers={"User-Agent": "SkySakhNewsBot/1.0"},
            timeout=25,
        )
        if r.status_code >= 400:
            return None
        pages = (r.json().get("query") or {}).get("pages") or {}
        ranked = []
        for page in pages.values():
            title = (page.get("title") or "").lower()
            if any(token in title for token in BAD_URL_TOKENS):
                continue
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = (info.get("mime") or "").lower()
            url = info.get("url")
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                continue
            if width < 700 or height < 350 or image_url_bad(url):
                continue
            ranked.append((width * height, url))
        if ranked:
            ranked.sort(reverse=True)
            return ranked[0][1]
    except Exception as exc:
        b.log("Wikimedia fallback failed: " + str(exc))
    return None


_original_fetch_image_bytes = b.fetch_image_bytes


def fetch_image_bytes_v12(url: Optional[str]):
    if image_url_bad(url):
        b.log("image rejected by v12 gate: " + str(url)[:90])
        return None
    return _original_fetch_image_bytes(url)


def resolve_image(item: Dict) -> Tuple[Optional[Tuple[bytes, str, str]], str, Optional[str]]:
    if item.get("image_file"):
        item["image_mode"] = SOURCE_IMAGE
        item["image_note"] = ""
        return item["image_file"], SOURCE_IMAGE, item.get("image_url")

    seed = safe_seed(item)
    for query in visual_queries(item):
        b.log("fallback image query: " + query)
        url = pexels_image(query, seed)
        if url:
            img = b.fetch_image_bytes(url)
            if img:
                item.update({"image_url": url, "image_file": img, "image_mode": PEXELS_IMAGE, "image_note": "🖼 Тематическая иллюстрация"})
                return img, PEXELS_IMAGE, url

        url = wikimedia_image(query)
        if url:
            img = b.fetch_image_bytes(url)
            if img:
                item.update({"image_url": url, "image_file": img, "image_mode": WIKIMEDIA_IMAGE, "image_note": "🖼 Тематическая иллюстрация"})
                return img, WIKIMEDIA_IMAGE, url

    item.update({"image_mode": NO_IMAGE, "image_note": ""})
    return None, NO_IMAGE, None


def make_post(row: Dict, item: Dict, max_len: int) -> str:
    note = item.get("image_note") or ""
    if note:
        base = b.make_post(row, item, max_len - len(note) - 4)
        return (base.rstrip() + "\n\n" + note)[:max_len]
    return b.make_post(row, item, max_len)


def send_text_no_preview(text: str) -> Dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat, "text": text, "parse_mode": "HTML", "link_preview_options": '{"is_disabled": true}'},
        timeout=90,
    )
    if r.status_code >= 400:
        raise RuntimeError(r.text[:700])
    return r.json()


def main_v12() -> None:
    state = b.load_state()
    b.log("Сбор кандидатов")
    items = b.collect(state)
    b.log(f"Кандидатов после фильтра v12: {len(items)}")
    if not items:
        b.save_state(state)
        return

    ordered = b.select_order(items)
    published = 0
    for item in ordered:
        if published >= b.POSTS_PER_RUN:
            break
        if item["url"] in state.get("published_urls", []):
            continue
        try:
            row = b.generate_row(item)
            image_file, image_mode, image_url = resolve_image(item)
            if image_file:
                caption = make_post(row, item, 980)
                b.log(f"publish image-card [{image_mode}]: {item['category_hint']} | {item['source']} | {item['title'][:90]}")
                result = b.tg_photo(item, caption)
                method = f"sendPhoto/{image_mode}"
            else:
                text = make_post(row, item, 2600)
                b.log(f"publish text-no-preview [no-image]: {item['category_hint']} | {item['source']} | {item['title'][:90]}")
                result = send_text_no_preview(text)
                method = "sendMessage/no-preview/no-image"
        except Exception as exc:
            b.log("candidate skipped: " + str(exc))
            continue

        if result.get("ok"):
            state.setdefault("published_urls", []).append(item["url"])
            state.setdefault("published_title_hashes", []).append(item["title_hash"])
            state.setdefault("last_posts", []).append({
                "time_sakhalin": datetime.now(b.TZ).isoformat(timespec="seconds"),
                "source": item["source"],
                "category": row.get("category") or item["category_hint"],
                "title": row.get("title_ru") or item["title"],
                "url": item["url"],
                "published_at": item.get("published_at"),
                "with_image": bool(image_file),
                "image_mode": image_mode,
                "image_url": image_url,
                "publish_method": method,
                "score": item.get("score"),
            })
            published += 1
            time.sleep(12)

    b.log(f"Опубликовано: {published}")
    b.save_state(state)


b.select_order = select_order_v12
b.fetch_image_bytes = fetch_image_bytes_v12
b.main = main_v12

if __name__ == "__main__":
    b.main()
