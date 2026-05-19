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
POSTS_PER_RUN = 2
IMAGE_REQUIRED = os.getenv("IMAGE_REQUIRED", "1").strip() != "0"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL") or "openrouter/free"

FOOTER = {
    "📍 Сахалин": "ЧП | САХАЛИН",
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 РФ / война и безопасность": "РФ | ВОЙНА И БЕЗОПАСНОСТЬ",
    "🇷🇺 РФ / экономика": "РФ | ЭКОНОМИКА",
    "🇷🇺 РФ / законы и политика": "РФ | ЗАКОНЫ И ПОЛИТИКА",
    "🧭 Геополитика": "МИР | ГЕОПОЛИТИКА",
    "💻 IT / технологии": "IT | ТЕХНОЛОГИИ",
}

BAD_PHRASES = [
    "подробности уточняются", "по мере появления", "событие относится", "важно для жителей",
    "система отметила", "детали уточняются", "рельсения", "трансплантирован организм",
    "пресс-команда bbc", "получитель интерпретировал", "слишком важно не провалиться",
    "мошенники угрожали задержкой", "потеря 13,3 млн рублей", "мировые сми сообщили о новом",
    "международные сми сообщили о новом", "новое развитие вокруг россии",
]

SAKH = "сахалин южно-сахалинск сахалинская область холмск корсаков анива невельск оха долинск поронайск углегорск тымовское курил курильск южно-курильск северо-курильск".split()
SAKH_EVENTS = "дтп пожар происшествие землетрясение шторм циклон авария розыск погиб пострадал задержали суд мчс мвд отключение эвакуация обыск задержан мошенничество кража".split()

WAR_SECURITY = "война сво украина украин фронт армия военн минобороны ракета ракеты ракетный дрон дроны беспилотник беспилотники бпла удар удары атака атаковал атаковали обстрел обстреляли бомб бомбеж взрыв пво мобилизац фсб теракт диверс погиб ранен drone drones strike missile attack attacked shelling bombing explosion air defense military army war ukraine".split()
ECONOMY = "экономика экономический рубль инфляция ставка центробанк цб бюджет минфин налог налоги пошлин экспорт импорт нефть газ спг топливо бензин дизель банк банки рынок санкц цена цены доходы расходы oil gas lng inflation budget economy sanction sanctions export import bank rate central".split()
HARD_LAWS = "закон законопроект госдума штраф запрет запретили ужесточ уголовн наказан поправк суд верховный конституционный фсб мвд роскомнадзор блокировк иноагент экстремизм терроризм мобилизац воинск призыв паспорт гражданство мигрант censorship ban law bill fine criminal court".split()
HIGH_POLITICS = "кремль песков путин лавров мишустин совбез президент правительство госдума мид минобороны переговоры саммит встреча послание указ выборы отставка назначение kremlin putin lavrov moscow president government summit talks".split()

WORLD_RU = "russia russian moscow kremlin ukraine ukrainian nato sanctions sanction putin lavrov china xi trump g7 eu россия рф российск москва кремль украина украин нато санкции путин лавров китай си трамп ес g7".split()
GEO = "iran иран israel израиль china китай taiwan тайвань nato нато g7 g20 sanctions санкции ukraine украина war война conflict конфликт oil нефть gas газ".split()
IT = "openai ai ии нейросет google microsoft apple meta nvidia chip чип кибератака cyberattack утечка data telegram android ios robot робот".split()

LOCAL_NOISE = "афиша вакансии гороскоп погода реклама конкурс спорт матч рейтинг".split()
GENERIC_RU_NOISE = "спорт турнир матч рейтинг самокат фестиваль выставка конкурс культура театр концерт погода".split()


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


def sha_title(value):
    return hashlib.sha1(norm(value).encode("utf-8")).hexdigest()


def latin_ratio(text):
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return 0.0
    return len([x for x in letters if re.match(r"[A-Za-z]", x)]) / len(letters)


def has_terms(text, terms):
    t = " " + (text or "").lower() + " "
    return [w for w in terms if w in t]


def too_similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    sa, sb = set(a.split()), set(b.split())
    return len(sa) >= 4 and len(sb) >= 4 and len(sa & sb) / max(1, min(len(sa), len(sb))) > 0.75


def gnews(query, lang="en", country="US"):
    return f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query)}&hl={lang}&gl={country}&ceid={country}:{lang}"


SOURCES = [
    ("Sakhalin", "sakhalin", gnews("Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Курилы ДТП OR пожар OR происшествие OR землетрясение OR шторм OR авария OR розыск OR отключение OR задержали OR суд", "ru", "RU")),
    ("Interfax", "ru", "https://www.interfax.ru/rss.asp"),
    ("Reuters", "world", gnews("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas drone missile war economy")),
    ("AP News", "world", gnews("site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas Iran Israel drone missile war")),
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


def resolve_google_url(url):
    if not url or not is_google(url):
        return url
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, allow_redirects=True)
        if r.url and not is_google(r.url):
            return r.url
    except Exception:
        pass
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
    return resolve_google_url(abs_url(base) or base)


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
    words = [w for w in norm(title).split() if len(w) >= 5]
    if not words:
        return 0.0
    text_norm = " " + norm(text) + " "
    return sum(1 for w in words if f" {w} " in text_norm) / len(words)


def page_info(url):
    if not url or is_google(url):
        return {}
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=30, allow_redirects=True)
        if r.status_code >= 400:
            return {}
        page = r.text[:900000]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        title = clean(meta(page, "og:title") or meta(page, "twitter:title") or (title_match.group(1) if title_match else ""))
        desc = clean(meta(page, "og:description") or meta(page, "description") or meta(page, "twitter:description"))
        img = meta(page, "og:image") or meta(page, "twitter:image")
        paragraphs = []
        for raw in re.findall(r"<p[^>]*>(.*?)</p>", page, re.I | re.S):
            text = clean(raw)
            if len(text) > 55 and not any(x in text.lower() for x in ("cookie", "javascript", "подпис", "реклама", "newsletter", "advertisement")):
                paragraphs.append(text)
            if len(paragraphs) >= 4:
                break
        page_text = " ".join(paragraphs)[:1600]
        if title and page_text and title_overlap(title, page_text) < 0.10:
            page_text = ""
        return {
            "url": r.url or url,
            "title": title,
            "desc": desc,
            "image": abs_url(img, r.url or url) if img else None,
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
    text = f"{title} {rss_text} {page_desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if source_type == "sakhalin" or has_terms(text, SAKH):
        if has_terms(text, LOCAL_NOISE):
            return None, 0
        if not has_terms(text, SAKH_EVENTS) and len(clean(rss_text + page_desc)) < 120:
            return None, 0
        return "📍 Сахалин", 125 + (15 if has_terms(text, SAKH_EVENTS) else 0)

    if source_type == "world":
        # Главный приоритет: как мир пишет о России/Украине/санкциях/НАТО/энергетике.
        if has_terms(text, RU_WORLD):
            bonus = 0
            if has_terms(text, WAR_SECURITY): bonus += 20
            if has_terms(text, ECONOMY): bonus += 16
            if has_terms(text, HARD_LAWS + HIGH_POLITICS): bonus += 10
            return "🌍 Мир о России", 170 + bonus
        if len(has_terms(text, GEO)) >= 2:
            return "🧭 Геополитика", 88
        return None, 0

    if source_type == "ru":
        if "/moscow/" in path or has_terms(text, GENERIC_RU_NOISE):
            return None, 0
        if has_terms(text, WAR_SECURITY):
            return "🇷🇺 РФ / война и безопасность", 145
        if has_terms(text, ECONOMY):
            return "🇷🇺 РФ / экономика", 132
        if has_terms(text, HARD_LAWS + HIGH_POLITICS):
            return "🇷🇺 РФ / законы и политика", 122
        return None, 0

    if source_type == "it":
        # IT оставляем фоновым направлением, только если нет сильных политико-экономических новостей.
        return ("💻 IT / технологии", 65) if has_terms(text, IT) else (None, 0)

    return None, 0


def load_state():
    if not os.path.exists(STATE):
        return {"published_urls": [], "published_title_hashes": [], "last_posts": []}
    with open(STATE, "r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("published_urls", [])
    state.setdefault("published_title_hashes", [])
    state.setdefault("last_posts", [])
    return state


def save_state(state):
    state["published_urls"] = state.get("published_urls", [])[-900:]
    state["published_title_hashes"] = state.get("published_title_hashes", [])[-900:]
    state["last_posts"] = state.get("last_posts", [])[-80:]
    state["last_run_sakhalin"] = datetime.now(TZ).isoformat(timespec="seconds")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_image_bytes(url):
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}, timeout=35, allow_redirects=True)
        if r.status_code >= 400:
            log(f"image bad status {r.status_code}: {url[:90]}")
            return None
        content_type = (r.headers.get("content-type") or "").split(";")[0].lower()
        data = r.content
        if content_type == "image/svg+xml" or not content_type.startswith("image/"):
            log(f"image bad content-type {content_type}: {url[:90]}")
            return None
        if len(data) < 8_000 or len(data) > 9_500_000:
            log(f"image bad size {len(data)}: {url[:90]}")
            return None
        ext = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "jpg")
        return data, content_type, f"news.{ext}"
    except Exception as exc:
        log("image download failed: " + str(exc))
        return None


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
            parts = [page_desc, rss_text]
            if page.get("text"):
                parts.append(page["text"])
            source_text = " ".join(x for x in parts if x).strip()[:1800]
            link = page.get("url") or link
            if len(clean(title)) < 20 or len(clean(source_text)) < 120:
                log("skip low info: " + title[:80])
                continue
            h = sha_title(title)
            if link in used_urls or h in used_titles:
                continue
            category, score = classify(source_type, title, rss_text, page_desc, link)
            if not category:
                continue
            image_url = rss_image(entry, raw, link) or page.get("image")
            image = fetch_image_bytes(image_url) if image_url else None
            if IMAGE_REQUIRED and not image:
                log("skip no valid image: " + title[:80])
                continue
            items.append({
                "id": len(items) + 1,
                "source": source_name(entry, source),
                "source_type": source_type,
                "category_hint": category,
                "score": score + (15 if image else 0),
                "title": title,
                "summary": source_text,
                "url": link,
                "image_url": image_url,
                "image_file": image,
                "published_at": (page.get("published") or dt or datetime.now(timezone.utc)).isoformat(),
                "title_hash": h,
            })
            log(f"candidate: {category} | {score} | {title[:90]}")
    items.sort(key=lambda x: -x["score"])
    return items[:40]


def openrouter(messages, max_tokens=1600):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    r = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "HTTP-Referer": "https://t.me/SkySakhNews", "X-OpenRouter-Title": "SkySakhNews"},
        json={"model": MODEL, "messages": messages, "temperature": 0.02, "max_tokens": max_tokens},
        timeout=90,
    )
    if r.status_code >= 400:
        raise RuntimeError(r.text[:700])
    return r.json()["choices"][0]["message"]["content"].strip()


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])


def select_order(items):
    # Без лишнего расхода API: программный приоритет.
    # 1 слот: главное направление — мир о России / РФ война, экономика, жесткие законы.
    # 2 слот: Сахалин, если есть. Если Сахалина нет — ещё одна главная новость.
    local = [x for x in items if x["category_hint"] == "📍 Сахалин"]
    main = [x for x in items if x["category_hint"] != "📍 Сахалин"]
    ordered = []
    if main:
        ordered.append(main[0])
    if local:
        ordered.append(local[0])
    for item in main + local:
        if item not in ordered:
            ordered.append(item)
    return ordered


def prompt_write(item, error=""):
    return (
        "Сделай короткий новостной пост для Telegram строго на русском языке.\n"
        "Это фактологическая выжимка, не художественный пересказ.\n\n"
        "Тематика канала: Сахалин; мир о России; РФ — война, дроны, удары, бомбёжки, экономика, санкции, жёсткие законы, громкая политика.\n"
        "Правила:\n"
        "1) Только факты из title/source_text. Ничего не добавляй.\n"
        "2) Английский текст переведи на русский. Английские предложения запрещены.\n"
        "3) 2-3 абзаца, каждый 1-2 предложения.\n"
        "4) Не используй списки, 'Суть', 'Источник', 'Что известно'.\n"
        "5) Заголовок конкретный, не одно слово, не общий шаблон.\n"
        "6) Если это обычная бытовая/мелкая российская новость без войны, экономики, законов или громкой политики — reject=true.\n"
        "7) Если фактов мало — reject=true.\n"
        f"Ошибка предыдущей попытки: {error}\n\n"
        "Формат строго JSON: {\"reject\":false,\"title_ru\":\"...\",\"body\":[\"абзац\",\"абзац\"],\"footer\":\"...\"}\n\n"
        "Данные:\n" + json.dumps({"category": item["category_hint"], "footer": FOOTER.get(item["category_hint"], "НОВОСТИ"), "source": item["source"], "title": item["title"], "source_text": item["summary"], "published_at": item["published_at"]}, ensure_ascii=False)
    )


def write_post(item, error=""):
    text = openrouter([
        {"role": "system", "content": "Ты профессиональный редактор новостей. Возвращай только валидный JSON на русском."},
        {"role": "user", "content": prompt_write(item, error)},
    ], max_tokens=1000)
    if "{" in text and "}" in text:
        text = text[text.find("{"):text.rfind("}") + 1]
    return json.loads(text)


def numbers(text):
    return set(re.findall(r"\d+(?:[,.]\d+)?", text or ""))


def validate(row, item):
    if row.get("reject") is True:
        return ["модель отклонила новость"]
    title = clean(row.get("title_ru"))
    body = row.get("body") if isinstance(row.get("body"), list) else []
    body = [clean(x) for x in body if clean(x)]
    joined = title + " " + " ".join(body)
    source = item["title"] + " " + item["summary"]
    errors = []
    if len(title.split()) < 4 or len(title) < 28:
        errors.append("заголовок слишком короткий/общий")
    if len(body) < 2:
        errors.append("меньше двух абзацев")
    if len(joined) < 260:
        errors.append("текст слишком короткий")
    if latin_ratio(joined) > 0.10:
        errors.append("много английского")
    low = joined.lower()
    for phrase in BAD_PHRASES:
        if phrase in low:
            errors.append("плохая фраза: " + phrase)
    invented = numbers(joined) - numbers(source)
    if invented:
        errors.append("добавлены числа не из источника: " + ", ".join(sorted(invented)))
    if re.search(r"\b(the|who|has|said|will|after|before|with|from|this|that|over|under|against|faces|keeps)\b", joined, re.I):
        errors.append("остались английские слова")
    if any(len(x) < 60 for x in body):
        errors.append("есть слишком короткий абзац")
    if any(len(x) > 520 for x in body):
        errors.append("есть слишком длинный абзац")
    return errors


def generate_row(item):
    error = ""
    for _ in range(3):
        try:
            row = write_post(item, error)
            row["category"] = item["category_hint"]
            row["footer"] = row.get("footer") or FOOTER.get(item["category_hint"], "НОВОСТИ")
            errors = validate(row, item)
            if not errors:
                return row
            error = "; ".join(errors)
            log("rewrite required: " + error)
        except Exception as exc:
            error = str(exc)
            log("write retry: " + error)
    raise RuntimeError("не прошёл редакционный валидатор: " + error)


def make_post(row, item, max_len):
    category = clean(row.get("category") or item["category_hint"])
    title = clean(row.get("title_ru"))
    body = [clean(x) for x in row.get("body", []) if clean(x)]
    footer = clean(row.get("footer") or FOOTER.get(category, "НОВОСТИ"))
    source = clean(item.get("source") or "Источник")
    url = item["url"]
    u = attr(url)
    text = f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(footer)} · <a href=\"{u}\">{esc(source)}</a>"
    return text[:max_len]


def tg_photo(item, caption):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    image = item.get("image_file")
    if not image:
        raise RuntimeError("нет валидной картинки")
    data, content_type, filename = image
    files = {"photo": (filename, data, content_type)}
    payload = {"chat_id": chat, "caption": caption, "parse_mode": "HTML"}
    r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data=payload, files=files, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(r.text[:700])
    return r.json()


def main():
    state = load_state()
    log("Сбор кандидатов")
    items = collect(state)
    log(f"Кандидатов после тематического фильтра: {len(items)}")
    if not items:
        save_state(state)
        return
    ordered = select_order(items)
    published = 0
    for item in ordered:
        if published >= POSTS_PER_RUN:
            break
        if item["url"] in state.get("published_urls", []):
            continue
        try:
            row = generate_row(item)
            caption = make_post(row, item, 980)
            log(f"publish photo-card: {item['category_hint']} | {item['source']} | {item['title'][:90]}")
            result = tg_photo(item, caption)
        except Exception as exc:
            log("candidate skipped: " + str(exc))
            continue
        if result.get("ok"):
            state.setdefault("published_urls", []).append(item["url"])
            state.setdefault("published_title_hashes", []).append(item["title_hash"])
            state.setdefault("last_posts", []).append({
                "time_sakhalin": datetime.now(TZ).isoformat(timespec="seconds"),
                "source": item["source"],
                "category": row.get("category") or item["category_hint"],
                "title": row.get("title_ru") or item["title"],
                "url": item["url"],
                "published_at": item.get("published_at"),
                "with_image": True,
                "publish_method": "sendPhoto/upload",
                "score": item.get("score"),
            })
            published += 1
            time.sleep(12)
    log(f"Опубликовано: {published}")
    save_state(state)


if __name__ == "__main__":
    main()
