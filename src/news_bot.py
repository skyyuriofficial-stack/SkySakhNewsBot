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
REQUEST_TIMEOUT = 35

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"


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

HASHTAG_MAP = {
    "📍 Сахалин": ["#Сахалин", "#ЮжноСахалинск"],
    "🚨 ЧП / происшествия": ["#ЧП", "#Происшествия"],
    "🌍 Мир о России": ["#Россия", "#МирОРоссии", "#Геополитика"],
    "🇷🇺 Россия / политика": ["#Россия", "#Политика"],
    "🇷🇺 Россия / экономика": ["#Россия", "#Экономика"],
    "🇷🇺 Россия / внешняя политика": ["#Россия", "#ВнешняяПолитика"],
    "🧭 Геополитика": ["#Геополитика", "#Мир"],
    "💻 IT / технологии": ["#IT", "#Технологии"],
}


def google_news_rss(query: str, lang: str = "en", country: str = "US") -> str:
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


SOURCES = [
    {
        "name": "Sakhalin Google News",
        "type": "sakhalin",
        "url": google_news_rss(
            "Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Анива OR Невельск OR Оха "
            "ДТП OR пожар OR циклон OR шторм OR отключение OR происшествие OR землетрясение OR цунами",
            "ru",
            "RU",
        ),
        "weight": 98,
    },
    {
        "name": "Interfax",
        "type": "ru_general",
        "url": "https://www.interfax.ru/rss.asp",
        "weight": 78,
    },
    {
        "name": "Reuters",
        "type": "world_authority",
        "url": google_news_rss("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas"),
        "weight": 96,
    },
    {
        "name": "AP News",
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


def log(message: str) -> None:
    now = datetime.now(SAKHALIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now} SAKH] {message}", flush=True)


def clean_inline(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def escape_html(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def normalize_image_url(url: str, base_url: str = "") -> Optional[str]:
    if not url:
        return None
    url = html.unescape(str(url).strip())
    if url.startswith("//"):
        url = "https:" + url
    if base_url and url.startswith("/"):
        url = urllib.parse.urljoin(base_url, url)
    if not url.startswith(("http://", "https://")):
        return None
    return url


def extract_source_name(entry: Any, fallback: str) -> str:
    source = entry.get("source")
    if isinstance(source, dict) and source.get("title"):
        return clean_inline(source.get("title"))
    try:
        if getattr(source, "title", None):
            return clean_inline(source.title)
    except Exception:
        pass
    return fallback.replace(" / Google News", "")


def extract_image_url(entry: Any, summary_raw: str, link: str) -> Optional[str]:
    for key in ("media_thumbnail", "media_content"):
        media = entry.get(key)
        if isinstance(media, list):
            for m in media:
                if isinstance(m, dict) and m.get("url"):
                    img = normalize_image_url(str(m["url"]), link)
                    if img:
                        return img

    links = entry.get("links")
    if isinstance(links, list):
        for item in links:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href", ""))
            typ = str(item.get("type", ""))
            rel = str(item.get("rel", ""))
            if href and ("image" in typ or rel in ("enclosure", "thumbnail")):
                img = normalize_image_url(href, link)
                if img:
                    return img

    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary_raw or "", flags=re.I)
    if m:
        return normalize_image_url(m.group(1), link)

    return None


def fetch_og_image(url: str) -> Optional[str]:
    if not url or "news.google.com" in url:
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code >= 400:
            return None
        text = r.text[:500000]
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        ]
        for p in patterns:
            m = re.search(p, text, flags=re.I)
            if m:
                return normalize_image_url(m.group(1), url)
    except Exception:
        return None
    return None


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
    state["published_urls"] = state.get("published_urls", [])[-900:]
    state["published_title_hashes"] = state.get("published_title_hashes", [])[-900:]
    state["last_posts"] = state.get("last_posts", [])[-80:]
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
            title = clean_inline(entry.get("title", ""))
            summary_raw = str(entry.get("summary", "") or "")
            summary = clean_inline(summary_raw)
            link = clean_inline(entry.get("link", ""))
            if not title or not link:
                continue

            hsh = title_hash(title)
            if link in published_urls or hsh in published_hashes:
                continue

            category, score, reason = local_classify(source, title, summary, link)
            if not category or score < 70:
                continue

            source_name = extract_source_name(entry, source["name"])
            image_url = extract_image_url(entry, summary_raw, link)

            candidates.append({
                "id": len(candidates) + 1,
                "source": source_name,
                "source_group": source["name"],
                "source_type": source["type"],
                "category_hint": category,
                "score_hint": int(score),
                "reason_hint": reason,
                "title": title,
                "summary": summary[:650],
                "url": link,
                "image_url": image_url,
                "title_hash": hsh,
            })

    candidates.sort(key=lambda x: (CATEGORY_ORDER.get(x["category_hint"], 0), x["score_hint"]), reverse=True)
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
        "Нужно выбрать ровно 2 лучшие новости для публикации.\n\n"
        "Приоритеты:\n"
        "1) 📍 Сахалин — ДТП, ЧП, пожары, погода, циклоны, отключения, важные локальные события.\n"
        "2) 🚨 ЧП / происшествия — реальные опасные события, жертвы, аварии, эвакуации.\n"
        "3) 🌍 Мир о России — как мир, США, ЕС, НАТО, G7, Китай и другие действуют/говорят о РФ, Украине, санкциях, нефти, газе, активах РФ.\n"
        "4) 🇷🇺 Россия / политика.\n"
        "5) 🇷🇺 Россия / экономика.\n"
        "6) 🧭 Геополитика.\n"
        "7) 💻 IT / технологии — только крупные события ИИ, чипов, кибератак, крупных платформ.\n\n"
        "Стиль поста:\n"
        "- русский язык;\n"
        "- деловой, живой, не канцелярский;\n"
        "- без кликбейта;\n"
        "- не выдумывать факты сверх title/summary/source;\n"
        "- brief должен быть 4–5 строк, каждая строка отдельная мысль;\n"
        "- why_important: 1 короткое предложение;\n"
        "- hashtags: 2–4 русских хэштега без пробелов.\n\n"
        "Верни строго JSON-массив без markdown:\n"
        "[\n"
        "  {\n"
        "    \"id\": 1,\n"
        "    \"category\": \"📍 Сахалин\",\n"
        "    \"title_ru\": \"Короткий ясный заголовок\",\n"
        "    \"brief\": [\"строка 1\", \"строка 2\", \"строка 3\", \"строка 4\"],\n"
        "    \"why_important\": \"Почему это важно одним предложением.\",\n"
        "    \"hashtags\": [\"#Сахалин\", \"#ЧП\"],\n"
        "    \"selection_reason\": \"коротко почему выбрана\"\n"
        "  }\n"
        "]\n\n"
        f"Кандидаты:\n{json.dumps(compact, ensure_ascii=False)}"
    )


def call_openrouter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    model = os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты строгий редактор новостного Telegram-канала. Возвращай только валидный JSON."},
            {"role": "user", "content": build_llm_prompt(candidates)},
        ],
        "temperature": 0.25,
        "max_tokens": 1800,
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
    return parse_json_array(data["choices"][0]["message"]["content"])


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
    result = []
    for c in candidates[:POSTS_PER_RUN]:
        category = c["category_hint"]
        result.append({
            "id": c["id"],
            "category": category,
            "title_ru": c["title"],
            "brief": [
                "Новость отобрана автоматическим фильтром по теме канала.",
                f"Источник сообщения: {c['source']}.",
                f"Предварительная категория: {category}.",
                "Система отметила событие как значимое по редакционным признакам.",
            ],
            "why_important": "Событие относится к приоритетной повестке канала.",
            "hashtags": HASHTAG_MAP.get(category, ["#Новости"]),
            "selection_reason": "fallback без LLM",
        })
    return result


def prepare_brief_lines(value: Any) -> List[str]:
    if isinstance(value, list):
        lines = [clean_inline(x) for x in value if clean_inline(x)]
    else:
        text = clean_inline(value)
        parts = re.split(r"[;\n]+|(?<=[.!?])\s+", text)
        lines = [clean_inline(x) for x in parts if clean_inline(x)]

    result = []
    seen = set()
    for line in lines:
        line = line.strip("—-• ")
        if not line or line.lower() in seen:
            continue
        seen.add(line.lower())
        result.append(line)
        if len(result) >= 5:
            break
    while len(result) < 4:
        result.append("Подробности будут уточняться по мере появления новых сообщений от источников.")
    return result[:5]


def make_hashtags(category: str, model_tags: Any) -> str:
    tags = []
    if isinstance(model_tags, list):
        tags.extend(str(t).strip() for t in model_tags if str(t).strip())
    tags.extend(HASHTAG_MAP.get(category, ["#Новости"]))

    clean_tags = []
    seen = set()
    for tag in tags:
        tag = tag.replace(" ", "")
        if not tag.startswith("#"):
            tag = "#" + tag
        tag = re.sub(r"[^#A-Za-zА-Яа-яЁё0-9_]", "", tag)
        if len(tag) < 2:
            continue
        low = tag.lower()
        if low in seen:
            continue
        seen.add(low)
        clean_tags.append(tag)
        if len(clean_tags) >= 4:
            break
    return " ".join(clean_tags)


def build_pretty_caption(item: Dict[str, Any], cand: Dict[str, Any], max_len: int = 980) -> str:
    category = clean_inline(item.get("category") or cand["category_hint"])
    title = clean_inline(item.get("title_ru") or cand["title"])
    brief = prepare_brief_lines(item.get("brief") or cand.get("summary") or "")
    why = clean_inline(item.get("why_important") or "Событие относится к приоритетной повестке канала.")
    hashtags = make_hashtags(category, item.get("hashtags"))
    source = clean_inline(cand.get("source") or cand.get("source_group") or "Источник")
    url = cand["url"]

    def render(lines: List[str]) -> str:
        bullets = "\n".join(f"• {escape_html(x)}" for x in lines)
        return (
            f"{escape_html(category)}\n\n"
            f"<b>{escape_html(title)}</b>\n\n"
            f"<b>Кратко:</b>\n{bullets}\n\n"
            f"<b>Почему важно:</b>\n{escape_html(why)}\n\n"
            f"<a href=\"{escape_html(url)}\">Источник: {escape_html(source)}</a>\n"
            f"{escape_html(hashtags)}"
        )

    caption = render(brief)
    while len(caption) > max_len and len(brief) > 4:
        brief = brief[:-1]
        caption = render(brief)
    if len(caption) > max_len:
        short = []
        for line in brief:
            short.append(line[:142].rstrip() + "…" if len(line) > 145 else line)
        caption = render(short)
    if len(caption) > max_len:
        caption = (
            f"{escape_html(category)}\n\n"
            f"<b>{escape_html(title[:220])}</b>\n\n"
            f"<b>Кратко:</b>\n"
            f"• {escape_html(brief[0][:180])}\n"
            f"• {escape_html(brief[1][:180])}\n"
            f"• {escape_html(brief[2][:180])}\n"
            f"• {escape_html(brief[3][:180])}\n\n"
            f"<a href=\"{escape_html(url)}\">Источник: {escape_html(source)}</a>\n"
            f"{escape_html(hashtags)}"
        )
    return caption[:max_len]


def send_telegram_message(text: str) -> Dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is missing")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    response = requests.post(url, data=payload, timeout=45)
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram sendMessage HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


def send_telegram_photo(photo_url: str, caption: str) -> Dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is missing")
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"}
    response = requests.post(url, data=payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram sendPhoto HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


def publish_item(item: Dict[str, Any], cand: Dict[str, Any]) -> Dict[str, Any]:
    caption = build_pretty_caption(item, cand)
    image_url = cand.get("image_url") or fetch_og_image(cand.get("url", ""))
    if image_url:
        try:
            log(f"Публикуем с картинкой: {image_url[:90]}")
            return send_telegram_photo(image_url, caption)
        except Exception as exc:
            log(f"Картинка не отправилась, fallback на текст: {exc}")
    return send_telegram_message(caption)


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

        log(f"Публикация: {cand['source']} | {cand['title'][:80]}")
        result = publish_item(item, cand)
        if result.get("ok"):
            state.setdefault("published_urls", []).append(cand["url"])
            state.setdefault("published_title_hashes", []).append(cand["title_hash"])
            state.setdefault("last_posts", []).append({
                "time_sakhalin": datetime.now(SAKHALIN_TZ).isoformat(timespec="seconds"),
                "source": cand["source"],
                "category": item.get("category") or cand["category_hint"],
                "title": item.get("title_ru") or cand["title"],
                "url": cand["url"],
                "with_image": bool(cand.get("image_url")),
            })
            published_count += 1
            time.sleep(15)

    log(f"Опубликовано: {published_count}")
    save_state(state)


if __name__ == "__main__":
    main()
