# v14: final overlay over v12.
# v14.5:
# - skip mixed digest/roundup articles instead of compressing several unrelated events into one post;
# - classify Russia/diplomacy/summit/APEC items as politics/economy, not war/security;
# - do not call v12 fallback resolver before our own visual planner;
# - prevent repeated fallback images by URL and by image-content hash;
# - avoid repeating recent fallback images from state.json;
# - use source image -> curated category image -> Pexels if key exists -> text-only;
# - removed unsafe random/loremflickr and broad Wikimedia search fallback because they produced cats/motherboards for war posts;
# - fallback images are used silently without caption labels.

import hashlib
import re
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import news_bot_v12 as v12

b = v12.b

USED_IMAGE_URLS = set()
USED_IMAGE_HASHES = set()

FOREIGN_MARKERS = [
    "usa", "united states", "сша", "америк", "trump", "трамп", "senate", "сенат",
    "iran", "иран", "israel", "израил", "gaza", "газа", "hormuz", "ормуз",
    "china", "китай", "eu", "евросоюз", "европа", "nato", "нато", "taiwan", "тайван",
]

WAR_TERMS = [
    "бпла", "беспилот", "дрон", "пво", "атака", "налет", "налёт", "удар", "обстрел",
    "взрыв", "ранен", "погиб", "уничтож", "минобороны", "всу", "сво", "боев", "промзон",
    "drone", "attack", "strike", "missile", "air defense", "war", "military",
]

DIPLOMACY_TERMS = [
    "саммит", "атэс", "апек", "визит", "пекин", "китай", "кнр", "си цзиньпин",
    "путин", "лавров", "мид", "переговор", "диалог", "дипломат", "сотрудничеств",
    "summit", "apec", "visit", "beijing", "china", "xi", "diplomacy", "talks",
]

ECONOMY_TERMS = [
    "эконом", "нефть", "газ", "спг", "рубль", "банк", "цб", "ставк", "инфляц",
    "бюджет", "экспорт", "импорт", "пошлин", "налог", "рынок", "торгов", "инвест",
    "oil", "gas", "lng", "economy", "finance", "bank", "inflation", "export", "import", "trade",
]

POWER_TERMS = ["электроэнерг", "электрич", "энергоснаб", "отключ", "обесточ", "свет", "power outage", "electricity"]

CYBER_TERMS = [
    "cve", "уязвим", "эксплуат", "exploit", "vulnerability", "vulnerabilities",
    "кибер", "взлом", "hack", "hacker", "malware", "security benchmark", "cve-bench",
]

ROUNDUP_TERMS = [
    "что случилось этой ночью",
    "что случилось ночью",
    "краткая сводка событий",
    "главные события ночи",
    "главное за ночь",
    "события к утру",
    "утренняя сводка",
    "вечерняя сводка",
    "главные новости к утру",
    "главные новости дня",
]

CATEGORY_FILES = {
    "🌍 Мир о России": [
        "Moscow Kremlin from Bolshoy Kamenny Bridge.jpg",
        "Vladimir Putin and Xi Jinping 2023.jpg",
        "G20 Summit 2022 - leaders.jpg",
    ],
    "🇷🇺 РФ / война и безопасность": [
        "Power transmission lines.jpg",
        "Substation power transformer.jpg",
        "Emergency response exercise.jpg",
        "Firefighters training.jpg",
    ],
    "🇷🇺 РФ / экономика": [
        "Oil platform P-51 (Brazil).jpg",
        "Gas pipeline.jpg",
        "Russian ruble banknotes 2022.jpg",
        "Industrial plant.jpg",
    ],
    "🇷🇺 РФ / законы и политика": [
        "Russian State Duma 2018.jpg",
        "APEC Vietnam 2017 leaders.jpg",
        "Great Hall of the People in Beijing.jpg",
        "Vladimir Putin 2024.jpg",
    ],
    "📍 Сахалин": [
        "Yuzhno-Sakhalinsk View.jpg",
        "Sakhalin Island, Russia.jpg",
        "Yuzhno-Sakhalinsk railway station.jpg",
    ],
    "🧭 Геополитика": [
        "United Nations Security Council Chamber.jpg",
        "Flags in front of the United Nations Office at Geneva.jpg",
        "G7 leaders 2022.jpg",
    ],
    "🌐 Мировые IT": [
        "Data Center (8655290531).jpg",
        "Server room.jpg",
        "Computer chips circuits.jpg",
        "Cyber security concept.jpg",
    ],
    "💻 IT / технологии": [
        "Data Center (8655290531).jpg",
        "Server room.jpg",
        "Computer chips circuits.jpg",
        "Cyber security concept.jpg",
    ],
    "🎮 Игры / индустрия": [
        "Video game controllers.jpg",
        "Gamescom 2018 gaming hall.jpg",
        "PlayStation 5 and DualSense.jpg",
    ],
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


def is_roundup_story(text: str) -> bool:
    text = (text or "").lower()
    if contains_any(text, ROUNDUP_TERMS):
        return True
    # Interfax digest pages usually include many short unrelated bullet points.
    # If a text has multiple unrelated agenda markers at once, skip it as a mixed digest.
    mixed_markers = 0
    for marker_group in (
        ["путин", "си цзиньпин", "китай", "пекин"],
        ["трамп", "сенат", "иран", "сша"],
        ["букер", "арсенал", "футбол"],
        ["g7", "искусственного интеллекта", "торговли"],
    ):
        if contains_any(text, marker_group):
            mixed_markers += 1
    return mixed_markers >= 3


def classify_v14(source_type, title, rss_text, page_desc, url):
    text = f"{title} {rss_text} {page_desc} {url}".lower()

    if is_roundup_story(text):
        b.log("skip mixed roundup/digest: " + str(title)[:120])
        return None, 0

    explicit_russia = v12.has_explicit_russia(text)
    has_war = contains_any(text, WAR_TERMS)
    has_diplomacy = contains_any(text, DIPLOMACY_TERMS)
    has_economy = contains_any(text, ECONOMY_TERMS)

    # Russian-language foreign-only stories are not Russian domestic streams.
    if source_type == "ru" and not explicit_russia and ("/world/" in (url or "") or contains_any(text, FOREIGN_MARKERS)):
        return "🧭 Геополитика", 88

    # Diplomacy/summits/visits are not war/security unless the item has a real attack/war marker.
    if source_type == "ru" and explicit_russia and has_diplomacy and not has_war:
        if has_economy:
            return "🇷🇺 РФ / экономика", 132
        return "🇷🇺 РФ / законы и политика", 122

    if source_type == "ru" and explicit_russia and has_economy and not has_war:
        return "🇷🇺 РФ / экономика", 132

    if source_type == "world" and not explicit_russia:
        if v12.strong_geopolitics_without_russia(text):
            return "🧭 Геополитика", 88
        return None, 0

    if source_type == "world" and explicit_russia:
        bonus = 20 if contains_any(text, WAR_TERMS + ECONOMY_TERMS) else 0
        return "🌍 Мир о России", 170 + bonus

    return v12.classify_v12(source_type, title, rss_text, page_desc, url)


def item_text(item: Dict) -> str:
    return f"{item.get('title','')} {item.get('summary','')} {item.get('category_hint','')} {item.get('source','')} {item.get('url','')} {item.get('image_url','')}".lower()


def image_digest(image_file) -> Optional[str]:
    try:
        if not image_file:
            return None
        data = image_file[0] if isinstance(image_file, tuple) else image_file
        if not data:
            return None
        return hashlib.sha1(data).hexdigest()
    except Exception:
        return None


def image_is_duplicate(url: Optional[str], image_file) -> bool:
    digest = image_digest(image_file)
    if url and url in USED_IMAGE_URLS:
        return True
    if digest and digest in USED_IMAGE_HASHES:
        return True
    return False


def remember_image(url: Optional[str], image_file) -> None:
    digest = image_digest(image_file)
    if url:
        USED_IMAGE_URLS.add(url)
    if digest:
        USED_IMAGE_HASHES.add(digest)


def category_fallback_urls(item: Dict) -> List[str]:
    category = item.get("category_hint") or ""
    files = CATEGORY_FILES.get(category) or CATEGORY_FILES["🧭 Геополитика"]
    seed = int(v12.safe_seed(item)[:8], 16)
    ordered = list(files)
    shift = seed % len(ordered)
    ordered = ordered[shift:] + ordered[:shift]
    return [
        "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(filename) + "?width=1280"
        for filename in ordered
    ]


def visual_search_queries(item: Dict) -> List[str]:
    text = item_text(item)
    queries: List[str] = []

    if contains_any(text, POWER_TERMS):
        queries.extend(["power transmission lines", "electrical substation", "power outage city"])
    if contains_any(text, ["дрон", "бпла", "беспилот", "пво", "drone"]):
        queries.extend(["drone sky", "air defense", "emergency services night"])
    if contains_any(text, ["саммит", "атэс", "апек", "визит", "китай", "пекин", "си цзиньпин"]):
        queries.extend(["summit diplomacy flags", "China diplomacy", "APEC summit"])
    if contains_any(text, CYBER_TERMS):
        queries.extend(["cybersecurity server", "data security", "server room"])
    if contains_any(text, ECONOMY_TERMS):
        queries.extend(["oil gas industry", "finance economy", "industrial plant"])

    # Pexels handles natural-language tags better than raw Wikimedia search.
    # Keep queries concise and avoid broad 'security/night' queries that produced irrelevant images.
    out = []
    for q in queries:
        q = q.replace(",", " ").strip()
        if q and q not in out:
            out.append(q)
    return out[:8]


def should_replace_source_image(item: Dict, mode: str, url: Optional[str]) -> bool:
    text = item_text(item)
    source = (item.get("source") or "").lower()
    image_url = (url or item.get("image_url") or "").lower()

    if mode == "source" and ("habr" in source or "habrastorage" in image_url or "habr.com" in text):
        if contains_any(text, CYBER_TERMS):
            return True

    if mode == "source" and "IT" in (item.get("category_hint") or "") and contains_any(text, CYBER_TERMS):
        if contains_any(image_url, ["habr", "preview", "cover", "trap", "cartoon", "draw", "illustration"]):
            return True

    return False


def try_image_urls(item: Dict, urls: List[str], mode: str):
    for url in urls:
        if url in USED_IMAGE_URLS:
            b.log("fallback image skipped by URL: " + url[:100])
            continue
        b.log(f"fallback image query [{mode}]: " + url)
        img = b.fetch_image_bytes(url)
        if not img:
            continue
        if image_is_duplicate(url, img):
            b.log("fallback image skipped by content hash: " + url[:100])
            remember_image(url, img)
            continue
        remember_image(url, img)
        item.update({
            "image_url": url,
            "image_file": img,
            "image_mode": mode,
            "image_note": "",
        })
        return img, mode, url
    return None, v12.NO_IMAGE, None


def try_pexels_fallback(item: Dict):
    seed = v12.safe_seed(item)
    urls: List[str] = []

    for query in visual_search_queries(item):
        try:
            pexels_url = v12.pexels_image(query, hashlib.sha1((seed + query).encode("utf-8")).hexdigest())
            if pexels_url:
                urls.append(pexels_url)
        except Exception as exc:
            b.log("Pexels search wrapper failed: " + str(exc))

    return try_image_urls(item, urls, "pexels")


def resolve_image_v14(item: Dict) -> Tuple[Optional[Tuple[bytes, str, str]], str, Optional[str]]:
    # Source image was attached during collection. Use it only if it is editorially acceptable
    # and not a duplicate. Do not call v12.resolve_image first: broad random fallbacks are forbidden here.
    img = item.get("image_file")
    url = item.get("image_url")
    mode = item.get("image_mode") or "source"

    if img and not should_replace_source_image(item, mode, url) and not image_is_duplicate(url, img):
        remember_image(url, img)
        item["image_note"] = ""
        return img, mode, url

    if img:
        reason = "duplicate" if image_is_duplicate(url, img) else "editorial gate"
        b.log(f"source image rejected by v14.5 {reason}: " + str(url)[:100])

    item.pop("image_file", None)
    item["image_mode"] = "source_rejected" if img else "no_source_image"
    item["image_note"] = ""

    # First try curated topic/category files. They are predictable and safer than random image search.
    img, mode, url = try_image_urls(item, category_fallback_urls(item), "category_file")
    if img:
        return img, mode, url

    # Pexels is allowed only when the owner explicitly provides PEXELS_API_KEY.
    # Without a key this returns nothing.
    img, mode, url = try_pexels_fallback(item)
    if img:
        return img, mode, url

    item["image_note"] = ""
    return None, v12.NO_IMAGE, None


def preload_recent_image_urls(state: Dict) -> None:
    USED_IMAGE_URLS.clear()
    USED_IMAGE_HASHES.clear()
    for post in (state.get("last_posts") or [])[-50:]:
        url = post.get("image_url")
        mode = post.get("image_mode") or ""
        if url and mode in {"pexels", "wikimedia", "category_file", "thematic_url"}:
            USED_IMAGE_URLS.add(url)


def main_v14() -> None:
    state = b.load_state()
    preload_recent_image_urls(state)

    b.log("Сбор кандидатов")
    items = b.collect(state)
    b.log(f"Кандидатов после фильтра v14.5: {len(items)}")
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
            image_file, image_mode, image_url = resolve_image_v14(item)
            if image_file:
                caption = b.make_post(row, item, 980)
                b.log(f"publish image-card [{image_mode}]: {item['category_hint']} | {item['source']} | {item['title'][:90]}")
                result = b.tg_photo(item, caption)
                method = f"sendPhoto/{image_mode}"
            else:
                text = b.make_post(row, item, 2600)
                b.log(f"publish text-no-preview [no-image]: {item['category_hint']} | {item['source']} | {item['title'][:90]}")
                result = v12.send_text_no_preview(text)
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


b.classify = classify_v14
v12.resolve_image = resolve_image_v14
b.main = main_v14

if __name__ == "__main__":
    b.main()
