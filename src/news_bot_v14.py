# v14: final overlay over v12.
# v14.4:
# - two-layer editorial gate: topic classification first, visual plan second;
# - do not call v12 fallback resolver before our own duplicate-control logic;
# - prevent repeated fallback images by URL and by image-content hash;
# - also avoid repeating recent fallback images from state.json;
# - classify Russia/diplomacy/summit/APEC items as politics/economy, not war/security;
# - choose topic-specific visuals for power outages, drones, diplomacy, economy, IT and games;
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


def classify_v14(source_type, title, rss_text, page_desc, url):
    text = f"{title} {rss_text} {page_desc} {url}".lower()
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

    queries.extend(thematic_tag_sets(item))

    out = []
    for q in queries:
        q = q.replace(",", " ").strip()
        if q and q not in out:
            out.append(q)
    return out[:10]


def thematic_tag_sets(item: Dict) -> List[str]:
    category = item.get("category_hint") or ""
    text = item_text(item)
    sets: List[str] = []

    if contains_any(text, POWER_TERMS):
        sets.extend(["power,line,electricity", "substation,electricity", "power,outage,city"])
    if contains_any(text, ["дрон", "бпла", "беспилот", "пво", "drone"]):
        sets.extend(["drone,sky,security", "air,defense,sky", "emergency,night,city"])
    if contains_any(text, ["саммит", "атэс", "апек", "визит", "китай", "пекин", "си цзиньпин"]):
        sets.extend(["summit,diplomacy,flags", "china,diplomacy,flags", "government,meeting,flags"])
    if "🎮" in category:
        sets.extend(["gaming,controller,console", "esports,gaming,computer"])
    if "IT" in category or "технолог" in category or contains_any(text, ["openai", "chatgpt", "nvidia", "google", "microsoft", "ии", "нейросет", "chip", "server"]):
        if contains_any(text, CYBER_TERMS):
            sets.extend(["cybersecurity,server,technology", "data,security,server", "code,security,computer"])
        else:
            sets.extend(["technology,server,computer", "data,center,server", "semiconductor,chip,technology"])
    if "Сахалин" in category:
        sets.extend(["island,landscape,russia", "city,winter,russia"])
    if "эконом" in category or contains_any(text, ECONOMY_TERMS):
        sets.extend(["industry,economy,oil", "gas,pipeline,industry", "finance,currency,economy"])
    if "война" in category or "безопасность" in category or contains_any(text, WAR_TERMS):
        sets.extend(["emergency,security,night", "emergency,services,city", "security,industrial,night"])
    if "полит" in category or "законы" in category:
        sets.extend(["government,parliament,law", "diplomacy,flags,summit"])
    if "Геополитика" in category or contains_any(text, FOREIGN_MARKERS):
        sets.extend(["diplomacy,flags,summit", "world,leaders,meeting"])
    if "Мир о России" in category:
        sets.extend(["russia,diplomacy,flags", "kremlin,moscow,russia"])

    if not sets:
        sets.append("news,city,world")

    out = []
    for s in sets:
        if s not in out:
            out.append(s)
    return out[:8]


def thematic_fallback_urls(item: Dict) -> List[str]:
    base_seed = int(v12.safe_seed(item)[:8], 16) % 1000000
    urls = []
    for i, tags in enumerate(thematic_tag_sets(item)):
        urls.append(f"https://loremflickr.com/1280/720/{urllib.parse.quote(tags)}?lock={base_seed + i * 997}")
    return urls


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


def try_search_fallback(item: Dict):
    seed = v12.safe_seed(item)
    urls: List[Tuple[str, str]] = []

    for idx, query in enumerate(visual_search_queries(item)):
        try:
            pexels_url = v12.pexels_image(query, hashlib.sha1((seed + query).encode("utf-8")).hexdigest())
            if pexels_url:
                urls.append((pexels_url, "pexels"))
        except Exception as exc:
            b.log("Pexels search wrapper failed: " + str(exc))

        try:
            wiki_url = v12.wikimedia_image(query)
            if wiki_url:
                urls.append((wiki_url, "wikimedia"))
        except Exception as exc:
            b.log("Wikimedia search wrapper failed: " + str(exc))

    for url, mode in urls:
        img, got_mode, got_url = try_image_urls(item, [url], mode)
        if img:
            return img, got_mode, got_url
    return None, v12.NO_IMAGE, None


def resolve_image_v14(item: Dict) -> Tuple[Optional[Tuple[bytes, str, str]], str, Optional[str]]:
    # Source image was attached during collection. Use it only if it is editorially acceptable
    # and not a duplicate. Do not call v12.resolve_image first, because v12 can already choose
    # a generic fallback before this deeper visual planner has a chance to work.
    img = item.get("image_file")
    url = item.get("image_url")
    mode = item.get("image_mode") or "source"

    if img and not should_replace_source_image(item, mode, url) and not image_is_duplicate(url, img):
        remember_image(url, img)
        item["image_note"] = ""
        return img, mode, url

    if img:
        reason = "duplicate" if image_is_duplicate(url, img) else "editorial gate"
        b.log(f"source image rejected by v14.4 {reason}: " + str(url)[:100])

    item.pop("image_file", None)
    item["image_mode"] = "source_rejected" if img else "no_source_image"
    item["image_note"] = ""

    img, mode, url = try_search_fallback(item)
    if img:
        return img, mode, url

    img, mode, url = try_image_urls(item, category_fallback_urls(item), "category_file")
    if img:
        return img, mode, url

    img, mode, url = try_image_urls(item, thematic_fallback_urls(item), "thematic_url")
    if img:
        return img, mode, url

    item["image_note"] = ""
    return None, v12.NO_IMAGE, None


def preload_recent_image_urls(state: Dict) -> None:
    USED_IMAGE_URLS.clear()
    USED_IMAGE_HASHES.clear()
    for post in (state.get("last_posts") or [])[-30:]:
        url = post.get("image_url")
        mode = post.get("image_mode") or ""
        if url and mode in {"pexels", "wikimedia", "category_file", "thematic_url"}:
            USED_IMAGE_URLS.add(url)


def main_v14() -> None:
    state = b.load_state()
    preload_recent_image_urls(state)

    b.log("Сбор кандидатов")
    items = b.collect(state)
    b.log(f"Кандидатов после фильтра v14.4: {len(items)}")
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
