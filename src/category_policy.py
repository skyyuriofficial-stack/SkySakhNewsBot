# Shared semantic category policy for SkySakhNews.
# Centralizes category override to avoid drift between editorial_review, final_guard and publisher.

import re
from typing import Dict

CATEGORY_SAKHALIN = "📍 Сахалин"
CATEGORY_GAMES = "🎮 Игры / индустрия"
CATEGORY_IT = "🌐 Мировые IT"
CATEGORY_WAR = "🇷🇺 РФ / война и безопасность"
CATEGORY_ECONOMY = "🇷🇺 РФ / экономика"
CATEGORY_INCIDENTS = "🇷🇺 РФ / происшествия"
CATEGORY_GEOPOLITICS = "🧭 Геополитика"
CATEGORY_WORLD_RUSSIA = "🌍 Мир о России"
CATEGORY_POLITICS = "🇷🇺 РФ / законы и политика"

SAKHALIN_WORDS = {
    "сахалин", "южно-сахалинск", "корсаков", "холмск", "курил", "курильск",
    "оха", "долинск", "поронайск", "углегорск", "анива", "невельск",
    "тымовск", "томари", "смирных", "александровск-сахалинский", "сахалинская область"
}

GAME_WORDS = {
    "игра", "игры", "геймдев", "game", "games", "gaming", "gamer", "steam", "epic games",
    "playstation", "xbox", "nintendo", "switch", "sony interactive", "ubisoft", "electronic arts",
    "activision", "blizzard", "bethesda", "riot games", "valve", "rockstar", "cd projekt", "sega",
    "trailer", "dlc", "remake", "remaster", "early access", "patch", "witcher", "cyberpunk",
    "gta", "call of duty", "dota", "cs2", "game pass"
}

# Important: no generic Cyrillic "ии" marker. It appears inside "России" and causes false IT positives.
IT_WORDS = {
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini", "google ai", "microsoft ai",
    "windows", "linux", "android", "ios", "apple intelligence", "meta ai", "aws", "azure", "github",
    "gitlab", "nvidia", "amd", "intel", "qualcomm", "tesla ai", "ai ", " ai", "нейросеть",
    "нейросети", "искусственный интеллект", "llm", "machine learning", "python", "javascript",
    "typescript", "react", "node.js", "nodejs", "database", "sql", "postgres", "mongodb",
    "api", "sdk", "cloud", "кибератака", "cyber", "cybersecurity", "security vulnerability",
    "cve", "уязвимость", "эксплойт", "веб-приложение", "gpu", "cpu", "server", "data center",
    "semiconductor", "chip", "software", "firmware", "дата-центр", "сервер", "чип"
}

POLITICS_BLOCK_IT = {
    "путин", "трамп", "байден", "си цзиньпин", "пашинян", "макрон", "зеленский",
    "ереван", "армения", "китай", "россия", "украина", "сша", "евросоюз", "ес",
    "нато", "оон", "саммит", "переговоры", "визит", "санкции", "министерство",
    "посол", "президент", "премьер", "глава государства", "резолюция", "антироссийский",
    "антироссийская", "геополитика", "внешняя политика", "мид", "дипломат"
}

GEO_WORDS = {
    "армения", "ереван", "азербайджан", "иран", "израиль", "китай", "сша", "евросоюз",
    "ес", "нато", "оон", "g7", "g20", "саммит", "переговоры", "визит", "санкции",
    "посол", "премьер", "президент", "лидер", "дипломатия", "международный", "внешняя политика",
    "геополитика", "резолюция", "антироссийская кампания", "антироссийские действия",
    "постсоветское", "грузия", "молдавия", "молдова", "куба", "тайван", "газа"
}

WORLD_ABOUT_RUSSIA_WORDS = {
    "россия", "рф", "путин", "санкции против россии", "отношения с россией", "антироссийский",
    "антироссийская", "российский", "российская экономика", "российская нефть", "российский экспорт",
    "российский газ", "российские власти", "москва", "кремль"
}

RU_WAR_WORDS = {
    "дрон", "дроны", "бпла", "беспилотник", "атака", "обстрел", "ракет", "пво",
    "минобороны", "военные", "удар", "всу", "фронт", "боеприпас", "войска", "ранен",
    "ранения", "разрушения", "пожар после атаки", "с-400", "диверсия", "теракт", "заэс", "аэс"
}

RU_ECON_WORDS = {
    "экономика", "нефть", "газ", "спг", "банк", "кредит", "рубль", "экспорт", "импорт",
    "поставки", "россельхозбанк", "финансирование", "доход", "инвестиции", "бюджет",
    "налог", "производство", "промышленность", "зерно", "сельхоз", "ставка", "цб"
}

RU_INCIDENT_WORDS = {
    "дтп", "авария", "пожар", "столкновение", "взрыв", "пострадал", "пострадали",
    "погиб", "погибли", "происшествие", "чп", "убийство", "грабеж", "мошенники",
    "без воды", "без света", "водопровод", "мчс", "криминал"
}

RU_POLITICS_WORDS = {
    "госдума", "закон", "законопроект", "сенат", "совет федерации", "правительство",
    "министерство", "кремль", "песков", "володин", "депутат", "комитет"
}


def norm_text(*parts: str) -> str:
    text = " ".join(str(p or "") for p in parts if p is not None)
    text = text.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def has_any(text: str, words) -> bool:
    return any(w in text for w in words)


def count_hits(text: str, words) -> int:
    return sum(1 for w in words if w in text)


def is_it(text: str) -> bool:
    it_hits = count_hits(text, IT_WORDS)
    block_hits = count_hits(text, POLITICS_BLOCK_IT)
    if block_hits >= 1 and it_hits < 3:
        return False
    return it_hits >= 2


def resolve_final_category(current_category: str = "", title: str = "", summary: str = "", source_name: str = "", source_url: str = "") -> str:
    text = norm_text(title, summary, source_name, source_url)

    if count_hits(text, SAKHALIN_WORDS) >= 1:
        return CATEGORY_SAKHALIN

    if count_hits(text, GAME_WORDS) >= 2:
        return CATEGORY_GAMES

    # Geopolitics must be evaluated before IT to prevent false IT categories for Russia/Armenia/etc.
    if count_hits(text, GEO_WORDS) >= 2:
        return CATEGORY_GEOPOLITICS

    if is_it(text):
        return CATEGORY_IT

    if count_hits(text, RU_WAR_WORDS) >= 2:
        return CATEGORY_WAR

    # Incidents before economy: "авария на водопроводе" contains infrastructure words, but it is incident.
    if count_hits(text, RU_INCIDENT_WORDS) >= 2:
        return CATEGORY_INCIDENTS

    if count_hits(text, RU_ECON_WORDS) >= 2:
        return CATEGORY_ECONOMY

    if count_hits(text, RU_POLITICS_WORDS) >= 2:
        return CATEGORY_POLITICS

    if count_hits(text, WORLD_ABOUT_RUSSIA_WORDS) >= 1:
        return CATEGORY_WORLD_RUSSIA

    return current_category or CATEGORY_GEOPOLITICS


def resolve_final_category_from_item(item: Dict) -> str:
    return resolve_final_category(
        current_category=item.get("category") or item.get("category_hint") or "",
        title=item.get("title_ru") or item.get("title_original") or item.get("title") or "",
        summary=" ".join([
            str(item.get("source_text") or ""),
            str(item.get("summary") or ""),
            " ".join(str(x) for x in (item.get("body") or [])),
            str(item.get("post_text") or ""),
            str(item.get("edited_post_text") or ""),
        ]),
        source_name=item.get("source") or "",
        source_url=item.get("url") or "",
    )
