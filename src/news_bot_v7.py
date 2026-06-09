import os
import re
import json
import html
import time
import hashlib
import urllib.parse
from io import BytesIO
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import feedparser
from PIL import Image, ImageOps

STATE = "state.json"
TZ = timezone(timedelta(hours=11))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL") or "openrouter/free"
POSTS_PER_RUN = int(os.getenv("POSTS_PER_RUN", "2"))
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "36"))
IMAGE_REQUIRED = os.getenv("IMAGE_REQUIRED", "1") != "0"

FOOTER = {
    "sakh": ("📍 Сахалин", "ЧП | САХАЛИН"),
    "world_ru": ("🌍 Мир о России", "МИР О РОССИИ"),
    "ru_pol": ("🇷🇺 Россия / политика", "РОССИЯ | ПОЛИТИКА"),
    "ru_eco": ("🇷🇺 Россия / экономика", "РОССИЯ | ЭКОНОМИКА"),
    "geo": ("🧭 Геополитика", "МИР | ГЕОПОЛИТИКА"),
    "it": ("💻 IT / технологии", "IT | ТЕХНОЛОГИИ"),
}
BAD = [
    "подробности уточняются", "по мере появления", "событие относится", "важно для жителей",
    "система отметила", "детали уточняются", "рельсения", "трансплантирован организм",
    "получитель интерпретировал", "слишком важно не провалиться", "источник сообщения",
    "мировые сми сообщили о новом событии", "международные сми сообщили о новом событии",
]
LOCAL = "сахалин южно-сахалинск южносахалинск холмск корсаков анива невельск оха долинск поронайск углегорск курил курильск южно-курильск северо-курильск".split()
LOCAL_EVENT = "дтп пожар происшествие авария землетрясение магнитуда цунами шторм циклон ураган отключение эвакуация погиб погибли пострадал пострадали задержан задержали розыск мчс мвд полиция прокуратура суд".split()
WORLD_RU = "russia russian moscow kremlin ukraine ukrainian nato sanctions sanction putin lavrov china xi trump россия рф российск москва кремль украина украин нато санкции путин лавров китай си трамп российская нефть российский газ".split()
POL = "кремль песков путин лавров мишустин госдума мид минобороны правительство президент совбез законопроект выборы".split()
ECO = "цб центробанк ставка инфляция рубль бюджет минфин банк нефть газ экономика санкц экспорт импорт рынок oil gas ruble inflation budget economy sanction".split()
GEO = "iran иран israel израиль china китай taiwan тайвань nato нато g7 g20 оон un sanctions санкции ukraine украина war война conflict конфликт oil нефть gas газ usa сша eu ес".split()
IT = "openai anthropic google microsoft apple meta nvidia ai ии искусственный интеллект нейросет llm chip chips semiconductor чип кибератака cyberattack утечка data telegram android ios robot робот".split()
NOISE = "спорт турнир матч рейтинг афиша гороскоп вакансии конкурс фестиваль выставка самокат рецепт кино".split()

STATS = {k: 0 for k in [
    "rss_seen", "old_skip", "google_skip", "duplicate_skip", "low_info_skip", "category_skip",
    "no_image_skip", "bad_image_skip", "candidates", "rewrite_retry", "editorial_skip",
    "telegram_fail", "published"
]}

def log(msg):
    print(f"[{datetime.now(TZ):%Y-%m-%d %H:%M:%S} SAKH] {msg}", flush=True)

def clean(x):
    s = html.unescape(str(x or ""))
    s = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def esc(x): return html.escape(str(x or ""), quote=False)
def attr(x): return html.escape(str(x or ""), quote=True)
def norm(x): return re.sub(r"[^0-9a-zа-яё]+", " ", clean(x).lower()).strip()
def htitle(x): return hashlib.sha1(norm(x).encode()).hexdigest()

def ratio_latin(text):
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return 0.0
    return len([c for c in letters if re.match(r"[A-Za-z]", c)]) / len(letters)

def terms(text, arr):
    t = " " + (text or "").lower() + " "
    return [w for w in arr if w in t]

def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    sa, sb = set(a.split()), set(b.split())
    return len(sa) >= 4 and len(sb) >= 4 and len(sa & sb) / max(1, min(len(sa), len(sb))) > 0.75

def gnews(q, lang="en", country="US"):
    return f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(q)}&hl={lang}&gl={country}&ceid={country}:{lang}"

SOURCES = [
    ("Sakhalin", "sakhalin", gnews("Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Курилы ДТП OR пожар OR происшествие OR землетрясение OR шторм OR авария OR розыск OR отключение", "ru", "RU"), 100),
    ("Interfax", "ru", "https://www.interfax.ru/rss.asp", 78),
    ("Reuters", "world", gnews("site:reuters.com Russia Ukraine sanctions NATO China G7 oil gas"), 96),
    ("AP News", "world", gnews("site:apnews.com Russia Ukraine sanctions NATO China G7 oil gas Iran Israel"), 94),
    ("BBC World", "world", "https://feeds.bbci.co.uk/news/world/rss.xml", 86),
    ("Guardian World", "world", "https://www.theguardian.com/world/rss", 82),
    ("BBC Technology", "it", "https://feeds.bbci.co.uk/news/technology/rss.xml", 80),
    ("Guardian Technology", "it", "https://www.theguardian.com/technology/rss", 76),
    ("Habr", "it", "https://habr.com/ru/rss/articles/", 55),
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

def entry_dt(e):
    for k in ("published_parsed", "updated_parsed"):
        v = e.get(k)
        if v:
            return datetime(*v[:6], tzinfo=timezone.utc)
    for k in ("published", "updated", "created"):
        raw = e.get(k)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(str(raw))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except Exception:
            pass
    return None

def fresh(dt):
    if not dt:
        return True
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(hours=MAX_AGE_HOURS)

def direct_url(e):
    base = clean(e.get("link", ""))
    urls = []
    for raw in (str(e.get("summary", "") or ""), str(e.get("description", "") or "")):
        urls += re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
    for link in e.get("links", []) or []:
        if isinstance(link, dict) and link.get("href"):
            urls.append(str(link["href"]))
    for u in urls:
        u = abs_url(u, base)
        if u and not is_google(u):
            return u
    return abs_url(base) or base

def meta(page, key):
    pats = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for p in pats:
        m = re.search(p, page, re.I)
        if m:
            return html.unescape(m.group(1).strip())
    return None

def iso_dt(x):
    if not x:
        return None
    try:
        dt = datetime.fromisoformat(x.strip().replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        return None

def title_overlap(title, text):
    words = [w for w in norm(title).split() if len(w) >= 5]
    if not words:
        return 0.0
    txt = " " + norm(text) + " "
    return sum(1 for w in words if f" {w} " in txt) / len(words)

def page_info(url):
    if not url or is_google(url):
        return {}
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=30, allow_redirects=True)
        if r.status_code >= 400:
            return {}
        page = r.text[:900000]
        title_m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        title = clean(meta(page, "og:title") or meta(page, "twitter:title") or (title_m.group(1) if title_m else ""))
        desc = clean(meta(page, "og:description") or meta(page, "description") or meta(page, "twitter:description"))
        image = meta(page, "og:image") or meta(page, "twitter:image") or meta(page, "twitter:image:src")
        published = iso_dt(meta(page, "article:published_time") or meta(page, "datePublished") or meta(page, "pubdate"))
        paragraphs = []
        safe = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
        for raw in re.findall(r"<p[^>]*>(.*?)</p>", safe, re.I | re.S):
            p = clean(raw)
            low = p.lower()
            if len(p) < 55:
                continue
            if any(x in low for x in ("cookie", "javascript", "подпис", "реклама", "newsletter", "advertisement")):
                continue
            paragraphs.append(p)
            if len(paragraphs) >= 4:
                break
        article = " ".join(paragraphs)[:1600]
        if title and article and title_overlap(title, article) < 0.10:
            article = ""
        return {
            "url": r.url or url,
            "title": title,
            "desc": desc,
            "image_url": abs_url(image, r.url or url) if image else None,
            "published": published,
            "article": article,
        }
    except Exception as ex:
        log(f"page read failed: {ex}")
        return {}

def rss_image(e, raw, url):
    for k in ("media_thumbnail", "media_content"):
        for item in e.get(k, []) or []:
            if isinstance(item, dict) and item.get("url"):
                u = abs_url(str(item["url"]), url)
                if u:
                    return u
    for link in e.get("links", []) or []:
        if isinstance(link, dict):
            href, typ, rel = str(link.get("href", "")), str(link.get("type", "")), str(link.get("rel", ""))
            if href and ("image" in typ or rel in ("enclosure", "thumbnail")):
                u = abs_url(href, url)
                if u:
                    return u
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw or "", re.I)
    return abs_url(m.group(1), url) if m else None

def source_name(e, fallback):
    src = e.get("source")
    if isinstance(src, dict) and src.get("title"):
        return clean(src["title"])
    try:
        if getattr(src, "title", None):
            return clean(src.title)
    except Exception:
        pass
    return fallback

def classify(src_type, weight, title, rss_text, desc, url):
    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()
    if terms(text, NOISE):
        return None, 0, "noise"
    if src_type == "sakhalin" or terms(text, LOCAL):
        if not terms(text, LOCAL_EVENT) and len(clean(rss_text + " " + desc)) < 150:
            return None, 0, "local_low_signal"
        return "sakh", weight + 30, "local"
    if src_type == "world":
        if terms(text, WORLD_RU):
            return "world_ru", weight + 18, "world_ru"
        if len(terms(text, GEO)) >= 2:
            return "geo", weight + 8, "geo"
        return None, 0, "world_not_relevant"
    if src_type == "it":
        return ("it", weight + 10, "it") if terms(text, IT) else (None, 0, "it_not_relevant")
    if src_type == "ru":
        if "/moscow/" in path:
            return None, 0, "moscow_noise"
        if terms(text, ECO):
            return "ru_eco", weight + 12, "ru_eco"
        if terms(text, POL) or terms(text, WORLD_RU):
            return "ru_pol", weight + 10, "ru_pol"
        return None, 0, "ru_not_relevant"
    return None, 0, "not_relevant"

def image_to_jpeg(image_url):
    if not image_url:
        return None
    try:
        r = requests.get(image_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*;q=0.8"}, timeout=30, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ctype = (r.headers.get("content-type") or "").split(";")[0].lower()
        if not ctype.startswith("image/") or ctype == "image/svg+xml":
            return None
        data = r.content
        if len(data) < 8000 or len(data) > 9500000:
            return None
        with Image.open(BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if w < 280 or h < 160:
                return None
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            if max(im.size) > 1600:
                im.thumbnail((1600, 1600), Image.LANCZOS)
            out = BytesIO()
            im.save(out, format="JPEG", quality=88, optimize=True)
            jpeg = out.getvalue()
            return jpeg if len(jpeg) >= 8000 else None
    except Exception:
        return None

def load_state():
    if not os.path.exists(STATE):
        return {"published_urls": [], "published_title_hashes": [], "last_posts": []}
    with open(STATE, "r", encoding="utf-8") as f:
        s = json.load(f)
    s.setdefault("published_urls", [])
    s.setdefault("published_title_hashes", [])
    s.setdefault("last_posts", [])
    return s

def save_state(s):
    s["published_urls"] = s.get("published_urls", [])[-900:]
    s["published_title_hashes"] = s.get("published_title_hashes", [])[-900:]
    s["last_posts"] = s.get("last_posts", [])[-80:]
    s["last_run_sakhalin"] = datetime.now(TZ).isoformat(timespec="seconds")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def collect(s):
    used_u, used_h = set(s.get("published_urls", [])), set(s.get("published_title_hashes", []))
    out = []
    for name, src_type, rss, weight in SOURCES:
        log(f"Источник: {name}")
        try:
            feed = feedparser.parse(rss)
        except Exception as ex:
            log(f"rss failed: {ex}")
            continue
        for e in feed.entries[:16]:
            STATS["rss_seen"] += 1
            dt = entry_dt(e)
            if not fresh(dt):
                STATS["old_skip"] += 1
                continue
            raw = str(e.get("summary", "") or "")
            rss_text = clean(raw)
            url = direct_url(e)
            if is_google(url):
                STATS["google_skip"] += 1
                continue
            page = page_info(url)
            if page.get("published") and not fresh(page["published"]):
                STATS["old_skip"] += 1
                continue
            title = page.get("title") or clean(e.get("title", ""))
            desc = page.get("desc") or ""
            text = " ".join(x for x in (desc, rss_text, page.get("article")) if x).strip()[:1800]
            url = page.get("url") or url
            if len(clean(title)) < 24 or len(clean(text)) < 140:
                STATS["low_info_skip"] += 1
                continue
            th = htitle(title)
            if url in used_u or th in used_h:
                STATS["duplicate_skip"] += 1
                continue
            cat, score, reason = classify(src_type, weight, title, rss_text, desc, url)
            if not cat:
                STATS["category_skip"] += 1
                continue
            img_url = rss_image(e, raw, url) or page.get("image_url")
            if not img_url:
                STATS["no_image_skip"] += 1
                if IMAGE_REQUIRED:
                    continue
            img = image_to_jpeg(img_url)
            if not img:
                STATS["bad_image_skip"] += 1
                if IMAGE_REQUIRED:
                    continue
            out.append({
                "id": len(out) + 1,
                "source": source_name(e, name),
                "category_key": cat,
                "category": FOOTER[cat][0],
                "footer": FOOTER[cat][1],
                "score": score + (20 if img else 0),
                "reason": reason,
                "title": title,
                "source_text": text,
                "url": url,
                "image_url": img_url,
                "image": img,
                "published_at": (page.get("published") or dt or datetime.now(timezone.utc)).isoformat(),
                "title_hash": th,
            })
    out.sort(key=lambda x: (x["category_key"] != "sakh", -x["score"], x["published_at"]))
    STATS["candidates"] = len(out)
    return out[:50]

def openrouter(messages, max_tokens=1100):
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

def parse_obj(text):
    try:
        v = json.loads(text)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("json object not found")
    return json.loads(text[a:b+1])

def write_prompt(c, error=""):
    data = {"category": c["category"], "footer": c["footer"], "source": c["source"], "title": c["title"], "source_text": c["source_text"], "published_at": c["published_at"]}
    return (
        "Сделай новостной Telegram-пост строго на русском языке.\n"
        "Правила: только факты из title/source_text; ничего не добавляй; английские предложения запрещены; "
        "2-3 абзаца обычным текстом; без списков, без слов «Суть», «Источник», «Что известно»; "
        "если фактов мало — верни reject=true; не добавляй числа, которых нет в исходнике.\n"
        f"Ошибка предыдущей попытки: {error}\n"
        "Верни только JSON: {\"reject\":false,\"title_ru\":\"...\",\"body\":[\"абзац 1\",\"абзац 2\"],\"footer\":\"...\"}\n"
        + json.dumps(data, ensure_ascii=False)
    )

def generate(c, error=""):
    text = openrouter([
        {"role": "system", "content": "Ты профессиональный редактор новостей. Возвращай только валидный JSON. Весь текст строго на русском."},
        {"role": "user", "content": write_prompt(c, error)}
    ])
    row = parse_obj(text)
    row["category"] = c["category"]
    row["footer"] = row.get("footer") or c["footer"]
    return row

def nums(text):
    return set(re.findall(r"\d+(?:[,.]\d+)?", text or ""))

def validate(row, c):
    if row.get("reject") is True:
        return ["model_rejected"]
    title = clean(row.get("title_ru"))
    body = row.get("body") if isinstance(row.get("body"), list) else []
    body = [clean(x) for x in body if clean(x)]
    joined = title + " " + " ".join(body)
    source = c["title"] + " " + c["source_text"]
    errors = []
    if len(title) < 32 or len(title.split()) < 4:
        errors.append("title_too_short")
    if len(body) < 2:
        errors.append("body_too_short")
    if len(joined) < 280:
        errors.append("post_too_short")
    if len(joined) > 1700:
        errors.append("post_too_long")
    if ratio_latin(joined) > 0.10:
        errors.append("latin_ratio_high")
    low = joined.lower()
    for phrase in BAD:
        if phrase in low:
            errors.append("bad_phrase:" + phrase)
    invented = nums(joined) - nums(source)
    if invented:
        errors.append("invented_numbers:" + ",".join(sorted(invented)))
    if re.search(r"\b(the|who|has|said|will|after|before|with|from|this|that|over|under|against|faces|keeps|what|why|how)\b", joined, re.I):
        errors.append("english_words_left")
    if any(len(x) < 70 for x in body):
        errors.append("paragraph_too_short")
    if any(len(x) > 560 for x in body):
        errors.append("paragraph_too_long")
    return errors

def valid_post(c):
    err = ""
    for _ in range(3):
        try:
            row = generate(c, err)
            errors = validate(row, c)
            if not errors:
                return row
            err = "; ".join(errors)
            STATS["rewrite_retry"] += 1
            log(f"rewrite required: {c['title'][:70]} | {err}")
        except Exception as ex:
            err = str(ex)
            STATS["rewrite_retry"] += 1
            log(f"write retry: {c['title'][:70]} | {err}")
    STATS["editorial_skip"] += 1
    return None

def ordered(cands):
    local = [c for c in cands if c["category_key"] == "sakh"]
    other = [c for c in cands if c["category_key"] != "sakh"]
    order = []
    if local:
        order.append(local[0])
    for key in ("world_ru", "ru_pol", "ru_eco", "geo", "it"):
        order += [c for c in other if c["category_key"] == key]
    order += local[1:] + [c for c in cands if c not in order]
    seen = set()
    uniq = []
    for c in order:
        marker = (c["url"], c["title_hash"])
        if marker in seen:
            continue
        seen.add(marker)
        uniq.append(c)
    return uniq

def caption(row, c):
    title = clean(row.get("title_ru"))
    body = [clean(x) for x in row.get("body", []) if clean(x)]
    url = c["url"]
    text = f"{esc(c['category'])}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(c['footer'])} · <a href=\"{attr(url)}\">{esc(c['source'])}</a>"
    if len(text) <= 1024:
        return text
    body = [x[:350].rstrip() + ("…" if len(x) > 350 else "") for x in body[:2]]
    return (f"{esc(c['category'])}\n\n<b>{esc(title[:220])}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(c['footer'])} · <a href=\"{attr(url)}\">{esc(c['source'])}</a>")[:1024]

def send_photo(c, cap):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    if not c.get("image"):
        raise RuntimeError("image_missing")
    files = {"photo": ("news.jpg", c["image"], "image/jpeg")}
    payload = {"chat_id": chat, "caption": cap, "parse_mode": "HTML"}
    r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data=payload, files=files, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(r.text[:700])
    return r.json()

def report():
    log("=== REPORT ===")
    for k in sorted(STATS):
        log(f"{k}: {STATS[k]}")

def main():
    state = load_state()
    log("Сбор кандидатов")
    cands = collect(state)
    log(f"Кандидатов после строгого фильтра: {len(cands)}")
    if not cands:
        report()
        save_state(state)
        return
    published = 0
    for c in ordered(cands):
        if published >= POSTS_PER_RUN:
            break
        if c["url"] in state.get("published_urls", []):
            continue
        row = valid_post(c)
        if not row:
            log(f"candidate skipped by editor: {c['title'][:90]}")
            continue
        try:
            cap = caption(row, c)
            log(f"publish photo-card: {c['category']} | {c['source']} | {c['title'][:90]}")
            result = send_photo(c, cap)
        except Exception as ex:
            STATS["telegram_fail"] += 1
            log(f"telegram failed: {c['title'][:90]} | {ex}")
            continue
        if result.get("ok"):
            state.setdefault("published_urls", []).append(c["url"])
            state.setdefault("published_title_hashes", []).append(c["title_hash"])
            state.setdefault("last_posts", []).append({
                "time_sakhalin": datetime.now(TZ).isoformat(timespec="seconds"),
                "source": c["source"],
                "category": c["category"],
                "title": row.get("title_ru") or c["title"],
                "url": c["url"],
                "published_at": c.get("published_at"),
                "with_image": True,
                "publish_method": "sendPhoto/uploaded_jpeg",
            })
            published += 1
            STATS["published"] = published
            time.sleep(12)
    log(f"Опубликовано: {published}")
    report()
    save_state(state)

if __name__ == "__main__":
    main()
