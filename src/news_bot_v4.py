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

BAD = [
    "подробности уточняются",
    "по мере появления",
    "событие относится",
    "важно для жителей",
    "система отметила",
    "детали уточняются",
]

SAKH = "сахалин южно-сахалинск холмск корсаков анива невельск оха долинск поронайск курил курильск".split()
RU_TERMS = "russia russian moscow kremlin ukraine ukrainian nato sanctions sanction putin lavrov россия рф российск москва кремль украина украин нато санкции путин лавров".split()
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
    q = urllib.parse.quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


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
    if not url.startswith(("http://", "https://")):
        return None
    return url


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


def page_info(url):
    if not url or is_google(url):
        return {}
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=30, allow_redirects=True)
        if response.status_code >= 400:
            return {}
        page = response.text[:800000]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        image = meta(page, "og:image") or meta(page, "twitter:image")
        paragraphs = []
        for raw in re.findall(r"<p[^>]*>(.*?)</p>", page, re.I | re.S):
            text = clean(raw)
            if len(text) > 45 and not any(x in text.lower() for x in ("cookie", "javascript", "подпис", "реклама")):
                paragraphs.append(text)
            if len(paragraphs) >= 4:
                break
        return {
            "url": response.url or url,
            "title": clean(meta(page, "og:title") or meta(page, "twitter:title") or (title_match.group(1) if title_match else "")),
            "desc": clean(meta(page, "og:description") or meta(page, "description") or meta(page, "twitter:description")),
            "image": abs_url(image, response.url or url) if image else None,
            "published": iso_dt(meta(page, "article:published_time") or meta(page, "datePublished")),
            "text": " ".join(paragraphs)[:1600],
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
        return "📍 Сахалин", 100
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
            text = " ".join(x for x in (page_desc, page.get("text"), rss_text) if x).strip()[:1800]
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
    payload = {"model": MODEL, "messages": messages, "temperature": 0.05, "max_tokens": max_tokens}
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "HTTP-Referer": "https://t.me/SkySakhNews", "X-OpenRouter-Title": "SkySakhNews"},
        json=payload,
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


def prompt(items):
    data = [{"id": x["id"], "category": x["category_hint"], "source": x["source"], "title": x["title"], "source_text": x["summary"], "published_at": x["published_at"]} for x in items]
    return (
        "Ты редактор Telegram-канала SkySakhNews. Выбери ровно 2 свежие новости: одну сахалинскую, если есть, вторую из другого направления. "
        "Весь output строго на русском языке. Английский исходник нужно перевести и пересказать по-русски. "
        "Нельзя оставлять английские предложения в title_ru и body. "
        "Пиши как обычный новостной Telegram-канал: русский заголовок и 2-4 абзаца. Без списков, без слов 'Суть' и 'Источник'. "
        "Используй только факты из title/source_text, ничего не выдумывай. "
        "Верни только JSON: [{\"id\":1,\"category\":\"📍 Сахалин\",\"title_ru\":\"...\",\"body\":[\"абзац\",\"абзац\"],\"footer\":\"ЧП | САХАЛИН\"}]\n"
        "Кандидаты:\n" + json.dumps(data, ensure_ascii=False)
    )


def ask_ai(items):
    text = openrouter([
        {"role": "system", "content": "Возвращай только валидный JSON. Все новостные тексты — строго на русском языке."},
        {"role": "user", "content": prompt(items)},
    ])
    return parse_json(text)


def rewrite_ru(item):
    text = openrouter([
        {"role": "system", "content": "Ты переводчик и редактор новостей. Верни только один JSON-объект. Все поля строго на русском языке."},
        {"role": "user", "content": "Переведи и перескажи новость строго по-русски. Не оставляй английские предложения. Используй только эти факты, ничего не добавляй. Формат: {\"title_ru\":\"...\",\"body\":[\"абзац\",\"абзац\"]}\n" + json.dumps({"title": item["title"], "source_text": item["summary"], "category": item["category_hint"]}, ensure_ascii=False)},
    ], max_tokens=900)
    if "{" in text and "}" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


def sentences(text):
    return [x.strip(" —-•") for x in re.split(r"(?<=[.!?])\s+|[;]\s+", clean(text)) if len(x.strip()) > 25]


def fallback_body(item):
    title = clean(item.get("title"))
    output = []
    for line in sentences(item.get("summary", "")):
        if latin_ratio(line) > 0.35:
            continue
        if any(bad in line.lower() for bad in BAD) or too_similar(line, title):
            continue
        output.append(line)
        if len(output) >= 3:
            break
    return output


def fallback_select(items):
    local = [x for x in items if is_local(x)]
    other = [x for x in items if not is_local(x)]
    chosen = (local[:1] + other[:1]) or items[:2]
    return [{"id": x["id"], "category": x["category_hint"], "title_ru": x["title"], "body": fallback_body(x), "footer": FOOTER.get(x["category_hint"], "НОВОСТИ")} for x in chosen[:2]]


def balance(selected, items):
    by_id = {x["id"]: x for x in items}
    output = []
    for row in selected:
        try:
            item_id = int(row.get("id"))
        except Exception:
            continue
        if item_id in by_id and item_id not in [x.get("id") for x in output]:
            output.append(row)
        if len(output) >= 2:
            break
    local = [x for x in items if is_local(x)]
    other = [x for x in items if not is_local(x)]
    ids = [int(x.get("id")) for x in output if str(x.get("id", "")).isdigit()]
    if local and not any(i in by_id and is_local(by_id[i]) for i in ids):
        output = [fallback_select(local)[0]] + output[:1]
    ids = [int(x.get("id")) for x in output if str(x.get("id", "")).isdigit()]
    if other and not any(i in by_id and not is_local(by_id[i]) for i in ids):
        output = output[:1] + [fallback_select(other)[0]]
    return (output or fallback_select(items))[:2]


def ensure_russian(row, item):
    title = clean(row.get("title_ru") or item["title"])
    body = row.get("body") if isinstance(row.get("body"), list) else []
    joined = title + " " + " ".join(clean(x) for x in body)
    if latin_ratio(joined) <= 0.22 and body:
        return row
    log("Русская редактура: " + item["title"][:80])
    try:
        fixed = rewrite_ru(item)
        row["title_ru"] = fixed.get("title_ru") or title
        row["body"] = fixed.get("body") if isinstance(fixed.get("body"), list) else body
    except Exception as exc:
        log("rewrite failed: " + str(exc))
    return row


def body_lines(row, item):
    raw = row.get("body") if isinstance(row.get("body"), list) else sentences(str(row.get("body") or ""))
    title = clean(row.get("title_ru") or item["title"])
    output = []
    for line in raw:
        line = clean(line)
        if not line or latin_ratio(line) > 0.30:
            continue
        if any(bad in line.lower() for bad in BAD) or too_similar(line, title):
            continue
        output.append(line)
        if len(output) >= 4:
            break
    if not output:
        output = fallback_body(item)
    return output


def make_post(row, item, max_len):
    category = clean(row.get("category") or item["category_hint"])
    title = clean(row.get("title_ru") or item["title"])
    if latin_ratio(title) > 0.30:
        title = "Международные СМИ сообщили о новом развитии событий"
    lines = body_lines(row, item)
    if not lines:
        raise RuntimeError("Нет русскоязычного текста для публикации")
    footer = clean(row.get("footer") or FOOTER.get(category, "НОВОСТИ"))
    source = clean(item.get("source") or "Источник")
    url = item["url"]
    url_attr = attr(url)
    text = f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in lines) + f"\n\n{esc(footer)} · <a href=\"{url_attr}\">{esc(source)}</a>\n<a href=\"{url_attr}\">&#8205;</a>"
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
    row = ensure_russian(row, item)
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
        selected = balance(ask_ai(items), items)
    except Exception as exc:
        log("AI fallback: " + str(exc))
        selected = fallback_select(items)
    by_id = {x["id"]: x for x in items}
    published = 0
    for row in selected:
        try:
            item = by_id[int(row.get("id"))]
        except Exception:
            continue
        if item["url"] in state.get("published_urls", []):
            continue
        try:
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
