# v15: source policy overlay over v14.
# Owner source policy:
# - Interfax is completely removed from active collection and publication candidates;
# - Euronews Russian is added as a preferred external source for "Мир о России";
# - ordering favours source diversity before the editorial queue.

import re
from typing import Dict, List

import news_bot_v14 as v14

b = v14.b
v12 = v14.v12
resolve_image_v14 = v14.resolve_image_v14

EURONEWS_NAME = "Euronews Russian"
EURONEWS_QUERY = (
    'site:ru.euronews.com '
    '(Россия OR российские OR Путин OR Москва OR Кремль OR Украина OR Киев OR санкции OR война OR НАТО OR ЕС OR дипломатия OR удары OR БПЛА OR экономика)'
)

PREFERRED_SOURCES = {
    EURONEWS_NAME: 320,
    "Reuters": 170,
    "AP News": 150,
    "BBC World": 135,
    "Guardian World": 125,
    "BBC Technology": 90,
    "Guardian Technology": 80,
    "The Verge": 80,
    "Ars Technica": 75,
    "Sakhalin": 220,
}

SOURCE_PENALTY = {
    "Habr": -180,
    "GameSpot": -80,
    "IGN": -80,
    "PC Gamer": -80,
    "Eurogamer": -80,
}

BLOCKED_SOURCES = {"Interfax"}


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def canonical_source_name(value: str, url: str = "") -> str:
    s = norm(value + " " + (url or ""))
    if "interfax" in s or "интерфакс" in s:
        return "Interfax"
    if "euronews" in s or "евроньюс" in s:
        return EURONEWS_NAME
    if "reuters" in s:
        return "Reuters"
    if "apnews" in s or "ap news" in s or "associated press" in s:
        return "AP News"
    if "bbc" in s and "technology" in s:
        return "BBC Technology"
    if "bbc" in s:
        return "BBC World"
    if "guardian" in s and "technology" in s:
        return "Guardian Technology"
    if "guardian" in s:
        return "Guardian World"
    if "theverge" in s or "the verge" in s:
        return "The Verge"
    if "arstechnica" in s or "ars technica" in s:
        return "Ars Technica"
    if "habr" in s or "хабр" in s:
        return "Habr"
    if "gamespot" in s:
        return "GameSpot"
    if "ign" == s or " ign " in (" " + s + " "):
        return "IGN"
    if "pcgamer" in s or "pc gamer" in s:
        return "PC Gamer"
    if "eurogamer" in s:
        return "Eurogamer"
    if "sakhalin" in s or "сахалин" in s:
        return "Sakhalin"
    return str(value or "Источник")


def is_blocked_source_name(name: str, url: str = "") -> bool:
    return canonical_source_name(name, url) in BLOCKED_SOURCES


def remove_blocked_sources_and_add_euronews() -> None:
    sources = []
    for name, stype, rss in list(getattr(b, "SOURCES", []) or []):
        if is_blocked_source_name(str(name), str(rss)):
            continue
        sources.append((name, stype, rss))
    exists = any(name == EURONEWS_NAME or "euronews" in str(rss).lower() for name, _stype, rss in sources)
    if not exists:
        insert_at = 1 if sources else 0
        sources.insert(insert_at, (EURONEWS_NAME, "world", b.gnews(EURONEWS_QUERY, "ru", "RU")))
    b.SOURCES = sources


def source_adjusted_score(item: Dict) -> int:
    src = canonical_source_name(item.get("source") or "", item.get("url") or "")
    base = int(item.get("score") or 0)
    if src in BLOCKED_SOURCES:
        return 0
    score = base + PREFERRED_SOURCES.get(src, 0) + SOURCE_PENALTY.get(src, 0)
    if src == EURONEWS_NAME and item.get("category_hint") == "🌍 Мир о России":
        score += 160
    return max(1, score)


def recent_source_counts() -> Dict[str, int]:
    try:
        state = b.load_state()
    except Exception:
        state = {}
    counts: Dict[str, int] = {}
    for post in (state.get("last_posts", []) or [])[-9:]:
        src = canonical_source_name(post.get("source") or "", post.get("url") or "")
        counts[src] = counts.get(src, 0) + 1
    return counts


def source_soft_cap(src: str) -> int:
    if src in {"Habr", "GameSpot", "IGN", "PC Gamer", "Eurogamer"}:
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
            item["score"] = max(1, int(item.get("score") or 0) - 180)
        enriched.append(item)

    high_categories = {
        "🌍 Мир о России", "📍 Сахалин", "🇷🇺 РФ / война и безопасность",
        "🇷🇺 РФ / экономика", "🇷🇺 РФ / происшествия", "🇷🇺 РФ / законы и политика",
        "🌐 Мировые IT", "🎮 Игры / индустрия",
    }
    enriched.sort(key=lambda x: (x.get("category_hint") not in high_categories, -int(x.get("score") or 0)))

    ordered: List[Dict] = []
    used_sources = set()
    for item in enriched:
        src = canonical_source_name(item.get("source") or "", item.get("url") or "")
        if src in used_sources:
            continue
        ordered.append(item)
        used_sources.add(src)
    for item in enriched:
        if item not in ordered:
            ordered.append(item)
    return ordered


remove_blocked_sources_and_add_euronews()
b.select_order = select_order_v15


def main_v15() -> None:
    return v14.main_v14()


b.main = main_v15

if __name__ == "__main__":
    b.main()
