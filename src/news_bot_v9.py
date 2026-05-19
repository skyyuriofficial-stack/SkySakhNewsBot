# v9: stable overlay over v7.
# Fixes:
# - v7 compatibility bug: RU_WORLD missing in some saved versions.
# - false gaming matches from tiny tokens like "ea" / "ai" inside normal English words.
# - keeps the required streams: world about Russia, Sakhalin, RF war/economy/laws,
#   world IT, loud gaming news.

import re
import news_bot_v7 as b

# Compatibility patch for older v7 file where the list was named WORLD_RU.
if not hasattr(b, "RU_WORLD"):
    b.RU_WORLD = getattr(b, "WORLD_RU", [])

b.FOOTER.update({
    "🌐 Мировые IT": "МИРОВЫЕ IT",
    "🎮 Игры / индустрия": "ИГРОВАЯ ИНДУСТРИЯ",
})

IT_HARD = [
    "openai", "chatgpt", "gpt", "gemini", "google", "anthropic", "claude",
    "microsoft", "apple", "meta", "nvidia", "amd", "intel", "spacex", "tesla",
    "grok", "deepseek", "neuralink", "tsmc", "samsung", "chip", "chips",
    "semiconductor", "cyberattack", "hack", "hacker", "breach", "data leak",
    "privacy", "spyware", "ransomware", "artificial intelligence",
    "ии", "нейросеть", "нейросети", "искусственный интеллект", "кибератака",
    "хакер", "взлом", "утечка", "данных", "персональные данные", "чип", "чипы",
]

GAMING = [
    "game", "games", "gaming", "gamer", "videogame", "videogames", "xbox",
    "playstation", "ps5", "ps6", "nintendo", "switch", "steam", "valve", "epic games",
    "ubisoft", "electronic arts", "rockstar", "gta", "gta 6", "gta6", "grand theft auto",
    "take-two", "bethesda", "activision", "blizzard", "sony", "cd projekt", "cyberpunk",
    "witcher", "stalker", "stalker 2", "warhammer", "elden ring", "fromsoftware",
    "kojima", "geforce", "rtx", "unreal engine", "unity",
    "геймдев", "игра", "игры", "игровая", "геймер", "геймеры", "гейминг",
    "плейстейшен", "нинтендо", "стим", "рокстар", "гта", "сталкер",
    "киберпанк", "ведьмак", "разработчики", "релиз", "трейлер", "консоль", "консоли",
]

GAMING_STRONG = [
    "gta", "gta 6", "gta6", "rockstar", "sony", "microsoft", "xbox", "playstation",
    "nintendo", "steam", "valve", "nvidia", "unreal engine", "stalker", "cyberpunk",
    "witcher", "activision", "blizzard", "bethesda", "релиз", "трейлер", "консоль",
    "гта", "рокстар", "сталкер", "киберпанк", "ведьмак",
]

IT_STRONG = [
    "openai", "chatgpt", "gpt", "gemini", "google", "microsoft", "apple", "meta",
    "nvidia", "deepseek", "cyberattack", "hack", "breach", "data leak",
    "кибератака", "взлом", "утечка", "ии", "нейросеть",
]


def term_hits(text, terms):
    """Safer term matcher. Short Latin tokens must be whole words, not substrings."""
    raw = (text or "").lower()
    hits = []
    for term in terms:
        t = term.lower().strip()
        if not t:
            continue
        # Multi-word phrase: plain substring is intended.
        if " " in t or "-" in t:
            if t in raw:
                hits.append(term)
            continue
        # Latin short token must be a whole token. Prevents 'ea' in 'fear', 'ai' in 'said'.
        if re.fullmatch(r"[a-z0-9]{1,3}", t):
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw):
                hits.append(term)
            continue
        # Normal terms: word boundary for Latin, substring for Russian stems.
        if re.fullmatch(r"[a-z0-9]+", t):
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw):
                hits.append(term)
        else:
            if t in raw:
                hits.append(term)
    return hits


b.SOURCES = [
    ("Sakhalin", "sakhalin", b.gnews("Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Курилы ДТП OR пожар OR происшествие OR землетрясение OR шторм OR авария OR розыск OR отключение OR задержали OR суд", "ru", "RU")),
    ("Interfax", "ru", "https://www.interfax.ru/rss.asp"),
    ("Reuters", "world", b.gnews("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas drone missile war economy")),
    ("AP News", "world", b.gnews("site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas Iran Israel drone missile war")),
    ("BBC World", "world", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Guardian World", "world", "https://www.theguardian.com/world/rss"),
    ("BBC Technology", "it", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("Guardian Technology", "it", "https://www.theguardian.com/technology/rss"),
    ("The Verge", "it", "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica", "it", "https://feeds.arstechnica.com/arstechnica/index"),
    ("Habr", "it", "https://habr.com/ru/rss/articles/"),
    ("GameSpot", "gaming", "https://www.gamespot.com/feeds/mashup/"),
    ("IGN", "gaming", "https://feeds.feedburner.com/ign/all"),
    ("PC Gamer", "gaming", "https://www.pcgamer.com/rss/"),
    ("Eurogamer", "gaming", "https://www.eurogamer.net/feed/news"),
]

_old_classify = b.classify


def classify(source_type, title, rss_text, page_desc, url):
    text = f"{title} {rss_text} {page_desc}".lower()

    if source_type == "gaming" or term_hits(text, GAMING):
        # Gaming is allowed only for actual gaming/industry vocabulary, not accidental substrings.
        score = 112
        if term_hits(text, GAMING_STRONG):
            score += 35
        return "🎮 Игры / индустрия", score

    if source_type == "it":
        if term_hits(text, IT_HARD):
            score = 108
            if term_hits(text, IT_STRONG):
                score += 35
            return "🌐 Мировые IT", score
        return None, 0

    return _old_classify(source_type, title, rss_text, page_desc, url)


b.classify = classify


def select_order(items):
    main = [x for x in items if x["category_hint"] in (
        "🌍 Мир о России",
        "🇷🇺 РФ / война и безопасность",
        "🇷🇺 РФ / экономика",
        "🇷🇺 РФ / законы и политика",
    )]
    local = [x for x in items if x["category_hint"] == "📍 Сахалин"]
    tech_game = [x for x in items if x["category_hint"] in ("🌐 Мировые IT", "🎮 Игры / индустрия")]

    ordered = []
    if main:
        ordered.append(main[0])
    if local:
        ordered.append(local[0])
    if len(ordered) < 2 and tech_game:
        ordered.append(tech_game[0])

    for item in tech_game + main + local + items:
        if item not in ordered:
            ordered.append(item)
    return ordered


b.select_order = select_order

_old_prompt_write = b.prompt_write


def prompt_write(item, error=""):
    if item.get("category_hint") in ("🌐 Мировые IT", "🎮 Игры / индустрия"):
        return (
            "Сделай короткий новостной пост для Telegram строго на русском языке.\n"
            "Тематика: громкие мировые IT и игровые новости: OpenAI, Google, Microsoft, Apple, NVIDIA, кибератаки, утечки, консоли, GTA, Steam, Xbox, PlayStation, крупные игровые релизы и сделки.\n\n"
            "Правила:\n"
            "1) Только факты из title/source_text. Ничего не добавляй.\n"
            "2) Английский текст переведи на русский. Английские предложения запрещены.\n"
            "3) 2-3 абзаца, каждый 1-2 предложения.\n"
            "4) Не используй списки, 'Суть', 'Источник', 'Что известно'.\n"
            "5) Заголовок конкретный. Не общий шаблон.\n"
            "6) Если новость мелкая, обзорная, рекламная или без явного инфоповода — reject=true.\n"
            f"Ошибка предыдущей попытки: {error}\n\n"
            "Формат строго JSON: {\"reject\":false,\"title_ru\":\"...\",\"body\":[\"абзац\",\"абзац\"],\"footer\":\"...\"}\n\n"
            "Данные:\n" + b.json.dumps({"category": item["category_hint"], "footer": b.FOOTER.get(item["category_hint"], "НОВОСТИ"), "source": item["source"], "title": item["title"], "source_text": item["summary"], "published_at": item["published_at"]}, ensure_ascii=False)
        )
    return _old_prompt_write(item, error)


b.prompt_write = prompt_write

if __name__ == "__main__":
    b.main()
