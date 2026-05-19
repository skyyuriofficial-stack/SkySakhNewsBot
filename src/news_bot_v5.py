import os
import re
import json
import html
import time
import hashlib
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
import feedparser

STATE = "state.json"
TZ = timezone(timedelta(hours=11))
MAX_AGE_HOURS = 36
POSTS = 2
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL") or "openrouter/free"

FOOTER = {
    "📍 Сахалин": "ЧП | САХАЛИН",
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 Россия": "РОССИЯ",
    "🧭 Геополитика": "МИР | ГЕОПОЛИТИКА",
    "💻 IT / технологии": "IT | ТЕХНОЛОГИИ",
}

BAD_PHRASES = [
    "подробности уточняются",
    "по мере появления",
    "событие относится",
    "важно для жителей",
    "система отметила",
    "детали уточняются",
    "рельсения",
    "трансплантирован организм",
    "пресс-команда bbc",
    "получитель интерпретировал",
    "слишком важно не провалиться",
]

SAKH = "сахалин южно-сахалинск холмск корсаков анива невельск оха долинск поронайск курил курильск".split()
SAKH_EVENTS = "дтп пожар происшествие землетрясение шторм циклон авария розыск погиб пострадал задержали суд мчс мвд".split()
RU_TERMS = "russia russian moscow kremlin ukraine ukrainian nato sanctions sanction putin lavrov china xi trump россия рф российск москва кремль украина украин нато санкции путин лавров китай си трамп".split()
GEO_TERMS = "iran иран israel израиль china китай taiwan тайвань nato нато g7 g20 sanctions санкции ukraine украина war война conflict конфликт oil нефть gas газ".split()
IT_TERMS = "openai ai ии нейросет google microsoft apple meta nvidia chip чип кибератака cyberattack утечка data telegram android ios robot робот".split()


def log(text):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S} SAKH] {text}", flush=True)


def clean(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def esc(value):
    return html.escape(str(value or ""), quote=False)


def attr(value):
    return html.escape(str(value or ""), quote=True)


def norm(value):
    return re.sub(r"[^0-9a-zа-яё]+", " ", clean(value).lower()).strip()


def title_hash(value):
    return hashlib.sha1(norm(value).encode("utf-8")).hexdigest()


def latin_ratio(text):
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return 0.0
    latin = [x for x in letters if re.match(r"[A-Za-z]", x)]
    return len(latin) / len(letters)


def too_similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    sa, sb = set(a.split()), set(b.split())
    return len(sa) >= 4 and len(sb) >= 4 and len(sa & sb) / max(1, min(len(sa), len(sb))) > 0.75


def has_terms(text, terms):
    text = " " + (text or "").lower() + " "
    return [t for t in terms if t in text]


def gnews(query, lang="en", country="US"):
    return f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query)}&hl={lang}&gl={country}&ceid={country}:{lang}"


SOURCES = [
    ("Sakhalin", "sakhalin", gnews("Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Курилы ДТП OR пожар OR происшествие OR землетрясение OR шторм OR авария OR розыск", "ru", "RU")),
    ("Interfax", "ru", "https://www.interfax.ru/rss.asp"),
    ("Reuters", "world", gnews("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas")),
    ("AP News", "world", gnews("site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas Iran Israel")),
    ("BBC World", "world", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Guardian World", "world", "https://www.theguardian.com/world/rss"),
    ("BBC Technology", "it", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("Guardian Technology", "it", "https://www.theguardian.com/technology/rss"),
    ("Habr", "it", "https://habr.com/ru/rss/articles/"),
]


def is_google(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return "news.google." in host or host in ("google.com", "www.google.com")


def abs_url(url, base=""):
    if not url:
        return None
    url = html.unescape(str(url).strip())
    if url.startswith("//"):
        url = "https:" + url
    if base and url.startswith("/"):
        url = urllib.parse.urljoin(base, url)
    return url if url.startswith(("http://", "https://")) else None


def entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        try:
            raw = entry.get(key)
            if raw:
                dt = parsedate_to_datetime(str(raw))
                return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except Exception:
            pass
    return None


def is_fresh(dt):
    if not dt:
        return True
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(hours=MAX_AGE_HOURS)


def direct_url(entry):
    base = clean(entry.get("link", ""))
    urls = []
    for raw in (str(entry.get("summary", "") or ""), str(entry.get("description", "") or "")):
        urls += re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
    for link in entry.get("links", []) or []:
        if isinstance(link, dict) and link.get("href"):
            urls.append(str(link["href"]))
    for url in urls:
        url = abs_url(url, base)
        if url and not is_google(url):
            return url
    return abs_url(base) or base


def meta(page, key):
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        found = re.search(pattern, page, re.I)
        if found:
            return html.unescape(found.group(1).strip())
    return None


def iso_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        return None


def title_overlap(title, text):
    title_words = [w for w in norm(title).split() if len(w) >= 5]
    if not title_words:
        return 0
    text_norm = " " + norm(text) + " "
    return sum(1 for w in title_words if f" {w} " in text_norm) / len(title_words)


def page_info(url):
    if not url or is_google(url):
        return {}
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=30, allow_redirects=True)
        if response.status_code >= 400:
            return {}
        page = response.text[:900000]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        image = meta(page, "og:image") or meta(page, "twitter:image")
        title = clean(meta(page, "og:title") or meta(page, "twitter:title") or (title_match.group(1) if title_match else ""))
        desc = clean(meta(page, "og:description") or meta(page, "description") or meta(page, "twitter:description"))
        paragraphs = []
        for raw in re.findall(r"<p[^>]*>(.*?)</p>", page, re.I | re.S):
            text = clean(raw)
            if len(text) > 45 and not any(x in text.lower() for x in ("cookie", "javascript", "подпис", "реклама", "newsletter", "advertisement")):
                paragraphs.append(text)
            if len(paragraphs) >= 4:
                break
        page_text = " ".join(paragraphs)[:1600]
        # Берём body со страницы только если он реально похож на тот же материал.
        if title and page_text and title_overlap(title, page_text) < 0.12:
            page_text = ""
        return {
            "url": response.url or url,
            "title": title,
            "desc": desc,
            "image": abs_url(image, response.url or url) if image else None,
            "published": iso_dt(meta(page, "article:published_time") or meta(page, "datePublished")),
            "text": page_text,
        }
    except Exception as exc:
        log("page read failed: " + str(exc))
        return {}


def rss_image(entry, raw, link):
    for key in ("media_thumbnail", "media_content"):
        for item in entry.get(key, []) or []:
            if isinstance(item, dict) and item.get("url"):
                url = abs_url(str(item["url"]), link)
                if url:
                    return url
    found = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw or "", re.I)
    return abs_url(found.group(1), link) if found else None


def source_name(entry, fallback):
    source = entry.get("source")
    if isinstance(source, dict) and source.get("title"):
        return clean(source["title"])
    try:
        if getattr(source, "title", None):
            return clean(source.title)
    except Exception:
        pass
    return fallback


def classify(source_type, title, rss_text, page_desc, url):
    strict = f"{title} {rss_text} {page_desc}".lower()
    if source_type == "sakhalin" or has_terms(strict, SAKH):
        return "📍 Сахалин", 100 + (8 if has_terms(strict, SAKH_EVENTS) else 0)
    if source_type == "it":
        return ("💻 IT / технологии", 72) if has_terms(strict, IT_TERMS) else (None, 0)
    if source_type == "world":
        if has_terms(strict, RU_TERMS):
            return "🌍 Мир о России", 92
        if len(has_terms(strict, GEO_TERMS)) >= 2:
            return "🧭 Геополитика", 76
        return None, 0
    if source_type == "ru":
        return "🇷🇺 Россия", 74
    return None, 0


def load_state():
    if not os.path.exists(STATE):
        return {"published_urls": [], "published_title_hashes": [], "last_posts": []}
    with open(STATE, "r", encoding="utf-8") as file:
        state = json.load(file)
    state.setdefault("published_urls", [])
    state.setdefault("published_title_hashes", [])
    state.setdefault("last_posts", [])
    return state


def save_state(state):
    state["published_urls"] = state.get("published_urls", [])[-900:]
    state["published_title_hashes"] = state.get("published_title_hashes", [])[-900:]
    state["last_posts"] = state.get("last_posts", [])[-80:]
    state["last_run_sakhalin"] = datetime.now(TZ).isoformat(timespec="seconds")
    with open(STATE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def collect(state):
    used_urls = set(state.get("published_urls", []))
    used_titles = set(state.get("published_title_hashes", []))
    items = []
    for source, source_type, rss in SOURCES:
        log("Источник: " + source)
        feed = feedparser.parse(rss)
        for entry in feed.entries[:14]:
            dt = entry_time(entry)
            if not is_fresh(dt):
                log("old skip: " + clean(entry.get("title", ""))[:80])
                continue
            raw = str(entry.get("summary", "") or "")
            rss_text = clean(raw)
            link = direct_url(entry)
            if is_google(link):
                log("skip google wrapper: " + clean(entry.get("title", ""))[:80])
                continue
            page = page_info(link)
            if page.get("published") and not is_fresh(page["published"]):
                log("old meta skip: " + clean(entry.get("title", ""))[:80])
                continue
            title = page.get("title") or clean(entry.get("title", ""))
            page_desc = page.get("desc") or ""
            # Ключевое исправление: source_text строится из title + meta description + RSS.
            # Тело страницы добавляется только если похоже на этот же материал.
            text_parts = [page_desc, rss_text]
            if page.get("text"):
                text_parts.append(page["text"])
            text = " ".join(x for x in text_parts if x).strip()[:1800]
            link = page.get("url") or link
            hash_value = title_hash(title)
            if link in used_urls or hash_value in used_titles:
                continue
            category, score = classify(source_type, title, rss_text, page_desc, link)
            if not category:
                continue
            items.append({
                "id": len(items) + 1,
                "source": source_name(entry, source),
                "source_type": source_type,
                "category_hint": category,
                "score": score,
                "title": title,
                "summary": text,
                "url": link,
                "image_url": rss_image(entry, raw, link) or page.get("image"),
                "published_at": (page.get("published") or dt or datetime.now(timezone.utc)).isoformat(),
                "title_hash": hash_value,
            })
    items.sort(key=lambda x: (x["category_hint"] != "📍 Сахалин", -x["score"]))
    return items[:30]


def is_local(item):
    return item.get("category_hint") == "📍 Сахалин"


def openrouter(messages, max_tokens=1600):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "HTTP-Referer": "https://t.me/SkySakhNews", "X-OpenRouter-Title": "SkySakhNews"},
        json={"model": MODEL, "messages": messages, "temperature": 0.03, "max_tokens": max_tokens},
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text[:700])
    return response.json()["choices"][0]["message"]["content"].strip()


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return json.loads(text[text.find("["):text.rfind("]") + 1])


def prompt_select(items):
    data = [{"id": x["id"], "category": x["category_hint"], "source": x["source"], "title": x["title"], "source_text": x["summary"][:900], "published_at": x["published_at"]} for x in items]
    return (
        "Выбери ровно 2 свежие новости для Telegram-канала SkySakhNews: одну сахалинскую, если есть, вторую из другого направления. "
        "Верни только JSON-массив вида [{\"id\":1},{\"id\":2}]. Никакого текста.\n"
        "Кандидаты:\n" + json.dumps(data, ensure_ascii=False)
    )


def ask_select(items):
    text = openrouter([
        {"role": "system", "content": "Ты редактор. Возвращай только JSON."},
        {"role": "user", "content": prompt_select(items)},
    ], max_tokens=400)
    return parse_json(text)


def prompt_write(item, previous_error=""):
    return (
        "Сделай новостной пост для Telegram строго на русском языке. Это не творческий пересказ, а редакторская выжимка по источнику.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "1) Используй только факты из title и source_text. Ничего не добавляй.\n"
        "2) Не оставляй английские предложения. Все переведи на русский.\n"
        "3) Если данных мало — сделай короткий пост, но не выдумывай.\n"
        "4) Не используй маркеры, списки, слова 'Суть', 'Источник', 'Что известно'.\n"
        "5) Не используй корявые кальки. Пиши как АСТВ/РИА: коротко и ясно.\n"
        "6) Сохрани все числа, даты, имена и места, которые есть в источнике. Новые числа не добавляй.\n"
        "7) Если не уверен в факте — не пиши его.\n\n"
        f"Ошибка предыдущей попытки, которую надо исправить: {previous_error}\n\n"
        "Верни только JSON-объект: {\"title_ru\":\"...\",\"body\":[\"абзац 1\",\"абзац 2\"],\"footer\":\"...\"}\n\n"
        "Данные источника:\n" + json.dumps({"category": item["category_hint"], "footer": FOOTER.get(item["category_hint"], "НОВОСТИ"), "source": item["source"], "title": item["title"], "source_text": item["summary"], "published_at": item["published_at"]}, ensure_ascii=False)
    )


def write_post(item, previous_error=""):
    text = openrouter([
        {"role": "system", "content": "Ты профессиональный редактор и переводчик новостей. Возвращай только валидный JSON. Весь текст строго на русском."},
        {"role": "user", "content": prompt_write(item, previous_error)},
    ], max_tokens=1100)
    if "{" in text and "}" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


def numbers(text):
    return set(re.findall(r"\d+(?:[,.]\d+)?", text or ""))


def named_latin_tokens(text):
    return set(x.lower() for x in re.findall(r"\b[A-Z][A-Za-z]{2,}\b", text or ""))


def validate_row(row, item):
    title = clean(row.get("title_ru"))
    body = row.get("body") if isinstance(row.get("body"), list) else []
    body = [clean(x) for x in body if clean(x)]
    joined = title + " " + " ".join(body)
    source = item["title"] + " " + item["summary"]
    errors = []
    if not title:
        errors.append("нет русского заголовка")
    if len(body) < 1:
        errors.append("нет body")
    if latin_ratio(joined) > 0.12:
        errors.append("слишком много английского текста")
    low = joined.lower()
    for phrase in BAD_PHRASES:
        if phrase in low:
            errors.append("плохая фраза: " + phrase)
    invented_numbers = numbers(joined) - numbers(source)
    if invented_numbers:
        errors.append("добавлены числа, которых нет в источнике: " + ", ".join(sorted(invented_numbers)))
    # Разрешаем латиницу только в коротких названиях источников/аббревиатурах, но не целые фразы.
    if re.search(r"\b(the|who|has|said|will|after|before|with|from|this|that|over|under|against)\b", joined, re.I):
        errors.append("остались английские слова/фразы")
    if any(len(x) > 620 for x in body):
        errors.append("слишком длинный абзац")
    return errors


def sentences(text):
    return [x.strip(" —-•") for x in re.split(r"(?<=[.!?])\s+|[;]\s+", clean(text)) if len(x.strip()) > 25]


def fallback_body(item):
    output = []
    title = clean(item.get("title"))
    for line in sentences(item.get("summary", "")):
        if latin_ratio(line) > 0.25:
            continue
        if any(bad in line.lower() for bad in BAD_PHRASES) or too_similar(line, title):
            continue
        output.append(line)
        if len(output) >= 3:
            break
    return output


def fallback_select(items):
    local = [x for x in items if is_local(x)]
    other = [x for x in items if not is_local(x)]
    chosen = (local[:1] + other[:1]) or items[:2]
    return [{"id": x["id"]} for x in chosen[:2]]


def balance(selected, items):
    by_id = {x["id"]: x for x in items}
    output = []
    for row in selected:
        try:
            item_id = int(row.get("id"))
        except Exception:
            continue
        if item_id in by_id and item_id not in [x.get("id") for x in output]:
            output.append({"id": item_id})
        if len(output) >= 2:
            break
    local = [x for x in items if is_local(x)]
    other = [x for x in items if not is_local(x)]
    ids = [int(x.get("id")) for x in output if str(x.get("id", "")).isdigit()]
    if local and not any(i in by_id and is_local(by_id[i]) for i in ids):
        output = [{"id": local[0]["id"]}] + output[:1]
    ids = [int(x.get("id")) for x in output if str(x.get("id", "")).isdigit()]
    if other and not any(i in by_id and not is_local(by_id[i]) for i in ids):
        output = output[:1] + [{"id": other[0]["id"]}]
    return (output or fallback_select(items))[:2]


def generate_valid_row(item):
    previous_error = ""
    for attempt in range(3):
        try:
            row = write_post(item, previous_error)
            row["category"] = item["category_hint"]
            row["footer"] = row.get("footer") or FOOTER.get(item["category_hint"], "НОВОСТИ")
            errors = validate_row(row, item)
            if not errors:
                return row
            previous_error = "; ".join(errors)
            log(f"Повторная редактура: {previous_error}")
        except Exception as exc:
            previous_error = str(exc)
            log("write retry: " + previous_error)
    # Последний fallback разрешён только для русских источников, где есть русский source_text.
    fb = fallback_body(item)
    if fb:
        row = {"category": item["category_hint"], "title_ru": item["title"], "body": fb, "footer": FOOTER.get(item["category_hint"], "НОВОСТИ")}
        if not validate_row(row, item):
            return row
    raise RuntimeError("не удалось получить корректный русский фактологический текст")


def make_post(row, item, max_len):
    category = clean(row.get("category") or item["category_hint"])
    title = clean(row.get("title_ru"))
    body = [clean(x) for x in row.get("body", []) if clean(x)]
    footer = clean(row.get("footer") or FOOTER.get(category, "НОВОСТИ"))
    source = clean(item.get("source") or "Источник")
    url = item["url"]
    url_attr = attr(url)
    text = f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(footer)} · <a href=\"{url_attr}\">{esc(source)}</a>\n<a href=\"{url_attr}\">&#8205;</a>"
    return text[:max_len], url


def tg(method, payload):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    payload["chat_id"] = chat
    response = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=payload, timeout=75)
    if response.status_code >= 400:
        raise RuntimeError(response.text[:700])
    return response.json()


def publish(row, item):
    if item.get("image_url"):
        caption, _ = make_post(row, item, 980)
        try:
            log("photo: " + item["image_url"][:90])
            return tg("sendPhoto", {"photo": item["image_url"], "caption": caption, "parse_mode": "HTML"})
        except Exception as exc:
            log("photo failed: " + str(exc))
    text, preview = make_post(row, item, 3000)
    return tg("sendMessage", {"text": text, "parse_mode": "HTML", "disable_web_page_preview": False, "link_preview_options": json.dumps({"is_disabled": False, "url": preview, "prefer_large_media": True, "show_above_text": False}, ensure_ascii=False)})


def main():
    state = load_state()
    log("Сбор кандидатов")
    items = collect(state)
    log(f"Кандидатов после фильтра свежести: {len(items)}")
    if not items:
        save_state(state)
        return
    try:
        selected = balance(ask_select(items), items)
    except Exception as exc:
        log("AI select fallback: " + str(exc))
        selected = fallback_select(items)
    by_id = {x["id"]: x for x in items}
    published = 0
    for selected_item in selected:
        try:
            item = by_id[int(selected_item.get("id"))]
        except Exception:
            continue
        if item["url"] in state.get("published_urls", []):
            continue
        try:
            row = generate_valid_row(item)
            result = publish(row, item)
        except Exception as exc:
            log("publish skip: " + str(exc))
            continue
        if result.get("ok"):
            state.setdefault("published_urls", []).append(item["url"])
            state.setdefault("published_title_hashes", []).append(item["title_hash"])
            state.setdefault("last_posts", []).append({"time_sakhalin": datetime.now(TZ).isoformat(timespec="seconds"), "source": item["source"], "category": row.get("category") or item["category_hint"], "title": row.get("title_ru") or item["title"], "url": item["url"], "with_image": bool(item.get("image_url")), "published_at": item.get("published_at")})
            published += 1
            time.sleep(12)
    log(f"Опубликовано: {published}")
    save_state(state)


if __name__ == "__main__":
    main()
