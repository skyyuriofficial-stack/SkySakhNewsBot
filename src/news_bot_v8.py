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

BAD_TEXT = ["подробности уточняются", "по мере появления", "событие относится", "важно для жителей", "система отметила", "детали уточняются", "источник сообщения", "рельсения", "трансплантирован организм", "получитель интерпретировал", "слишком важно не провалиться", "мировые сми сообщили о новом событии", "мошенники угрожали задержкой", "потеря 13,3 млн рублей"]
BAD_IMAGE_WORDS = ["logo", "logotype", "brand", "banner", "header", "footer", "sprite", "icon", "favicon", "placeholder", "default", "avatar", "profile", "share", "social", "promo", "stub", "логотип", "баннер", "заглушка", "иконка"]
NOISE = "спорт турнир матч рейтинг афиша гороскоп вакансии конкурс фестиваль выставка самокат рецепт кино теннис футбол баскетбол".split()
LOCAL = "сахалин южно-сахалинск южносахалинск холмск корсаков анива невельск оха долинск поронайск углегорск тымовское курил курильск южно-курильск северо-курильск итуруп кунашир".split()
QUAKE = "землетрясение землетрясения магнитуда магнитудой сейсмик сейсмологи эпицентр толчки цунами".split()
LOCAL_EVENT = "дтп пожар происшествие авария шторм циклон ураган отключение эвакуация погиб погибли пострадал пострадали задержан задержали розыск мчс мвд полиция прокуратура суд".split() + QUAKE
WORLD_RU = "russia russian moscow kremlin ukraine ukrainian nato sanctions sanction putin lavrov china xi trump россия рф российск москва кремль украина украин нато санкции путин лавров китай си трамп российская нефть российский газ".split()
POL = "кремль песков путин лавров мишустин госдума мид минобороны правительство президент совбез законопроект выборы".split()
ECO = "цб центробанк ставка инфляция рубль бюджет минфин банк нефть газ экономика санкц экспорт импорт рынок oil gas ruble inflation budget economy sanction".split()
GEO = "iran иран israel израиль china китай taiwan тайвань nato нато g7 g20 оон un sanctions санкции ukraine украина war война conflict конфликт oil нефть gas газ usa сша eu ес".split()
IT = "openai anthropic google microsoft apple meta nvidia ai ии искусственный интеллект нейросет llm chip chips semiconductor чип кибератака cyberattack утечка data telegram android ios robot робот".split()

CAT = {
    "sakh_quake": ("📍 Сахалин", "САХАЛИН | СЕЙСМИКА"),
    "sakh_chp": ("📍 Сахалин", "ЧП | САХАЛИН"),
    "sakh": ("📍 Сахалин", "САХАЛИН"),
    "world_ru": ("🌍 Мир о России", "МИР О РОССИИ"),
    "ru_pol": ("🇷🇺 Россия / политика", "РОССИЯ | ПОЛИТИКА"),
    "ru_eco": ("🇷🇺 Россия / экономика", "РОССИЯ | ЭКОНОМИКА"),
    "geo": ("🧭 Геополитика", "МИР | ГЕОПОЛИТИКА"),
    "it": ("💻 IT / технологии", "IT | ТЕХНОЛОГИИ"),
}

STATS = {k: 0 for k in ["rss_seen", "old_skip", "google_skip", "duplicate_skip", "low_info_skip", "category_skip", "no_image_skip", "bad_image_skip", "logo_image_skip", "text_card_image_skip", "candidates", "rewrite_retry", "editorial_skip", "telegram_fail", "published"]}

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
    return 0.0 if not letters else len([c for c in letters if re.match(r"[A-Za-z]", c)]) / len(letters)

def terms(text, arr):
    t = " " + (text or "").lower() + " "
    return [w for w in arr if w in t]

def too_similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return False
    if a == b or a in b or b in a: return True
    sa, sb = set(a.split()), set(b.split())
    return len(sa) >= 4 and len(sb) >= 4 and len(sa & sb) / max(1, min(len(sa), len(sb))) > 0.75

def gnews(q, lang="en", country="US"):
    return f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(q)}&hl={lang}&gl={country}&ceid={country}:{lang}"

SOURCES = [
    ("Sakhalin Google", "sakhalin", gnews("Сахалин OR Южно-Сахалинск OR Холмск OR Корсаков OR Курилы ДТП OR пожар OR происшествие OR землетрясение OR шторм OR авария OR розыск OR отключение", "ru", "RU"), 100),
    ("ASTV", "sakhalin", "https://astv.ru/rss/news", 105),
    ("SakhalinMedia", "sakhalin", "https://sakhalinmedia.ru/rss/", 102),
    ("Sakh.online", "sakhalin", "https://sakh.online/rss/", 100),
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
    if not url: return None
    url = html.unescape(str(url).strip())
    if url.startswith("//"): url = "https:" + url
    if base and url.startswith("/"): url = urllib.parse.urljoin(base, url)
    return url if url.startswith(("http://", "https://")) else None

def entry_dt(e):
    for k in ("published_parsed", "updated_parsed"):
        v = e.get(k)
        if v: return datetime(*v[:6], tzinfo=timezone.utc)
    for k in ("published", "updated", "created"):
        raw = e.get(k)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
            except Exception:
                pass
    return None

def fresh(dt):
    if not dt: return True
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(hours=MAX_AGE_HOURS)

def direct_url(e):
    base = clean(e.get("link", ""))
    urls = []
    for raw in (str(e.get("summary", "") or ""), str(e.get("description", "") or "")):
        urls += re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I)
    for link in e.get("links", []) or []:
        if isinstance(link, dict) and link.get("href"): urls.append(str(link["href"]))
    for u in urls:
        u = abs_url(u, base)
        if u and not is_google(u): return u
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
        if m: return html.unescape(m.group(1).strip())
    return None

def iso_dt(x):
    if not x: return None
    try:
        dt = datetime.fromisoformat(x.strip().replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        return None

def title_overlap(title, text):
    words = [w for w in norm(title).split() if len(w) >= 5]
    if not words: return 0.0
    txt = " " + norm(text) + " "
    return sum(1 for w in words if f" {w} " in txt) / len(words)

def pick_srcset(srcset, base):
    best, best_w = None, -1
    for part in srcset.split(","):
        chunks = part.strip().split()
        if not chunks: continue
        u = abs_url(chunks[0], base)
        if not u: continue
        w = 0
        if len(chunks) > 1:
            m = re.search(r"(\d+)w", chunks[1])
            if m: w = int(m.group(1))
        if w >= best_w: best, best_w = u, w
    return best

def img_candidates_from_html(page, base):
    out, seen = [], set()
    safe = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
    article = re.search(r"<article[^>]*>(.*?)</article>", safe, re.I | re.S)
    scopes = [("article", article.group(1) if article else safe[:500000]), ("page", safe[:500000])]
    for scope_name, scope in scopes:
        for m in re.finditer(r"<img\b[^>]*>", scope, re.I | re.S):
            tag = m.group(0)
            src = None
            ss = re.search(r'\bsrcset=["\']([^"\']+)["\']', tag, re.I)
            if ss: src = pick_srcset(ss.group(1), base)
            if not src:
                sm = re.search(r'\b(?:src|data-src|data-original|data-lazy-src)=["\']([^"\']+)["\']', tag, re.I)
                if sm: src = abs_url(sm.group(1), base)
            if not src or src in seen: continue
            seen.add(src)
            alt = ""
            am = re.search(r'\b(?:alt|title)=["\']([^"\']*)["\']', tag, re.I)
            if am: alt = clean(am.group(1))
            ctx = clean(scope[max(0, m.start()-350):m.end()+350])
            out.append({"url": src, "source": scope_name, "context": (alt + " " + ctx)[:900]})
    return out

def page_info(url):
    if not url or is_google(url): return {}
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=30, allow_redirects=True)
        if r.status_code >= 400: return {}
        page, final_url = r.text[:1000000], r.url or url
        title_m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        title = clean(meta(page, "og:title") or meta(page, "twitter:title") or (title_m.group(1) if title_m else ""))
        desc = clean(meta(page, "og:description") or meta(page, "description") or meta(page, "twitter:description"))
        published = iso_dt(meta(page, "article:published_time") or meta(page, "datePublished") or meta(page, "pubdate"))
        safe = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
        paragraphs = []
        for raw in re.findall(r"<p[^>]*>(.*?)</p>", safe, re.I | re.S):
            p, low = clean(raw), clean(raw).lower()
            if len(p) < 55 or any(x in low for x in ("cookie", "javascript", "подпис", "реклама", "newsletter", "advertisement")): continue
            paragraphs.append(p)
            if len(paragraphs) >= 4: break
        article = " ".join(paragraphs)[:1700]
        if title and article and title_overlap(title, article) < 0.10: article = ""
        imgs = img_candidates_from_html(page, final_url)
        for key in ("og:image", "twitter:image", "twitter:image:src"):
            img = meta(page, key)
            u = abs_url(img, final_url) if img else None
            if u: imgs.append({"url": u, "source": "og", "context": title + " " + desc})
        return {"url": final_url, "title": title, "desc": desc, "published": published, "article": article, "images": imgs}
    except Exception as ex:
        log(f"page read failed: {ex}")
        return {}

def rss_images(e, raw, url):
    out = []
    for k in ("media_thumbnail", "media_content"):
        for item in e.get(k, []) or []:
            if isinstance(item, dict) and item.get("url"):
                u = abs_url(str(item["url"]), url)
                if u: out.append({"url": u, "source": "rss", "context": clean(raw)[:600]})
    for link in e.get("links", []) or []:
        if isinstance(link, dict):
            href, typ, rel = str(link.get("href", "")), str(link.get("type", "")), str(link.get("rel", ""))
            if href and ("image" in typ or rel in ("enclosure", "thumbnail")):
                u = abs_url(href, url)
                if u: out.append({"url": u, "source": "rss", "context": clean(raw)[:600]})
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', raw or "", re.I):
        u = abs_url(m.group(1), url)
        if u: out.append({"url": u, "source": "rss", "context": clean(raw)[:600]})
    return out

def source_name(e, fallback):
    src = e.get("source")
    if isinstance(src, dict) and src.get("title"): return clean(src["title"])
    try:
        if getattr(src, "title", None): return clean(src.title)
    except Exception: pass
    return fallback

def classify(src_type, weight, title, rss_text, desc, url):
    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()
    if terms(text, NOISE): return None, 0, "noise"
    is_local = src_type == "sakhalin" or bool(terms(text, LOCAL))
    if is_local:
        if terms(text, QUAKE): return "sakh_quake", weight + 36, "local_quake"
        if terms(text, LOCAL_EVENT): return "sakh_chp", weight + 32, "local_chp"
        if len(clean(rss_text + " " + desc)) >= 180: return "sakh", weight + 18, "local_general"
        return None, 0, "local_low_signal"
    if src_type == "world":
        if terms(text, WORLD_RU): return "world_ru", weight + 18, "world_ru"
        if len(terms(text, GEO)) >= 2: return "geo", weight + 8, "geo"
        return None, 0, "world_not_relevant"
    if src_type == "it": return ("it", weight + 10, "it") if terms(text, IT) else (None, 0, "it_not_relevant")
    if src_type == "ru":
        if "/moscow/" in path: return None, 0, "moscow_noise"
        if terms(text, QUAKE) and terms(text, LOCAL): return "sakh_quake", weight + 20, "ru_local_quake"
        if terms(text, ECO): return "ru_eco", weight + 12, "ru_eco"
        if terms(text, POL) or terms(text, WORLD_RU): return "ru_pol", weight + 10, "ru_pol"
        return None, 0, "ru_not_relevant"
    return None, 0, "not_relevant"

def image_priority(cand, title):
    score = {"article": 100, "rss": 85, "page": 65, "og": 35}.get(cand.get("source", ""), 20)
    ctx = norm(cand.get("context", ""))
    for w in [w for w in norm(title).split() if len(w) >= 5][:6]:
        if f" {w} " in f" {ctx} ": score += 5
    return score

def image_to_jpeg(cand, title):
    url = cand.get("url", "")
    probe = " ".join([url, cand.get("context", ""), cand.get("source", "")]).lower()
    if any(w in probe for w in BAD_IMAGE_WORDS): return None, "logo_word"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*;q=0.8"}, timeout=30, allow_redirects=True)
        if r.status_code >= 400: return None, "http"
        ctype = (r.headers.get("content-type") or "").split(";")[0].lower()
        if not ctype.startswith("image/") or ctype == "image/svg+xml": return None, "content_type"
        data = r.content
        if len(data) < 10000 or len(data) > 9500000: return None, "size"
        with Image.open(BytesIO(data)) as im0:
            im0 = ImageOps.exif_transpose(im0)
            w, h = im0.size
            if w < 360 or h < 220: return None, "dimensions"
            aspect = w / max(1, h)
            if aspect > 2.35 or aspect < 0.38: return None, "banner_aspect"
            im = im0.convert("RGB")
            small = im.resize((96, 96))
            entropy = small.convert("L").entropy()
            pal = small.convert("P", palette=Image.ADAPTIVE, colors=64)
            colors = pal.getcolors(maxcolors=10000) or []
            dominant = max([c for c, _ in colors], default=0) / (96 * 96)
            color_count = len(colors)
            if entropy < 4.25 or color_count < 18: return None, "flat_graphic"
            if dominant > 0.48 and entropy < 5.35: return None, "text_card_like"
            if cand.get("source") == "og" and dominant > 0.38 and entropy < 5.15: return None, "og_card_like"
            if max(im.size) > 1600: im.thumbnail((1600, 1600), Image.LANCZOS)
            out = BytesIO(); im.save(out, format="JPEG", quality=88, optimize=True)
            jpeg = out.getvalue()
            return (jpeg, "ok") if len(jpeg) >= 10000 else (None, "encoded_small")
    except Exception:
        return None, "exception"

def select_image(cands, title):
    seen, ranked = set(), []
    for c in cands:
        u = c.get("url")
        if u and u not in seen:
            seen.add(u); ranked.append(c)
    ranked.sort(key=lambda c: image_priority(c, title), reverse=True)
    last = "none"
    for c in ranked[:12]:
        img, reason = image_to_jpeg(c, title)
        if img: return img, c.get("url"), "ok"
        last = reason
        if reason == "logo_word": STATS["logo_image_skip"] += 1
        if reason in ("flat_graphic", "text_card_like", "og_card_like"): STATS["text_card_image_skip"] += 1
    return None, None, last

def load_state():
    if not os.path.exists(STATE): return {"published_urls": [], "published_title_hashes": [], "last_posts": []}
    with open(STATE, "r", encoding="utf-8") as f: s = json.load(f)
    s.setdefault("published_urls", []); s.setdefault("published_title_hashes", []); s.setdefault("last_posts", [])
    return s

def save_state(s):
    s["published_urls"] = s.get("published_urls", [])[-900:]
    s["published_title_hashes"] = s.get("published_title_hashes", [])[-900:]
    s["last_posts"] = s.get("last_posts", [])[-80:]
    s["last_run_sakhalin"] = datetime.now(TZ).isoformat(timespec="seconds")
    with open(STATE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=2)

def collect(state):
    used_u, used_h = set(state.get("published_urls", [])), set(state.get("published_title_hashes", []))
    out = []
    for name, src_type, rss, weight in SOURCES:
        log(f"Источник: {name}")
        try: feed = feedparser.parse(rss)
        except Exception as ex:
            log(f"rss failed: {name}: {ex}"); continue
        for e in feed.entries[:16]:
            STATS["rss_seen"] += 1
            dt = entry_dt(e)
            if not fresh(dt): STATS["old_skip"] += 1; continue
            raw = str(e.get("summary", "") or "")
            rss_text = clean(raw)
            url = direct_url(e)
            if is_google(url): STATS["google_skip"] += 1; continue
            page = page_info(url)
            if page.get("published") and not fresh(page["published"]): STATS["old_skip"] += 1; continue
            title = page.get("title") or clean(e.get("title", ""))
            desc = page.get("desc") or ""
            text = " ".join(x for x in (desc, rss_text, page.get("article")) if x).strip()[:1800]
            url = page.get("url") or url
            if len(clean(title)) < 24 or len(clean(text)) < 140: STATS["low_info_skip"] += 1; continue
            th = htitle(title)
            if url in used_u or th in used_h: STATS["duplicate_skip"] += 1; continue
            cat, score, reason = classify(src_type, weight, title, rss_text, desc, url)
            if not cat: STATS["category_skip"] += 1; continue
            image, image_url, image_reason = select_image(rss_images(e, raw, url) + page.get("images", []), title)
            if not image:
                STATS["bad_image_skip"] += 1
                log(f"skip bad image: {title[:80]} | {image_reason}")
                if IMAGE_REQUIRED: continue
            category, footer = CAT[cat]
            out.append({"id": len(out)+1, "source": source_name(e, name), "category_key": cat, "category": category, "footer": footer, "score": score + (20 if image else 0), "reason": reason, "title": title, "source_text": text, "url": url, "image_url": image_url, "image": image, "published_at": (page.get("published") or dt or datetime.now(timezone.utc)).isoformat(), "title_hash": th})
    out.sort(key=lambda x: (x["category_key"] not in ("sakh_quake", "sakh_chp", "sakh"), -x["score"], x["published_at"]))
    STATS["candidates"] = len(out)
    return out[:50]

def openrouter(messages, max_tokens=1100):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key: raise RuntimeError("OPENROUTER_API_KEY is missing")
    r = requests.post(OPENROUTER_URL, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "HTTP-Referer": "https://t.me/SkySakhNews", "X-OpenRouter-Title": "SkySakhNews"}, json={"model": MODEL, "messages": messages, "temperature": 0.02, "max_tokens": max_tokens}, timeout=90)
    if r.status_code >= 400: raise RuntimeError(r.text[:700])
    return r.json()["choices"][0]["message"]["content"].strip()

def parse_obj(text):
    try:
        v = json.loads(text)
        if isinstance(v, dict): return v
    except Exception: pass
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a: raise ValueError("json object not found")
    return json.loads(text[a:b+1])

def write_prompt(c, error=""):
    data = {"category": c["category"], "footer": c["footer"], "source": c["source"], "title": c["title"], "source_text": c["source_text"], "published_at": c["published_at"]}
    return "Сделай новостной Telegram-пост строго на русском языке. Правила: только факты из title/source_text; ничего не добавляй; английские предложения запрещены; 2-3 абзаца обычным текстом; без списков, без слов «Суть», «Источник», «Что известно»; если фактов мало — верни reject=true; не добавляй числа, которых нет в исходнике. Ошибка предыдущей попытки: " + error + "\nВерни только JSON: {\"reject\":false,\"title_ru\":\"...\",\"body\":[\"абзац 1\",\"абзац 2\"],\"footer\":\"...\"}\n" + json.dumps(data, ensure_ascii=False)

def generate(c, error=""):
    text = openrouter([{"role": "system", "content": "Ты профессиональный редактор новостей. Возвращай только валидный JSON. Весь текст строго на русском."}, {"role": "user", "content": write_prompt(c, error)}])
    row = parse_obj(text)
    row["category"] = c["category"]; row["footer"] = row.get("footer") or c["footer"]
    return row

def nums(text): return set(re.findall(r"\d+(?:[,.]\d+)?", text or ""))

def validate(row, c):
    if row.get("reject") is True: return ["model_rejected"]
    title = clean(row.get("title_ru")); body = row.get("body") if isinstance(row.get("body"), list) else []
    body = [clean(x) for x in body if clean(x)]
    joined = title + " " + " ".join(body); source = c["title"] + " " + c["source_text"]
    errors = []
    if len(title) < 32 or len(title.split()) < 4: errors.append("title_too_short")
    if len(body) < 2: errors.append("body_too_short")
    if len(joined) < 280: errors.append("post_too_short")
    if len(joined) > 1700: errors.append("post_too_long")
    if ratio_latin(joined) > 0.10: errors.append("latin_ratio_high")
    low = joined.lower()
    for phrase in BAD_TEXT:
        if phrase in low: errors.append("bad_phrase:" + phrase)
    invented = nums(joined) - nums(source)
    if invented: errors.append("invented_numbers:" + ",".join(sorted(invented)))
    if re.search(r"\b(the|who|has|said|will|after|before|with|from|this|that|over|under|against|faces|keeps|what|why|how)\b", joined, re.I): errors.append("english_words_left")
    if any(len(x) < 70 for x in body): errors.append("paragraph_too_short")
    if any(len(x) > 560 for x in body): errors.append("paragraph_too_long")
    return errors

def valid_post(c):
    err = ""
    for _ in range(3):
        try:
            row = generate(c, err); errors = validate(row, c)
            if not errors: return row
            err = "; ".join(errors); STATS["rewrite_retry"] += 1; log(f"rewrite required: {c['title'][:70]} | {err}")
        except Exception as ex:
            err = str(ex); STATS["rewrite_retry"] += 1; log(f"write retry: {c['title'][:70]} | {err}")
    STATS["editorial_skip"] += 1
    return None

def ordered(cands):
    local = [c for c in cands if c["category_key"] in ("sakh_quake", "sakh_chp", "sakh")]
    other = [c for c in cands if c not in local]
    out = (local[:1] if local else [])
    for key in ("world_ru", "ru_pol", "ru_eco", "geo", "it"): out += [c for c in other if c["category_key"] == key]
    out += local[1:] + [c for c in cands if c not in out]
    seen, uniq = set(), []
    for c in out:
        marker = (c["url"], c["title_hash"])
        if marker not in seen: seen.add(marker); uniq.append(c)
    return uniq

def caption(row, c):
    title = clean(row.get("title_ru")); body = [clean(x) for x in row.get("body", []) if clean(x)]; url = c["url"]
    text = f"{esc(c['category'])}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(c['footer'])} · <a href=\"{attr(url)}\">{esc(c['source'])}</a>"
    if len(text) <= 1024: return text
    body = [x[:350].rstrip() + ("…" if len(x) > 350 else "") for x in body[:2]]
    return (f"{esc(c['category'])}\n\n<b>{esc(title[:220])}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(c['footer'])} · <a href=\"{attr(url)}\">{esc(c['source'])}</a>")[:1024]

def send_photo(c, cap):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip(); chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat: raise RuntimeError("Telegram secrets missing")
    if not c.get("image"): raise RuntimeError("image_missing")
    r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id": chat, "caption": cap, "parse_mode": "HTML"}, files={"photo": ("news.jpg", c["image"], "image/jpeg")}, timeout=90)
    if r.status_code >= 400: raise RuntimeError(r.text[:700])
    return r.json()

def report():
    log("=== REPORT ===")
    for k in sorted(STATS): log(f"{k}: {STATS[k]}")

def main():
    state = load_state(); log("Сбор кандидатов")
    cands = collect(state); log(f"Кандидатов после строгого фильтра: {len(cands)}")
    published = 0
    for c in ordered(cands):
        if published >= POSTS_PER_RUN: break
        if c["url"] in state.get("published_urls", []): continue
        row = valid_post(c)
        if not row: log(f"candidate skipped by editor: {c['title'][:90]}"); continue
        try:
            cap = caption(row, c); log(f"publish photo-card: {c['category']} | {c['source']} | {c['title'][:90]}")
            result = send_photo(c, cap)
        except Exception as ex:
            STATS["telegram_fail"] += 1; log(f"telegram failed: {c['title'][:90]} | {ex}"); continue
        if result.get("ok"):
            state.setdefault("published_urls", []).append(c["url"]); state.setdefault("published_title_hashes", []).append(c["title_hash"])
            state.setdefault("last_posts", []).append({"time_sakhalin": datetime.now(TZ).isoformat(timespec="seconds"), "source": c["source"], "category": c["category"], "title": row.get("title_ru") or c["title"], "url": c["url"], "published_at": c.get("published_at"), "with_image": True, "publish_method": "sendPhoto/uploaded_jpeg"})
            published += 1; STATS["published"] = published; time.sleep(12)
    log(f"Опубликовано: {published}"); report(); save_state(state)

if __name__ == "__main__": main()
