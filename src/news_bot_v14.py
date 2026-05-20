# v14: final overlay over v12.
# Keeps v12 rules, adds stricter category gate and a final Wikimedia category image fallback.

import re
import urllib.parse
from typing import Dict, Optional, Tuple

import news_bot_v12 as v12

b = v12.b

FOREIGN_MARKERS = [
    "usa", "united states", "сша", "америк", "trump", "трамп", "senate", "сенат",
    "iran", "иран", "israel", "израил", "gaza", "газа", "hormuz", "ормуз",
    "china", "китай", "eu", "евросоюз", "европа", "nato", "нато", "taiwan", "тайван",
]

CATEGORY_FILES = {
    "🌍 Мир о России": "Moscow Kremlin from Bolshoy Kamenny Bridge.jpg",
    "🇷🇺 РФ / война и безопасность": "Firefighters training.jpg",
    "🇷🇺 РФ / экономика": "Oil platform P-51 (Brazil).jpg",
    "🇷🇺 РФ / законы и политика": "Russian State Duma 2018.jpg",
    "📍 Сахалин": "Yuzhno-Sakhalinsk View.jpg",
    "🧭 Геополитика": "United Nations Security Council Chamber.jpg",
    "🌐 Мировые IT": "Data Center (8655290531).jpg",
    "💻 IT / технологии": "Data Center (8655290531).jpg",
    "🎮 Игры / индустрия": "Video game controllers.jpg",
}


def contains_any(text, terms):
    raw = " " + (text or "").lower() + " "
    for term in terms:
        t = term.lower().strip()
        if not t:
            continue
        if re.fullmatch(r"[a-z0-9.]+", t):
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw):
                return True
        elif t in raw:
            return True
    return False


def classify_v14(source_type, title, rss_text, page_desc, url):
    text = f"{title} {rss_text} {page_desc} {url}".lower()
    explicit_russia = v12.has_explicit_russia(text)

    if source_type == "ru" and not explicit_russia and ("/world/" in (url or "") or contains_any(text, FOREIGN_MARKERS)):
        return "🧭 Геополитика", 88

    if source_type == "world" and not explicit_russia:
        if v12.strong_geopolitics_without_russia(text):
            return "🧭 Геополитика", 88
        return None, 0

    return v12.classify_v12(source_type, title, rss_text, page_desc, url)


def category_fallback_url(item: Dict) -> str:
    category = item.get("category_hint") or ""
    filename = CATEGORY_FILES.get(category, "United Nations Security Council Chamber.jpg")
    return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(filename) + "?width=1280"


_original_resolve_image = v12.resolve_image


def resolve_image_v14(item: Dict) -> Tuple[Optional[Tuple[bytes, str, str]], str, Optional[str]]:
    img, mode, url = _original_resolve_image(item)
    if img:
        return img, mode, url

    url = category_fallback_url(item)
    b.log("fallback image query: category file " + url)
    img = b.fetch_image_bytes(url)
    if img:
        item.update({
            "image_url": url,
            "image_file": img,
            "image_mode": "category_file",
            "image_note": "🖼 Тематическая иллюстрация",
        })
        return img, "category_file", url

    return None, v12.NO_IMAGE, None


b.classify = classify_v14
v12.resolve_image = resolve_image_v14
b.main = v12.main_v12

if __name__ == "__main__":
    b.main()
