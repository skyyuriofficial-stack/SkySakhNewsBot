# v15: production source policy overlay over v14.
# Policy:
# - Interfax is removed completely;
# - the highest stream priority is "Мир о России";
# - each stream has several sources, not a single-source dependency;
# - source diversity is enforced before the editorial queue.

import re
from typing import Dict, List, Tuple

import news_bot_v14 as v14

b = v14.b
v12 = v14.v12
resolve_image_v14 = v14.resolve_image_v14

BLOCKED_SOURCES = {"Interfax"}

CATEGORY_PRIORITY = {
    "🌍 Мир о России": 1000,
    "📍 Сахалин": 950,
    "🇷🇺 РФ / война и безопасность": 900,
    "🧭 Геополитика": 820,
    "🇷🇺 РФ / происшествия": 780,
    "🇷🇺 РФ / экономика": 760,
    "🇷🇺 РФ / законы и политика": 700,
    "🌐 Мировые IT": 650,
    "🎮 Игры / индустрия": 600,
}

# name, source_type, Google News query, language, country
EXTRA_SOURCES: List[Tuple[str, str, str, str, str]] = [
    # 🌍 Мир о России / external view
    ("Euronews Russian", "world", "site:ru.euronews.com Россия OR российские OR Путин OR Москва OR Кремль OR Украина OR санкции OR экономика", "ru", "RU"),
    ("DW Russian", "world", "site:dw.com/ru Россия OR российские OR Путин OR Москва OR Кремль OR Украина OR санкции OR экономика", "ru", "RU"),
    ("France 24 Russian", "world", "site:france24.com/ru Россия OR российские OR Путин OR Москва OR Кремль OR Украина OR санкции", "ru", "RU"),
    ("RFI Russian", "world", "site:rfi.fr/ru Россия OR российские OR Путин OR Москва OR Кремль OR Украина OR санкции", "ru", "RU"),

    # 🧭 Геополитика
    ("Politico Europe", "world", "site:politico.eu Russia OR Ukraine OR EU OR NATO OR sanctions OR China OR Iran", "en", "US"),
    ("Al Jazeera", "world", "site:aljazeera.com Russia OR Ukraine OR NATO OR sanctions OR China OR Iran", "en", "US"),
    ("Financial Times", "world", "site:ft.com Russia OR Ukraine OR sanctions OR oil OR gas OR economy", "en", "US"),

    # 📍 Сахалин
    ("SakhalinMedia", "sakhalin", "site:sakhalinmedia.ru Сахалин OR Южно-Сахалинск OR Курилы OR Холмск OR Корсаков OR происшествие OR суд", "ru", "RU"),
    ("ASTV Sakhalin", "sakhalin", "site:astv.ru Сахалин OR Южно-Сахалинск OR Курилы OR Холмск OR Корсаков OR происшествие OR суд", "ru", "RU"),
    ("Sakh.com", "sakhalin", "site:sakh.com Сахалин OR Южно-Сахалинск OR Курилы OR Холмск OR Корсаков OR происшествие OR суд", "ru", "RU"),

    # 🇷🇺 РФ / economy, law, politics, incidents, security replacement pool
    ("RBC", "ru", "site:rbc.ru Россия OR экономика OR политика OR закон OR Госдума OR происшествие OR бизнес", "ru", "RU"),
    ("Kommersant", "ru", "site:kommersant.ru Россия OR экономика OR политика OR закон OR Госдума OR происшествие OR бизнес", "ru", "RU"),
    ("Vedomosti", "ru", "site:vedomosti.ru Россия OR экономика OR политика OR закон OR бизнес OR компании", "ru", "RU"),
    ("TASS", "ru", "site:tass.ru Россия OR экономика OR политика OR закон OR Госдума OR происшествие", "ru", "RU"),
    ("Forbes Russia", "ru", "site:forbes.ru Россия OR экономика OR бизнес OR компании OR доходы OR выручка", "ru", "RU"),

    # 🌐 Мировые IT / Habr alternatives
    ("CNews", "it", "site:cnews.ru ИИ OR искусственный интеллект OR кибербезопасность OR утечка OR чип OR процессор OR софт OR ИТ", "ru", "RU"),
    ("3DNews", "it", "site:3dnews.ru ИИ OR NVIDIA OR AMD OR Intel OR чип OR процессор OR видеокарта OR кибербезопасность", "ru", "RU"),
    ("TechCrunch", "it", "site:techcrunch.com OpenAI OR Google OR Microsoft OR Apple OR NVIDIA OR AI OR cybersecurity OR startup", "en", "US"),
    ("MIT Technology Review", "it", "site:technologyreview.com AI OR artificial intelligence OR chip OR cybersecurity OR OpenAI OR Google", "en", "US"),

    # 🎮 Игры / индустрия
    ("VGC", "gaming", "site:videogameschronicle.com Rockstar OR GTA OR PlayStation OR Xbox OR Nintendo OR Steam OR studio", "en", "US"),
    ("Game Developer", "gaming", "site:gamedeveloper.com game industry OR studio OR developer OR publisher OR Unreal OR Unity", "en", "US"),
    ("DTF", "gaming", "site:dtf.ru игры OR геймдев OR Steam OR Xbox OR PlayStation OR Nintendo OR GTA OR Rockstar", "ru", "RU"),
    ("StopGame", "gaming", "site:stopgame.ru игры OR геймдев OR Steam OR Xbox OR PlayStation OR Nintendo OR GTA OR Rockstar", "ru", "RU"),
]

PREFERRED_SOURCES = {
    "Euronews Russian": 360, "DW Russian": 300, "France 24 Russian": 285, "RFI Russian": 260,
    "Reuters": 190, "AP News": 170, "BBC World": 150, "Guardian World": 140,
    "Politico Europe": 135, "Al Jazeera": 125, "Financial Times": 120,
    "Sakhalin": 240, "SakhalinMedia": 230, "ASTV Sakhalin": 225, "Sakh.com": 215,
    "RBC": 185, "Kommersant": 175, "Vedomosti": 165, "TASS": 150, "Forbes Russia": 145,
    "BBC Technology": 100, "Guardian Technology": 90, "The Verge": 90, "Ars Technica": 85,
    "CNews": 115, "3DNews": 105, "TechCrunch": 105, "MIT Technology Review": 100,
    "VGC": 95, "Game Developer": 90, "DTF": 85, "StopGame": 80,
}

SOURCE_PENALTY = {
    "Habr": -90,
    "GameSpot": -60,
    "IGN": -60,
    "PC Gamer": -60,
    "Eurogamer": -60,
}


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def canonical_source_name(value: str, url: str = "") -> str:
    s = " " + norm(value + " " + (url or "")) + " "
    alias_map = {
        "Interfax": ["interfax", "интерфакс"],
        "Euronews Russian": ["euronews", "евроньюс"],
        "DW Russian": ["dw russian", "dw.com/ru", "deutsche welle"],
        "France 24 Russian": ["france 24", "france24.com/ru"],
        "RFI Russian": ["rfi russian", "rfi.fr/ru"],
        "Politico Europe": ["politico", "politico.eu"],
        "Al Jazeera": ["aljazeera", "al jazeera"],
        "Financial Times": ["financial times", "ft.com"],
        "Reuters": ["reuters"],
        "AP News": ["apnews", "ap news", "associated press"],
        "BBC Technology": ["bbc technology"],
        "BBC World": ["bbc"],
        "Guardian Technology": ["guardian technology"],
        "Guardian World": ["guardian"],
        "The Verge": ["theverge", "the verge"],
        "Ars Technica": ["arstechnica", "ars technica"],
        "CNews": ["cnews"],
        "3DNews": ["3dnews"],
        "TechCrunch": ["techcrunch"],
        "MIT Technology Review": ["technologyreview", "mit technology review"],
        "Habr": ["habr", "хабр"],
        "GameSpot": ["gamespot"],
        "IGN": ["ign.com", " ign "],
        "PC Gamer": ["pcgamer", "pc gamer"],
        "Eurogamer": ["eurogamer"],
        "VGC": ["videogameschronicle", " vgc "],
        "Game Developer": ["gamedeveloper", "game developer"],
        "DTF": ["dtf.ru", " dtf "],
        "StopGame": ["stopgame"],
        "SakhalinMedia": ["sakhalinmedia"],
        "ASTV Sakhalin": ["astv"],
        "Sakh.com": ["sakh.com"],
        "Sakhalin": ["sakhalin", "сахалин"],
        "RBC": ["rbc.ru", " rbc ", "рбк"],
        "Kommersant": ["kommersant", "коммерсант"],
        "Vedomosti": ["vedomosti", "ведомости"],
        "TASS": ["tass.ru", " тасс "],
        "Forbes Russia": ["forbes.ru", "forbes russia"],
    }
    for name, tokens in alias_map.items():
        if any(token in s for token in tokens):
            return name
    return str(value or "Источник")


def is_blocked_source_name(name: str, url: str = "") -> bool:
    return canonical_source_name(name, url) in BLOCKED_SOURCES


def add_or_keep_sources() -> None:
    sources = []
    for name, stype, rss in list(getattr(b, "SOURCES", []) or []):
        if is_blocked_source_name(str(name), str(rss)):
            continue
        sources.append((canonical_source_name(str(name), str(rss)), stype, rss))
    existing = {canonical_source_name(str(name), str(rss)) for name, _stype, rss in sources}
    for name, stype, query, lang, country in EXTRA_SOURCES:
        if name not in existing and name not in BLOCKED_SOURCES:
            sources.append((name, stype, b.gnews(query, lang, country)))
            existing.add(name)
    b.SOURCES = sources


def source_adjusted_score(item: Dict) -> int:
    src = canonical_source_name(item.get("source") or "", item.get("url") or "")
    if src in BLOCKED_SOURCES:
        return 0
    base = int(item.get("score") or 0)
    score = base + PREFERRED_SOURCES.get(src, 0) + SOURCE_PENALTY.get(src, 0)
    category = item.get("category_hint") or item.get("category") or ""
    if category == "🌍 Мир о России":
        score += 220
        if src in {"Euronews Russian", "DW Russian", "France 24 Russian", "RFI Russian", "Reuters", "AP News", "BBC World", "Guardian World"}:
            score += 140
    elif category == "📍 Сахалин":
        score += 90
    elif category == "🇷🇺 РФ / война и безопасность":
        score += 75
    return max(1, score)


def recent_source_counts() -> Dict[str, int]:
    try:
        state = b.load_state()
    except Exception:
        state = {}
    counts: Dict[str, int] = {}
    for post in (state.get("last_posts", []) or [])[-12:]:
        src = canonical_source_name(post.get("source") or "", post.get("url") or "")
        counts[src] = counts.get(src, 0) + 1
    return counts


def source_soft_cap(src: str) -> int:
    if src in {"Habr", "GameSpot", "IGN", "PC Gamer", "Eurogamer", "VGC", "Game Developer", "DTF", "StopGame"}:
        return 1
    return 2


def select_order_v15(items: List[Dict]) -> List[Dict]:
    recent_counts = recent_source_counts()
    enriched: List[Dict] = []
    for raw in items:
        src = canonical_source_name(raw.get("source") or "", raw.get("url") or "")
        if src in BLOCKED_SOURCES:
            continue
        item = dict(raw)
        item["source"] = src
        item["score"] = source_adjusted_score(item)
        if recent_counts.get(src, 0) >= source_soft_cap(src):
            item["score"] = max(1, int(item.get("score") or 0) - 190)
        enriched.append(item)

    enriched.sort(key=lambda x: (-CATEGORY_PRIORITY.get(x.get("category_hint"), 0), -int(x.get("score") or 0), x.get("source") or ""))

    ordered: List[Dict] = []
    used_sources = set()
    used_categories = set()
    for item in enriched:
        src = canonical_source_name(item.get("source") or "", item.get("url") or "")
        cat = item.get("category_hint") or ""
        if src in used_sources or cat in used_categories:
            continue
        ordered.append(item)
        used_sources.add(src)
        used_categories.add(cat)
    for item in enriched:
        src = canonical_source_name(item.get("source") or "", item.get("url") or "")
        if item not in ordered and src not in used_sources:
            ordered.append(item)
            used_sources.add(src)
    for item in enriched:
        if item not in ordered:
            ordered.append(item)
    return ordered


add_or_keep_sources()
b.select_order = select_order_v15


def main_v15() -> None:
    return v14.main_v14()


b.main = main_v15

if __name__ == "__main__":
    b.main()
