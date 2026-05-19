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
MAX_CANDIDATES_FOR_LLM = 34
MAX_ENTRIES_PER_SOURCE = 16
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

FOOTER_MAP = {
    "📍 Сахалин": "ЧП | САХАЛИН",
    "🚨 ЧП / происшествия": "ЧП | ПРОИСШЕСТВИЯ",
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 Россия / политика": "РОССИЯ | ПОЛИТИКА",
    "🇷🇺 Россия / экономика": "РОССИЯ | ЭКОНОМИКА",
    "🇷🇺 Россия / внешняя политика": "РОССИЯ | ВНЕШНЯЯ ПОЛИТИКА",
    "🧭 Геополитика": "МИР | ГЕОПОЛИТИКА",
    "💻 IT / технологии": "IT | ТЕХНОЛОГИИ",
}

MONTHS_RU = (
    "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
)

VAGUE_LINES = [
    "подробности будут уточняться",
    "по мере появления новых сообщений",
    "причины и сила толчков уточняются",
    "сейсмическая активность зафиксирована",
    "новость отобрана",
    "автоматическим фильтром",
    "предварительная категория",
    "система отметила",
    "источник сообщения",
    "детали уточняются",
    "сообщение опубликовано",
]


def google_news_rss(query: str, lang: str = "en", country: str = "US") -> str:
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


SOURCES = [
    {
        "name": "Sakhalin Google News",
        "type": "sakhalin",
        "url": google_news_rss(
            "Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Анива OR Невельск OR Оха "
            "ДТП OR пожар OR циклон OR шторм OR отключение OR происшествие OR землетрясение OR цунами "
            "ограбление OR розыск OR авария",
            "ru",
            "RU",
        ),
        "weight": 100,
    },
    {"name": "Interfax", "type": "ru_general", "url": "https://www.interfax.ru/rss.asp", "weight": 78},
    {"name": "Reuters", "type": "world_authority", "url": google_news_rss("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas"), "weight": 96},
    {"name": "AP News", "type": "world_authority", "url": google_news_rss("site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas Iran Israel"), "weight": 94},
    {"name": "BBC World", "type": "world_authority", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "weight": 86},
    {"name": "The Guardian World", "type": "world_authority", "url": "https://www.theguardian.com/world/rss", "weight": 82},
    {"name": "BBC Technology", "type": "world_it", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "weight": 80},
    {"name": "The Guardian Technology", "type": "world_it", "url": "https://www.theguardian.com/technology/rss", "weight": 76},
    {"name": "Habr", "type": "it_ru", "url": "https://habr.com/ru/rss/articles/", "weight": 48},
]

SAKHALIN_GEO = [
    "сахалин", "южно-сахалинск", "сахалинская область", "холмск", "корсаков",
    "анива", "невельск", "оха", "долинск", "поронайск", "углегорск",
    "тымовское", "курил", "курильск", "южно-курильск", "северо-курильск",
]

SAKHALIN_IMPORTANT = [
    "дтп", "пожар", "погиб", "погибли", "пострадал", "пострадали",
    "шторм", "циклон", "ураган", "землетрясение", "цунами", "отключение",
    "авария", "эвакуация", "мчс", "мвд", "перекрытие", "дорог", "света",
    "воды", "тепла", "ограб", "краж", "разыскивают", "суд", "задерж",
]

INCIDENT = [
    "дтп", "авария", "пожар", "погиб", "погибли", "ранен", "ранены",
    "пострадал", "пострадали", "эвакуация", "взрыв", "обрушение",
    "землетрясение", "цунами", "шторм", "циклон", "ураган", "ограб",
    "краж", "разыскивают", "killed", "dead", "explosion", "earthquake", "evacuation",
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


def norm_text(value: str) -> str:
    value = clean_inline(value).lower()
    return re.sub(r"[^0-9a-zа-яё]+", " ", value).strip()


def too_similar(a: str, b: str) -> bool:
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    wa, wb = set(na.split()), set(nb.split())
    if len(wa) < 4 or len(wb) < 4:
        return False
    return len(wa & wb) / max(1, min(len(wa), len(wb))) > 0.72


def normalize_url(url: str, base_url: str = "") -> Optional[str]:
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


def is_google_news_url(url: str) -> bool:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return "news.google." in host or host in {"google.com", "www.google.com"}


def extract_direct_article_url(entry: Any, fallback: str) -> str:
    candidates: List[str] = []
    raw_fields = [str(entry.get("summary", "") or ""), str(entry.get("description", "") or ""), str(entry.get("content", "") or "")]
    for raw in raw_fields:
        for href in re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I):
            href = normalize_url(href, fallback)
            if href:
                candidates.append(href)
    links = entry.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and link.get("href"):
                href = normalize_url(str(link.get("href")), fallback)
                if href:
                    candidates.append(href)
    fallback_norm = normalize_url(fallback) or fallback
    for url in candidates:
        if not is_google_news_url(url) and not url.lower().startswith("https://news.google.com"):
            return url
    return fallback_norm


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
                    img = normalize_url(str(m["url"]), link)
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
                img = normalize_url(href, link)
                if img:
                    return img
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary_raw or "", flags=re.I)
    if m:
        return normalize_url(m.group(1), link)
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
    return hashlib.sha1(norm_text(title).encode("utf-8")).hexdigest()


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
            original_link = clean_inline(entry.get("link", ""))
            link = extract_direct_article_url(entry, original_link)
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
                "summary": summary[:1000],
                "url": link,
                "original_url": original_link,
                "image_url": image_url,
                "title_hash": hsh,
            })
    candidates.sort(key=lambda x: (CATEGORY_ORDER.get(x["category_hint"], 0), x["score_hint"]), reverse=True)
    return candidates[:MAX_CANDIDATES_FOR_LLM]


def is_local(cand: Dict[str, Any]) -> bool:
    return cand.get("category_hint") in ("📍 Сахалин", "🚨 ЧП / происшествия") and (
        cand.get("source_type") == "sakhalin"
        or bool(hits(f"{cand.get('title','')} {cand.get('summary','')}", SAKHALIN_GEO))
    )


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
        "Ты редактор Telegram-канала SkySakhNews. Нужно выбрать ровно 2 новости.\n\n"
        "Баланс выпуска:\n"
        "- если есть местная сахалинская новость, выбери 1 местную;\n"
        "- вторую выбери из другого направления: Мир о России, Россия/политика, Россия/экономика, Геополитика или IT;\n"
        "- две сахалинские подряд бери только если нет сильной второй новости.\n\n"
        "Формат текста как у новостного Telegram-канала, без служебных заголовков:\n"
        "- title_ru: короткий русский заголовок, переведи английский заголовок на русский;\n"
        "- body: 2-4 абзаца обычным текстом, без маркеров, без «Суть», без «Что известно», без «Почему важно»;\n"
        "- body должен раскрывать факт новости: что произошло, где, когда, кто участники, цифры, последствия;\n"
        "- обязательно сохраняй конкретику из title/summary: даты, места, имена, суммы, проценты, погибших/пострадавших;\n"
        "- если новость про землетрясение — укажи магнитуду/баллы, район, дату и ощущалось ли, если это есть в title/summary;\n"
        "- если цифр нет в title/summary, не выдумывай;\n"
        "- запрещены пустые фразы: «подробности уточняются», «система отметила», «событие относится», «важно для жителей»;\n"
        "- tone: сухой, новостной, как АСТВ/РИА/Mash, без канцелярита и без кликбейта.\n\n"
        "Верни строго JSON-массив без markdown:\n"
        "[{\"id\":1,\"category\":\"📍 Сахалин\",\"title_ru\":\"...\",\"body\":[\"абзац 1\",\"абзац 2\",\"абзац 3\"],\"footer\":\"ЧП | САХАЛИН\"}]\n\n"
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
        "temperature": 0.14,
        "max_tokens": 1900,
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


def split_sentence_facts(text: str) -> List[str]:
    text = clean_inline(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|[;]\s+", text)
    return [p.strip(" —-•") for p in parts if len(p.strip()) > 20]


def extract_numbers(text: str) -> List[str]:
    patterns = [
        rf"\b\d{{1,2}}\s+(?:{MONTHS_RU})\b",
        r"\b\d+[,.]?\d*\s*(?:балл\w*|магнитуд\w*|%|процент\w*|млн|млрд|руб\.?|доллар\w*|человек|погиб\w*|пострадал\w*)",
        r"\bмагнитуд[а-я]*\s*(?:до|около|примерно|составила|составило)?\s*\d+[,.]?\d*",
        r"\b\d+\s+землетрясен\w*",
    ]
    found: List[str] = []
    for p in patterns:
        found.extend(re.findall(p, text, flags=re.I))
    clean = []
    for x in found:
        if isinstance(x, tuple):
            x = " ".join(x)
        x = clean_inline(x)
        if x and x.lower() not in [v.lower() for v in clean]:
            clean.append(x)
    return clean[:5]


def earthquake_body(cand: Dict[str, Any]) -> Optional[List[str]]:
    raw = clean_inline(f"{cand.get('title','')}. {cand.get('summary','')}")
    low = raw.lower()
    if "землетр" not in low and "магнитуд" not in low:
        return None
    date = re.search(rf"\b\d{{1,2}}\s+(?:{MONTHS_RU})\b", raw, flags=re.I)
    count = re.search(r"\b(\d+)\s+землетрясен\w*", raw, flags=re.I)
    mags = re.findall(r"(?:магнитуд[а-я]*\s*(?:до|около|примерно|составила|составило)?\s*|M\s*)(\d+[,.]?\d*)", raw, flags=re.I)
    points = re.findall(r"(\d+[,.]?\d*)\s*балл\w*", raw, flags=re.I)
    places = [p for p in SAKHALIN_GEO if p in low]
    first = "В островном регионе"
    if count:
        first += f" сообщили о {count.group(1)} землетрясениях"
    else:
        first += " сообщили о землетрясении"
    if date:
        first += f" {date.group(0)}"
    if places:
        first += f". В сообщении упоминаются {', '.join(dict.fromkeys(places[:4]))}"
    first += "."
    second_parts = []
    if mags:
        second_parts.append(f"магнитуда — {', '.join(dict.fromkeys(mags[:3]))}")
    if points:
        second_parts.append(f"ощущалось до {', '.join(dict.fromkeys(points[:3]))} балла")
    if second_parts:
        second = "По данным исходного сообщения, " + "; ".join(second_parts) + "."
    else:
        second = "Магнитуда и балльность в RSS-описании не указаны; точное значение нужно смотреть в первоисточнике."
    result = [first, second]
    if "ощути" in low and not points:
        result.append("Источник отдельно отмечает, что толчки ощущались жителями.")
    return result[:3]


def fallback_body(cand: Dict[str, Any], category: str) -> List[str]:
    eq = earthquake_body(cand)
    if eq:
        return eq
    title = clean_inline(cand.get("title", ""))
    summary = clean_inline(cand.get("summary", ""))
    facts = split_sentence_facts(summary)
    nums = extract_numbers(f"{title}. {summary}")
    result: List[str] = []
    for fact in facts:
        if not too_similar(fact, title):
            result.append(fact)
        if len(result) >= 3:
            break
    if nums and not any(any(num in line for num in nums) for line in result):
        result.append("Ключевые данные сообщения: " + "; ".join(nums) + ".")
    if not result:
        result.append(title)
    return result[:4]


def fallback_select(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    local = [c for c in candidates if is_local(c)]
    other = [c for c in candidates if not is_local(c)]
    chosen: List[Dict[str, Any]] = []
    if local:
        chosen.append(local[0])
    if other and len(chosen) < POSTS_PER_RUN:
        chosen.append(other[0])
    for c in candidates:
        if len(chosen) >= POSTS_PER_RUN:
            break
        if c not in chosen:
            chosen.append(c)
    result = []
    for c in chosen[:POSTS_PER_RUN]:
        category = c["category_hint"]
        result.append({
            "id": c["id"],
            "category": category,
            "title_ru": c["title"],
            "body": fallback_body(c, category),
            "footer": FOOTER_MAP.get(category, "НОВОСТИ"),
            "selection_reason": "fallback без LLM",
        })
    return result


def enforce_balance(selected: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {c["id"]: c for c in candidates}
    local_candidates = [c for c in candidates if is_local(c)]
    other_candidates = [c for c in candidates if not is_local(c)]
    cleaned = []
    used_ids = set()
    for item in selected:
        try:
            cid = int(item.get("id"))
        except Exception:
            continue
        if cid in by_id and cid not in used_ids:
            cleaned.append(item)
            used_ids.add(cid)
        if len(cleaned) >= POSTS_PER_RUN:
            break
    if local_candidates and other_candidates:
        ids = [int(i.get("id")) for i in cleaned if str(i.get("id", "")).isdigit()]
        has_local = any(is_local(by_id[i]) for i in ids if i in by_id)
        has_other = any((not is_local(by_id[i])) for i in ids if i in by_id)
        if not has_local:
            c = local_candidates[0]
            cleaned = [{"id": c["id"], "category": c["category_hint"], "title_ru": c["title"], "body": fallback_body(c, c["category_hint"]), "footer": FOOTER_MAP.get(c["category_hint"], "НОВОСТИ")}] + cleaned[:1]
        if not has_other:
            c = other_candidates[0]
            item = {"id": c["id"], "category": c["category_hint"], "title_ru": c["title"], "body": fallback_body(c, c["category_hint"]), "footer": FOOTER_MAP.get(c["category_hint"], "НОВОСТИ")}
            cleaned = cleaned[:1] + [item] if cleaned else [item]
    if len(cleaned) < POSTS_PER_RUN:
        fallback = fallback_select(candidates)
        for item in fallback:
            if item.get("id") not in {x.get("id") for x in cleaned}:
                cleaned.append(item)
            if len(cleaned) >= POSTS_PER_RUN:
                break
    return cleaned[:POSTS_PER_RUN]


def prepare_body_lines(value: Any, item: Dict[str, Any], cand: Dict[str, Any], category: str) -> List[str]:
    raw_lines: List[str] = []
    if isinstance(value, list):
        raw_lines = [clean_inline(x) for x in value if clean_inline(x)]
    elif value:
        raw_lines = split_sentence_facts(clean_inline(value))
    eq = earthquake_body(cand)
    if eq:
        raw_lines = eq + raw_lines
    title = clean_inline(item.get("title_ru") or cand.get("title") or "")
    result: List[str] = []
    seen = set()
    for line in raw_lines:
        line = line.strip("—-• ")
        low = line.lower()
        if not line:
            continue
        if any(v in low for v in VAGUE_LINES):
            continue
        if low in seen:
            continue
        if too_similar(line, title):
            continue
        seen.add(low)
        result.append(line)
        if len(result) >= 4:
            break
    if len(result) < 2:
        for line in fallback_body(cand, category):
            low = line.lower()
            if low not in seen and not too_similar(line, title) and not any(v in low for v in VAGUE_LINES):
                result.append(line)
                seen.add(low)
            if len(result) >= 3:
                break
    return result[:4]


def build_news_post(item: Dict[str, Any], cand: Dict[str, Any], max_len: int = 3000) -> str:
    category = clean_inline(item.get("category") or cand["category_hint"])
    title = clean_inline(item.get("title_ru") or cand["title"])
    body = prepare_body_lines(item.get("body") or item.get("brief") or cand.get("summary") or "", item, cand, category)
    footer = clean_inline(item.get("footer") or FOOTER_MAP.get(category, "НОВОСТИ"))
    url = cand["url"]
    paragraphs = "\n\n".join(escape_html(x) for x in body if x)
    text = f"{escape_html(category)}\n\n<b>{escape_html(title)}</b>\n\n{paragraphs}\n\n{escape_html(footer)}\n{escape_html(url)}"
    if len(text) <= max_len:
        return text
    body = body[:2]
    paragraphs = "\n\n".join(escape_html(x[:450]) for x in body if x)
    return f"{escape_html(category)}\n\n<b>{escape_html(title[:240])}</b>\n\n{paragraphs}\n\n{escape_html(footer)}\n{escape_html(url)}"[:max_len]


def send_telegram_post(text: str, preview_url: str) -> Dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is missing")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "link_preview_options": json.dumps({
            "is_disabled": False,
            "url": preview_url,
            "prefer_large_media": True,
            "show_above_text": False,
        }, ensure_ascii=False),
    }
    response = requests.post(url, data=payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram sendMessage HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


def publish_item(item: Dict[str, Any], cand: Dict[str, Any]) -> Dict[str, Any]:
    post = build_news_post(item, cand)
    log(f"Публикуем текст с preview: {cand['url'][:90]}")
    return send_telegram_post(post, cand["url"])


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
        selected = enforce_balance(selected, candidates)
        log(f"OpenRouter выбрал новостей после балансировки: {len(selected)}")
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
        log(f"Публикация: {cand['category_hint']} | {cand['source']} | {cand['title'][:90]}")
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
            })
            published_count += 1
            time.sleep(12)
    log(f"Опубликовано: {published_count}")
    save_state(state)


if __name__ == "__main__":
    main()
