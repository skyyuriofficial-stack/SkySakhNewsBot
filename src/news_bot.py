import os
import re
import json
import html
import time
import hashlib
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
import feedparser


STATE_PATH = "state.json"
SAKHALIN_TZ = timezone(timedelta(hours=11))
POSTS_PER_RUN = 2
MAX_CANDIDATES_FOR_LLM = 28
MAX_ENTRIES_PER_SOURCE = 12

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"


def google_news_rss(query: str, lang: str = "en", country: str = "US") -> str:
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


SOURCES = [
    # Сахалин — отдельный приоритетный поток
    {
        "name": "Sakhalin Local / Google News",
        "type": "sakhalin",
        "url": google_news_rss(
            "Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Анива OR Невельск OR Оха "
            "ДТП OR пожар OR циклон OR шторм OR отключение OR происшествие OR землетрясение OR цунами",
            "ru",
            "RU",
        ),
        "weight": 98,
    },

    # Россия
    {
        "name": "Interfax",
        "type": "ru_general",
        "url": "https://www.interfax.ru/rss.asp",
        "weight": 78,
    },

    # Авторитетные мировые СМИ через Google News
    {
        "name": "Reuters / Google News",
        "type": "world_authority",
        "url": google_news_rss("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas"),
        "weight": 96,
    },
    {
        "name": "AP News / Google News",
        "type": "world_authority",
        "url": google_news_rss("site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas"),
        "weight": 94,
    },
    {
        "name": "BBC World",
        "type": "world_authority",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "weight": 86,
    },
    {
        "name": "The Guardian World",
        "type": "world_authority",
        "url": "https://www.theguardian.com/world/rss",
        "weight": 82,
    },

    # IT
    {
        "name": "BBC Technology",
        "type": "world_it",
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "weight": 80,
    },
    {
        "name": "The Guardian Technology",
        "type": "world_it",
        "url": "https://www.theguardian.com/technology/rss",
        "weight": 76,
    },
    {
        "name": "Habr",
        "type": "it_ru",
        "url": "https://habr.com/ru/rss/articles/",
        "weight": 48,
    },
]


SAKHALIN_GEO = [
    "сахалин", "южно-сахалинск", "сахалинская область", "холмск", "корсаков",
    "анива", "невельск", "оха", "долинск", "поронайск", "углегорск",
    "тымовское", "курил", "курильск", "южно-курильск",
]

SAKHALIN_IMPORTANT = [
    "дтп", "пожар", "погиб", "погибли", "пострадал", "пострадали",
    "шторм", "циклон", "ураган", "землетрясение", "цунами", "отключение",
    "авария", "эвакуация", "мчс", "мвд", "перекрытие", "дорог", "света",
    "воды", "тепла",
]

INCIDENT = [
    "дтп", "авария", "пожар", "погиб", "погибли", "ранен", "ранены",
    "пострадал", "пострадали", "эвакуация", "взрыв", "обрушение",
    "землетрясение", "цунами", "шторм", "циклон", "ураган",
    "killed", "dead", "explosion", "earthquake", "evacuation",
]

RU_POL = [
    "кремль", "песков", "путин", "лавров", "мишустин", "госдума", "мид",
    "минобороны", "правительство", "президент", "совбез", "законопроект",
    "kremlin", "putin", "lavrov", "moscow",
]

RU_ECO = [
    "цб", "центробанк", "ставка", "ключевая ставка", "инфляция", "рубль",
    "бюджет", "минфин", "банк", "нефть", "газ", "экономика", "санкц",
    "экспорт", "импорт", "oil", "gas", "ruble", "rouble", "central bank",
    "inflation", "budget", "economy", "sanction",
]

WORLD_RU = [
    "russia", "russian", "moscow", "kremlin", "россия", "рф", "российск",
    "москва", "кремль", "ukraine", "украина", "украин", "nato", "нато",
    "sanctions against russia", "санкции против россии", "санкции против рф",
    "russian assets", "russian oil", "russian gas", "российская нефть",
    "российский газ", "замороженные активы",
]

GEO = [
    "usa", "u.s.", "сша", "china", "китай", "iran", "иран", "israel",
    "израиль", "taiwan", "тайвань", "g7", "g20", "оон", "un ", "nato",
    "нато", "war", "война", "conflict", "конфликт", "sanction", "санкц",
    "election", "выборы", "oil", "нефть", "gas", "газ", "eu ", "ес ",
    "japan", "korea", "france", "germany", "britain",
]

IT_BIG = [
    "openai", "anthropic", "google", "microsoft", "apple", "meta", "nvidia",
    "ai", "artificial intelligence", "искусственный интеллект", "ии",
    "нейросет", "llm", "chip", "chips", "semiconductor", "чип", "процессор",
    "cyberattack", "кибератака", "data breach", "утечка", "telegram",
    "android", "ios", "robot", "робот", "cloud", "model", "модель",
]

IT_NOISE = [
    "геймдев", "шрифт", "собеседование", "личный опыт", "как мы сделали",
    "1с", "r-keeper", "ресторан", "игру", "игра", "менеджмент", "команда",
    "frontend", "backend", "c++", "javascript", "python",
]

LOW_RU = [
    "аэропорт", "самокат", "регламент", "спорт", "турнир", "матч",
    "выставка", "фестиваль", "конкурс", "рейтинг",
]

CATEGORY_ORDER = {
    "📍 Сахалин": 100,
    "🚨 ЧП / происшествия": 94,
    "🌍 Мир о России": 90,
    "🇷🇺 Россия / политика": 82,
    "🇷🇺 Россия / экономика": 80,
    "🇷🇺 Россия / внешняя политика": 78,
    "🧭 Геополитика": 72,
    "💻 IT / технологии": 66,
}


def log(message: str) -> None:
    now = datetime.now(SAKHALIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now} SAKH] {message}", flush=True)


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def term_matches(text: str, term: str) -> bool:
    text = (text or "").lower()
    term = (term or "").lower().strip()

    if not term:
        return False

    if " " in term or "-" in term:
        return term in text

    if len(term) <= 3:
        pattern = r"(?<![0-9a-zа-яё_])" + re.escape(term) + r"(?![0-9a-zа-яё_])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None

    return term in text


def hits(text: str, words: List[str]) -> List[str]:
    return [w for w in words if term_matches(text, w)]


def path_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).path.lower()
    except Exception:
        return ""


def title_hash(title: str) -> str:
    normalized = re.sub(r"[^0-9a-zа-яё]+", " ", (title or "").lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {"published_urls": [], "published_title_hashes": [], "last_posts": []}

    with open(STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("published_urls", [])
    data.setdefault("published_title_hashes", [])
    data.setdefault("last_posts", [])
    return data


def save_state(state: Dict[str, Any]) -> None:
    # Держим историю ограниченной, чтобы файл не раздувался.
    state["published_urls"] = state.get("published_urls", [])[-700:]
    state["published_title_hashes"] = state.get("published_title_hashes", [])[-700:]
    state["last_posts"] = state.get("last_posts", [])[-50:]
    state["last_run_sakhalin"] = datetime.now(SAKHALIN_TZ).isoformat(timespec="seconds")

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def local_classify(source: Dict[str, Any], title: str, summary: str, link: str) -> Tuple[Optional[str], int, str]:
    stype = source["type"]
    score = int(source["weight"])
    text = f"{title} {summary}".lower()
    p = path_of(link)

    sg = hits(text, SAKHALIN_GEO)
    si = hits(text, SAKHALIN_IMPORTANT)
    if stype == "sakhalin" or sg:
        score += 18
        reasons = ["сахалинский поток" if not sg else "география: " + ", ".join(sg[:3])]
        if si:
            score += 18
            reasons.append("важное локальное событие: " + ", ".join(si[:3]))
        return "📍 Сахалин", score, "; ".join(reasons)

    if stype in ("it_ru", "world_it"):
        big = hits(text, IT_BIG)
        noise = hits(text, IT_NOISE)
        if not big:
            return None, 0, "IT без крупного события"
        score += 15
        reasons = ["крупный IT-признак: " + ", ".join(big[:3])]
        if noise:
            score -= 25
            reasons.append("антишум: " + ", ".join(noise[:3]))
        return "💻 IT / технологии", score, "; ".join(reasons)

    if stype == "world_authority" or "/world/" in p:
        wr = hits(text, WORLD_RU)
        geo = hits(text, GEO)
        if wr:
            score += 20
            return "🌍 Мир о России", score, "мир о РФ/Украине/НАТО/санкциях: " + ", ".join(wr[:3])
        if geo:
            score += 8
            return "🧭 Геополитика", score, "геополитика: " + ", ".join(geo[:3])
        return None, 0, "мировая новость без нужной связи"

    if "/russia/" in p:
        inc = hits(text, INCIDENT)
        low = hits(text, LOW_RU)
        pol = hits(text, RU_POL)
        eco = hits(text, RU_ECO)
        wr = hits(text, WORLD_RU)

        if inc and not pol:
            score += 18
            return "🚨 ЧП / происшествия", score, "происшествие: " + ", ".join(inc[:3])
        if low and not pol and not eco and not wr:
            return None, 0, "низкая значимость: " + ", ".join(low[:3])
        if eco:
            score += 15
            return "🇷🇺 Россия / экономика", score, "экономика РФ: " + ", ".join(eco[:3])
        if pol:
            score += 15
            return "🇷🇺 Россия / политика", score, "политика РФ: " + ", ".join(pol[:3])
        if wr:
            score += 10
            return "🇷🇺 Россия / внешняя политика", score, "внешняя повестка РФ: " + ", ".join(wr[:3])
        return None, 0, "russia без сильного признака"

    if "/business/" in p:
        eco = hits(text, RU_ECO)
        geo = hits(text, GEO)
        if eco:
            score += 12
            return "🇷🇺 Россия / экономика", score, "экономика: " + ", ".join(eco[:3])
        if geo:
            score += 8
            return "🇷🇺 Россия / экономика", score, "внешнеэкономический контекст: " + ", ".join(geo[:3])
        return None, 0, "business без высокой значимости"

    return None, 0, "не подходит"


def collect_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    published_urls = set(state.get("published_urls", []))
    published_hashes = set(state.get("published_title_hashes", []))
    candidates: List[Dict[str, Any]] = []

    for source in SOURCES:
        log(f"Источник: {source['name']}")
        try:
            feed = feedparser.parse(source["url"])
        except Exception as exc:
            log(f"Ошибка источника {source['name']}: {exc}")
            continue

        for entry in feed.entries[:MAX_ENTRIES_PER_SOURCE]:
            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", ""))
            link = clean_text(entry.get("link", ""))

            if not title or not link:
                continue

            hsh = title_hash(title)
            if link in published_urls or hsh in published_hashes:
                continue

            category, score, reason = local_classify(source, title, summary, link)
            if not category or score < 70:
                continue

            candidates.append({
                "id": len(candidates) + 1,
                "source": source["name"],
                "source_type": source["type"],
                "category_hint": category,
                "score_hint": int(score),
                "reason_hint": reason,
                "title": title,
                "summary": summary[:600],
                "url": link,
                "title_hash": hsh,
            })

    candidates.sort(
        key=lambda x: (CATEGORY_ORDER.get(x["category_hint"], 0), x["score_hint"]),
        reverse=True,
    )

    return candidates[:MAX_CANDIDATES_FOR_LLM]


def build_llm_prompt(candidates: List[Dict[str, Any]]) -> str:
    compact = []
    for c in candidates:
        compact.append({
            "id": c["id"],
            "source": c["source"],
            "category_hint": c["category_hint"],
            "score_hint": c["score_hint"],
            "reason_hint": c["reason_hint"],
            "title": c["title"],
            "summary": c["summary"],
            "url": c["url"],
        })

    return (
        "Ты главный редактор автоматического Telegram-канала SkySakhNews.\n\n"
        "Канал публикует 2 новости за слот. Рубрики:\n"
        "1) 📍 Сахалин — ДТП, ЧП, пожары, погода, циклоны, отключения, важные локальные события.\n"
        "2) 🚨 ЧП / происшествия — реальные опасные события, жертвы, аварии, эвакуации.\n"
        "3) 🌍 Мир о России — как мир, США, ЕС, НАТО, G7, Китай и другие действуют/говорят о РФ, Украине, санкциях, нефти, газе, активах РФ.\n"
        "4) 🇷🇺 Россия / политика — федеральная политика РФ, Кремль, МИД, Госдума, Минобороны, решения власти.\n"
        "5) 🇷🇺 Россия / экономика — ЦБ, рубль, инфляция, бюджет, банки, нефть, газ, санкции, рынки.\n"
        "6) 🧭 Геополитика — крупные мировые конфликты, США-Китай, Иран, Израиль, Тайвань, G7/G20, энергетика.\n"
        "7) 💻 IT / технологии — только крупные события ИИ, OpenAI, Google, Microsoft, NVIDIA, чипы, кибератаки, утечки, Telegram/Android/iOS.\n\n"
        "Главный приоритет: Сахалин и локальные опасные события. Затем Мир о России. Затем политика/экономика РФ. Затем геополитика. Затем IT.\n\n"
        "Правила:\n"
        "- Выбери ровно 2 новости из списка.\n"
        "- Не выдумывай факты. Используй только title/summary/source.\n"
        "- Английские новости переведи на русский.\n"
        "- Пост должен быть на русском.\n"
        "- В каждом посте должно быть 4–6 содержательных строк в блоке «Кратко».\n"
        "- Не используй кликбейт и эмоциональную пропаганду.\n"
        "- Если новость слабая, не выбирай её.\n"
        "- Верни строго JSON-массив, без markdown.\n\n"
        "Формат JSON:\n"
        "[\n"
        "  {\n"
        "    \"id\": 1,\n"
        "    \"category\": \"🌍 Мир о России\",\n"
        "    \"title_ru\": \"...\",\n"
        "    \"post\": \"🌍 Мир о России\\n\\nЗаголовок\\n\\nКратко:\\n— строка 1\\n— строка 2\\n— строка 3\\n— строка 4\\n\\nПочему важно:\\n1–2 строки.\\n\\nИсточник:\\nURL\",\n"
        "    \"selection_reason\": \"коротко почему выбрана\"\n"
        "  }\n"
        "]\n\n"
        "Кандидаты:\n"
        f"{json.dumps(compact, ensure_ascii=False)}"
    )


def call_openrouter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")

    model = os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Ты строгий редактор новостного Telegram-канала. Возвращай только валидный JSON."
            },
            {
                "role": "user",
                "content": build_llm_prompt(candidates)
            }
        ],
        "temperature": 0.2,
        "max_tokens": 2200,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SkySakhNews",
        "X-OpenRouter-Title": "SkySakhNews",
    }

    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=90)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {response.text[:1000]}")

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    return parse_json_array(content)


def parse_json_array(text: str) -> List[Dict[str, Any]]:
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    start = text.find("[")
    end = text.rfind("]")

    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"Model did not return JSON array: {text[:1000]}")

    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, list):
        raise RuntimeError("Parsed JSON is not a list")

    return parsed


def fallback_select(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chosen = candidates[:POSTS_PER_RUN]
    result = []

    for c in chosen:
        category = c["category_hint"]
        title = c["title"]
        url = c["url"]
        source = c["source"]

        post = (
            f"{category}\n\n"
            f"{title}\n\n"
            "Кратко:\n"
            f"— Новость отобрана автоматическим фильтром по теме канала.\n"
            f"— Источник сообщения: {source}.\n"
            f"— Предварительная категория: {category}.\n"
            f"— Система отметила событие как значимое по редакционным признакам.\n\n"
            "Почему важно:\n"
            "Событие относится к приоритетной повестке канала: Сахалин, Россия, мир о России, геополитика или крупные технологии.\n\n"
            f"Источник:\n{url}"
        )

        result.append({
            "id": c["id"],
            "category": category,
            "title_ru": title,
            "post": post,
            "selection_reason": "fallback без LLM",
        })

    return result


def send_telegram(text: str) -> Dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is missing")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    response = requests.post(url, data=payload, timeout=45)
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram HTTP {response.status_code}: {response.text[:1000]}")

    return response.json()


def normalize_post(post: str, candidate_url: str) -> str:
    post = clean_text(post).replace("\\n", "\n")
    # После clean_text переносы могут схлопнуться; если модель дала нормальный текст, оставляем как есть.
    # Если URL не попал в пост, добавляем.
    if candidate_url and candidate_url not in post:
        post = post.rstrip() + f"\n\nИсточник:\n{candidate_url}"

    if len(post) > 3900:
        post = post[:3800].rstrip() + f"\n\nИсточник:\n{candidate_url}"

    return post


def main() -> None:
    state = load_state()

    log("Сбор кандидатов")
    candidates = collect_candidates(state)
    log(f"Кандидатов после локального фильтра: {len(candidates)}")

    if not candidates:
        log("Нет кандидатов для публикации")
        save_state(state)
        return

    try:
        selected = call_openrouter(candidates)
        log(f"OpenRouter выбрал новостей: {len(selected)}")
    except Exception as exc:
        log(f"OpenRouter недоступен, fallback: {exc}")
        selected = fallback_select(candidates)

    by_id = {c["id"]: c for c in candidates}
    published_count = 0

    for item in selected[:POSTS_PER_RUN]:
        try:
            cid = int(item.get("id"))
        except Exception:
            continue

        cand = by_id.get(cid)
        if not cand:
            continue

        if cand["url"] in state.get("published_urls", []):
            continue

        post = normalize_post(str(item.get("post", "")), cand["url"])

        if not post or len(post) < 120:
            continue

        log(f"Публикация: {cand['source']} | {cand['title'][:80]}")
        result = send_telegram(post)

        if result.get("ok"):
            state.setdefault("published_urls", []).append(cand["url"])
            state.setdefault("published_title_hashes", []).append(cand["title_hash"])
            state.setdefault("last_posts", []).append({
                "time_sakhalin": datetime.now(SAKHALIN_TZ).isoformat(timespec="seconds"),
                "source": cand["source"],
                "category": item.get("category") or cand["category_hint"],
                "title": item.get("title_ru") or cand["title"],
                "url": cand["url"],
            })
            published_count += 1
            time.sleep(15)

    log(f"Опубликовано: {published_count}")
    save_state(state)


if __name__ == "__main__":
    main()
