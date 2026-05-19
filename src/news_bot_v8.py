# v8: topic overlay for v7.
# Adds loud world IT and gaming news back into the editorial grid without weakening
# Sakhalin / Russia-war-economy-law filters.

import urllib.parse
import news_bot_v7 as b

b.FOOTER.update({
    "🌐 Мировые IT": "МИРОВЫЕ IT",
    "🎮 Игры / индустрия": "ИГРОВАЯ ИНДУСТРИЯ",
})

IT_HARD = "openai chatgpt gpt gemini google anthropic claude microsoft apple meta nvidia amd intel spacex tesla x ai grok deepseek neuralink tsmc samsung chip chips semiconductor ai ии нейросеть нейросети искусственный интеллект кибератака хакер взлом утечка данных персональные данные cyberattack hack hacker breach data leak privacy spyware ransomware".split()

GAMING = "game games gaming gamer videogame videogames xbox playstation ps5 ps6 nintendo switch steam valve epic ubisoft ea electronic arts rockstar gta gta6 grand theft auto take-two bethesda activision blizzard microsoft sony cd projekt cyberpunk witcher stalker stalker2 warhammer elden ring fromsoftware kojima nvidia geforce rtx unreal engine unity геймдев игра игры игровая геймеры гейминг xbox playstation плейстейшен нинтендо стим valve эпик юбисофт рокстар гта gta6 сталкер киберпанк ведьмак разработчики релиз трейлер консоль консоли".split()

# Более точечные источники по мировым IT и играм. Google News часто отдаёт картинки через исходные сайты.
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
    if source_type == "gaming" or b.has_terms(text, GAMING):
        if b.has_terms(text, b.GENERIC_RU_NOISE):
            return None, 0
        score = 112
        if b.has_terms(text, "gta gta6 rockstar sony microsoft xbox playstation nintendo steam valve nvidia unreal engine stalker cyberpunk witcher activision blizzard bethesda релиз трейлер консоль".split()):
            score += 35
        return "🎮 Игры / индустрия", score
    if source_type == "it":
        if b.has_terms(text, IT_HARD):
            score = 108
            if b.has_terms(text, "openai chatgpt gpt google microsoft apple meta nvidia deepseek кибератака взлом утечка ai ии нейросеть".split()):
                score += 35
            return "🌐 Мировые IT", score
        return None, 0
    return _old_classify(source_type, title, rss_text, page_desc, url)

b.classify = classify


def select_order(items):
    # Приоритет выпуска:
    # 1) Мир о России / РФ война-экономика-законы.
    # 2) Сахалин.
    # 3) Громкое мировое IT / игры.
    # Если в первых двух слотах нет сильного кандидата — IT/игры получают место.
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

    # Чтобы IT/игры не пропадали полностью: если главных политических новостей много,
    # они идут следующими в очереди, а не выкидываются.
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
