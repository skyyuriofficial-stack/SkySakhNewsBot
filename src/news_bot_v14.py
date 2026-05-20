# v14: final overlay over v12.
# v14.3:
# - do not reuse the same fallback image inside one run;
# - use several category images, not one fixed image per category;
# - classify Russia/diplomacy/summit items as politics/diplomacy, not war/security;
# - choose more precise visual tags for power outages, drones, diplomacy, economy, IT and games;
# - fallback images are used silently without caption labels.

import re
import urllib.parse
from typing import Dict, List, Optional, Tuple

import news_bot_v12 as v12

b = v12.b

USED_IMAGE_URLS = set()

FOREIGN_MARKERS = [
    "usa", "united states", "сша", "америк", "trump", "трамп", "senate", "сенат",
    "iran", "иран", "israel", "израил", "gaza", "газа", "hormuz", "ормуз",
    "china", "китай", "eu", "евросоюз", "европа", "nato", "нато", "taiwan", "тайван",
]

WAR_TERMS = [
    "бпла", "беспилот", "дрон", "пво", "атака", "налет", "налёт", "удар", "обстрел",
    "взрыв", "ранен", "погиб", "уничтож", "минобороны", "всу", "сво", "боев",
    "drone", "attack", "strike", "missile", "air defense", "war", "military",
]

DIPLOMACY_TERMS = [
    "саммит", "атэс", "апек", "визит", "пекин", "китай", "кнр", "си цзиньпин",
    "путин", "лавров", "мид", "переговор", "диалог", "дипломат", "сотрудничеств",
    "summit", "apec", "visit", "beijing", "china", "xi", "diplomacy", "talks",
]

ECONOMY_TERMS = [
    "эконом", "нефть", "газ", "спг", "рубль", "банк", "цб", "ставк", "инфляц",
    "бюджет", "экспорт", "импорт", "пошлин", "налог", "рынок", "oil", "gas", "lng",
    "economy", "finance", "bank", "inflation", "export", "import",
]

POWER_TERMS = ["электроэнерг", "электрич", "энергоснаб", "отключ", "свет", "power outage", "electricity"]

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
        "Firefighters training.jpg",
        "Emergency response exercise.jpg",
        "Power transmission lines.jpg",
        "Substation power transformer.jpg",
    ],
    "🇷🇺 РФ / экономика": [
        "Oil platform P-51 (Brazil).jpg",
        "Gas pipeline.jpg",
        "Russian ruble banknotes 2022.jpg",
        "Industrial plant.jpg",
    ],
    "🇷🇺 РФ / законы и политика": [
        "Russian State Duma 2018.jpg",
        "Vladimir Putin 2024.jpg",
        "APEC Vietnam 2017 leaders.jpg",
        "Great Hall of the People in Beijing.jpg",
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

    # Russian-language stories with Putin/APEC/China/summits must not fall into war/security
    # unless there is a real war/security marker.
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
            b.log("fallback image skipped, already used in this run: " + url[:100])
            continue
        b.log(f"fallback image query [{mode}]: " + url)
        img = b.fetch_image_bytes(url)
        if img:
            USED_IMAGE_URLS.add(url)
            item.update({
                "image_url": url,
                "image_file": img,
                "image_mode": mode,
                "image_note": "",
            })
            return img, mode, url
    return None, v12.NO_IMAGE, None


_original_resolve_image = v12.resolve_image


def resolve_image_v14(item: Dict) -> Tuple[Optional[Tuple[bytes, str, str]], str, Optional[str]]:
    img, mode, url = _original_resolve_image(item)

    if img and url in USED_IMAGE_URLS:
        b.log("source/fallback image rejected: duplicate in this run " + str(url)[:100])
        img = None

    if img and not should_replace_source_image(item, mode, url):
        USED_IMAGE_URLS.add(url)
        item["image_note"] = ""
        return img, mode, url

    if img and should_replace_source_image(item, mode, url):
        b.log("source image rejected by v14.3 editorial gate: " + str(url)[:100])

    item.pop("image_file", None)
    item["image_mode"] = "source_rejected" if img else "no_source_image"
    item["image_note"] = ""

    img, mode, url = try_image_urls(item, category_fallback_urls(item), "category_file")
    if img:
        return img, mode, url

    img, mode, url = try_image_urls(item, thematic_fallback_urls(item), "thematic_url")
    if img:
        return img, mode, url

    item["image_note"] = ""
    return None, v12.NO_IMAGE, None


b.classify = classify_v14
v12.resolve_image = resolve_image_v14
b.main = v12.main_v12

if __name__ == "__main__":
    b.main()
