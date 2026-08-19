# SkySakhNews stable production overlay over v8.
# Single production policy layer. Do not stack additional publisher versions on top.

import json
import re
import time
import hashlib
import html
import urllib.parse
from datetime import datetime, timezone

import requests
import feedparser
import news_bot_v8 as b

VERSION = "stable-v9.5"

# Quality beats decorative completeness: a safe text post is better than a wrong image.
b.IMAGE_REQUIRED = False

# Keep only reliable RSS feeds here. Sites without a reliable RSS are collected through
# first-party HTML adapters below.
_sources = []
for name, src_type, url, weight in b.SOURCES:
    if name in ("Habr", "ASTV", "Sakh.online"):
        continue
    if name == "SakhalinMedia":
        url = "https://sakhalinmedia.ru/export/new/news64.rss"
    _sources.append((name, src_type, url, weight))
b.SOURCES = _sources

if not any(s[0] == "TASS" for s in b.SOURCES):
    b.SOURCES.append(("TASS", "ru", "https://tass.ru/rss/v2.xml", 98))

ASTV_NEWS_URL = "https://astv.ru/news"
SAKH_NEWS_URL = "https://sakh.online/news"

b.CAT["ru_security"] = ("🇷🇺 Россия / безопасность", "РОССИЯ | БЕЗОПАСНОСТЬ")

RUSSIA_MARKERS = [
    "russia", "russian", "moscow", "kremlin", "putin", "lavrov",
    "россия", "россии", "россию", "россией", "рф", "российск",
    "москва", "кремль", "путин", "лавров",
]
GEO_MARKERS = [
    "iran", "иран", "israel", "израиль", "usa", "u.s.", "сша", "america", "американ",
    "trump", "трамп", "nato", "нато", "china", "китай", "taiwan", "тайвань", "g7", "g20",
    "war", "война", "conflict", "конфликт", "strike", "attack", "удар", "удары",
    "missile", "ракета", "drone", "дрон", "military", "военн", "base", "база",
    "air defense", "пво", "sanctions", "санкц", "oil", "нефть", "gas", "газ",
    "middle east", "ближн", "йемен", "yemen",
]
SECURITY_MARKERS = [
    "беспилот", "бпла", "дрон", "дроны", "пво", "минобороны", "атака", "атаковали",
    "угроза", "опасность", "воздушная опасность", "режим опасности", "аэропорт",
    "аэропорты", "росавиация", "воздушное судно", "ограничения", "план ковер",
    "всу", "обломки", "ракета", "ракет", "перехват", "сбили", "сбит",
]
IT_STRICT = [
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini", "google", "microsoft",
    "apple", "meta", "nvidia", "amd", "intel", "tsmc", "semiconductor", "chip", "chips",
    "cyberattack", "cybersecurity", "ransomware", "malware", "android", "ios", "linux",
    "windows", "telegram", "artificial intelligence", "llm", "neural network",
    "ии", "нейросет", "искусственный интеллект", "кибератак", "кибербезопас",
    "утечка данных", "чип", "процессор", "видеокарт", "сервер", "программирован",
    "разработчик", "софт", "приложение", "операционная система",
]

GOOGLE_BAD_HOST_PARTS = (
    "google.", "googleusercontent.", "gstatic.", "youtube.", "youtu.be",
    "accounts.google", "support.google", "policies.google",
)


def hit(text, term):
    raw = (text or "").lower()
    t = term.lower().strip()
    if not t:
        return False
    if " " in t or "-" in t:
        return t in raw
    if re.fullmatch(r"[a-z0-9.]{1,4}", t):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw))
    if re.fullmatch(r"[a-z0-9.]+", t):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", raw))
    return t in raw


def hits(text, markers):
    return [m for m in markers if hit(text, m)]


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------
_old_fresh = b.fresh


def strict_fresh(dt):
    # An unknown publication date is not evidence of freshness.
    if dt is None:
        return False
    try:
        return _old_fresh(dt)
    except Exception:
        return False


b.fresh = strict_fresh


# ---------------------------------------------------------------------------
# Direct-link integrity for Google News wrappers
# ---------------------------------------------------------------------------
def _host(url):
    try:
        return urllib.parse.urlparse(url or "").netloc.lower().split(":")[0]
    except Exception:
        return ""


def _is_external_http(url):
    if not url or not url.startswith(("http://", "https://")):
        return False
    host = _host(url)
    return bool(host) and not any(x in host for x in GOOGLE_BAD_HOST_PARTS)


def _source_href(entry):
    src = entry.get("source")
    if isinstance(src, dict):
        return str(src.get("href") or "")
    try:
        return str(getattr(src, "href", "") or "")
    except Exception:
        return ""


def _same_site(a, b_url):
    a_host, b_host = _host(a), _host(b_url)
    if not a_host or not b_host:
        return False
    a_host = a_host.removeprefix("www.")
    b_host = b_host.removeprefix("www.")
    return a_host == b_host or a_host.endswith("." + b_host) or b_host.endswith("." + a_host)


def resolve_google_wrapper(url, source_href=""):
    """Best-effort resolver. A Google wrapper is never returned as a publishable URL."""
    if not url or not b.is_google(url):
        return url

    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"},
            timeout=25,
            allow_redirects=True,
        )
    except Exception:
        return None

    final_url = r.url or ""
    if _is_external_http(final_url):
        if not source_href or _same_site(final_url, source_href):
            return final_url

    page = html.unescape(r.text[:900000])
    raw_candidates = []
    for m in re.finditer(r'(?:href|data-n-au)=["\']([^"\']+)["\']', page, re.I):
        raw_candidates.append(m.group(1))
    raw_candidates += re.findall(r'https?://[^\s"\'<>\\]+', page, flags=re.I)

    candidates = []
    seen = set()
    source_host = _host(source_href)

    for raw in raw_candidates:
        raw = html.unescape(raw).replace("\\u0026", "&").replace("\\/", "/")
        u = urllib.parse.urljoin(final_url or url, raw)

        if b.is_google(u):
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
                nested = (q.get("url") or q.get("q") or [None])[0]
                if nested:
                    u = urllib.parse.unquote(nested)
            except Exception:
                pass

        if not _is_external_http(u):
            continue
        if source_href and not _same_site(u, source_href):
            continue

        p = urllib.parse.urlparse(u)
        if p.path in ("", "/"):
            continue
        if re.search(r"\.(?:jpg|jpeg|png|gif|webp|svg|css|js|pdf)(?:$|\?)", p.path, re.I):
            continue

        u = urllib.parse.urlunparse((p.scheme, p.netloc, p.path, p.params, p.query, ""))
        if u in seen:
            continue
        seen.add(u)

        score = min(len(p.path), 120)
        if source_host and _same_site(u, source_href):
            score += 250
        candidates.append((score, u))

    return max(candidates, default=(0, None))[1]


def _resolved_title_matches(entry, resolved):
    """Reject a resolved URL if its page title is not recognisably the RSS story."""
    rss_title = b.clean(entry.get("title", ""))
    if not rss_title or not resolved:
        return False
    page = b.page_info(resolved)
    page_title = b.clean(page.get("title"))
    if not page_title:
        return False
    return b.title_overlap(rss_title, page_title) >= 0.28 or b.too_similar(rss_title, page_title)


def direct_url_v95(entry):
    base = b.clean(entry.get("link", ""))
    raw_blocks = (
        str(entry.get("summary", "") or ""),
        str(entry.get("description", "") or ""),
    )

    for raw in raw_blocks:
        for u in re.findall(r'href=["\']([^"\']+)["\']', raw, flags=re.I):
            u = b.abs_url(u, base)
            if u and not b.is_google(u):
                return u

    for link in entry.get("links", []) or []:
        if isinstance(link, dict):
            u = b.abs_url(link.get("href"), base)
            if u and not b.is_google(u):
                return u

    if base and not b.is_google(base):
        return b.abs_url(base) or base

    resolved = resolve_google_wrapper(base, _source_href(entry))
    if not resolved:
        return base
    if not _resolved_title_matches(entry, resolved):
        b.log("Google resolver title mismatch -> skip wrapper")
        return base
    return resolved


b.direct_url = direct_url_v95


# ---------------------------------------------------------------------------
# Classification: source type first, then geography/event
# ---------------------------------------------------------------------------
def classify(src_type, weight, title, rss_text, desc, url):
    text = f"{title} {rss_text} {desc}".lower()
    path = urllib.parse.urlparse(url or "").path.lower()

    if b.terms(text, b.NOISE):
        return None, 0, "noise"

    if src_type == "it":
        return ("it", weight + 10, "it_strict") if hits(text, IT_STRICT) else (None, 0, "it_not_relevant")

    if src_type == "sakhalin":
        if b.terms(text, b.QUAKE):
            return "sakh_quake", weight + 36, "local_quake"
        if b.terms(text, b.LOCAL_EVENT):
            return "sakh_chp", weight + 32, "local_chp"
        if b.terms(text, b.LOCAL) or len(b.clean(rss_text + " " + desc)) >= 140:
            return "sakh", weight + 18, "local_general"
        return None, 0, "local_low_signal"

    if src_type == "world":
        if hits(text, RUSSIA_MARKERS):
            return "world_ru", weight + 20, "world_about_russia"
        if len(set(hits(text, GEO_MARKERS))) >= 2:
            return "geo", weight + 10, "geo"
        return None, 0, "world_not_in_stream"

    if src_type == "ru":
        if "/moscow/" in path:
            return None, 0, "moscow_noise"

        if b.terms(text, b.LOCAL):
            if b.terms(text, b.QUAKE):
                return "sakh_quake", weight + 24, "ru_local_quake"
            if b.terms(text, b.LOCAL_EVENT):
                return "sakh_chp", weight + 20, "ru_local_chp"
            return "sakh", weight + 12, "ru_local"

        if hits(text, SECURITY_MARKERS):
            return "ru_security", weight + 18, "ru_security"
        if b.terms(text, b.ECO):
            return "ru_eco", weight + 12, "ru_eco"
        if b.terms(text, b.POL) or hits(text, RUSSIA_MARKERS):
            return "ru_pol", weight + 10, "ru_pol"
        if len(set(hits(text, GEO_MARKERS))) >= 2:
            return "geo", weight + 6, "ru_geo"
        return None, 0, "ru_not_in_stream"

    return None, 0, "unknown_source_type"


b.classify = classify


# ---------------------------------------------------------------------------
# Images: semantic relevance + quality + duplicate protection
# ---------------------------------------------------------------------------
def select_image_v95(cands, title):
    seen = set()
    ranked = []
    for c in cands:
        u = c.get("url")
        if u and u not in seen:
            seen.add(u)
            ranked.append(c)

    ranked.sort(key=lambda c: b.image_priority(c, title), reverse=True)
    last = "none"

    for c in ranked[:14]:
        source = c.get("source", "")
        overlap = b.title_overlap(title, c.get("context", ""))

        # Weakly contextual page/OG images are where logos/header cards most often leak in.
        if source in ("page", "og") and overlap < 0.18:
            last = "weak_image_context"
            continue

        img, reason = b.image_to_jpeg(c, title)
        if img:
            return img, c.get("url"), f"ok:{source}:{overlap:.2f}"

        last = reason
        if reason == "logo_word":
            b.STATS["logo_image_skip"] += 1
        if reason in ("flat_graphic", "text_card_like", "og_card_like"):
            b.STATS["text_card_image_skip"] += 1

    return None, None, last


b.select_image = select_image_v95


# ---------------------------------------------------------------------------
# First-party local HTML adapters
# ---------------------------------------------------------------------------
def discover_astv_urls(page_text):
    urls, seen = [], set()
    for raw in re.findall(r'href=["\']([^"\']+)["\']', page_text or "", flags=re.I):
        u = urllib.parse.urljoin(ASTV_NEWS_URL, html.unescape(raw))
        p = urllib.parse.urlparse(u)
        if not re.match(r"^/news/[^/]+/\d{4}-\d{2}-\d{2}-[^/]+/?$", p.path.lower()):
            continue
        u = urllib.parse.urlunparse((p.scheme or "https", p.netloc or "astv.ru", p.path, "", "", ""))
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls[:24]


def _astv_url_dt(url):
    m = re.search(r"/(\d{4}-\d{2}-\d{2})-", url or "")
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1)).replace(tzinfo=b.TZ).astimezone(timezone.utc)
    except Exception:
        return None


def discover_sakh_urls(page_text):
    urls, seen = [], set()
    for raw in re.findall(r'href=["\']([^"\']+)["\']', page_text or "", flags=re.I):
        u = urllib.parse.urljoin(SAKH_NEWS_URL, html.unescape(raw))
        p = urllib.parse.urlparse(u)
        if not re.match(r"^/news/\d+/\d{4}-\d{2}-\d{2}/[^/]+/?$", p.path.lower()):
            continue
        u = urllib.parse.urlunparse((p.scheme or "https", p.netloc or "sakh.online", p.path, "", "", ""))
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls[:24]


def _sakh_url_dt(url):
    m = re.search(r"/news/\d+/(\d{4}-\d{2}-\d{2})/", url or "")
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1)).replace(tzinfo=b.TZ).astimezone(timezone.utc)
    except Exception:
        return None


def _local_html_candidates(state, source_name, index_url, discover, date_from_url, weight):
    used_u = set(state.get("published_urls", []))
    used_h = set(state.get("published_title_hashes", []))
    out = []

    try:
        r = requests.get(
            index_url,
            headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"},
            timeout=25,
        )
        r.raise_for_status()
        urls = discover(r.text[:1200000])
    except Exception as ex:
        b.log(f"{source_name} HTML source failed: {ex}")
        return []

    for url in urls[:16]:
        if url in used_u:
            continue

        page = b.page_info(url)
        title = b.clean(page.get("title"))
        desc = b.clean(page.get("desc"))
        article = b.clean(page.get("article"))
        text = " ".join(x for x in (desc, article) if x).strip()[:1800]

        dt = page.get("published") or date_from_url(url)
        if not strict_fresh(dt):
            continue
        if len(title) < 24 or len(text) < 140:
            continue

        th = b.htitle(title)
        if th in used_h:
            continue

        cat, score, reason = classify("sakhalin", weight, title, text, desc, url)
        if not cat:
            continue

        image, image_url, image_reason = b.select_image(page.get("images", []), title)
        if not image:
            b.STATS["bad_image_skip"] += 1
            b.log(f"{source_name} no safe image -> text-only: {title[:80]} | {image_reason}")

        category, footer = b.CAT[cat]
        out.append({
            "id": 10000 + len(out),
            "source": source_name,
            "category_key": cat,
            "category": category,
            "footer": footer,
            "score": score + (20 if image else 0),
            "reason": reason,
            "title": title,
            "source_text": text,
            "url": page.get("url") or url,
            "image_url": image_url,
            "image": image,
            "published_at": dt.isoformat(),
            "title_hash": th,
        })

    return out


def collect_astv_html(state):
    return _local_html_candidates(state, "ASTV", ASTV_NEWS_URL, discover_astv_urls, _astv_url_dt, 108)


def collect_sakh_html(state):
    return _local_html_candidates(state, "Sakh.online", SAKH_NEWS_URL, discover_sakh_urls, _sakh_url_dt, 106)


_old_collect = b.collect


def image_hash(item):
    data = item.get("image")
    if isinstance(data, (bytes, bytearray)) and data:
        return hashlib.sha1(bytes(data)).hexdigest()
    url = item.get("image_url") or ""
    return hashlib.sha1(url.encode("utf-8")).hexdigest() if url else ""


def topic_cluster(item):
    text = f"{item.get('title','')} {item.get('source_text','')}".lower()
    cat = item.get("category_key", "")

    if cat == "ru_security" and any(x in text for x in (
        "аэропорт", "росавиац", "воздушн", "беспилот", "бпла", "дрон", "пво", "опасност"
    )):
        return "ru_security_airspace_drone"

    if cat == "sakh_quake":
        places = [x for x in b.LOCAL if x in text]
        return "sakh_quake:" + "_".join(sorted(set(places))[:2])

    words = [w for w in b.norm(item.get("title", "")).split() if len(w) >= 5][:6]
    return cat + ":" + "_".join(words)


def valid_source_stream(item):
    cat = item.get("category_key", "")
    src = (item.get("source") or "").lower()
    url = (item.get("url") or "").lower()
    body = f"{item.get('title','')} {item.get('source_text','')}".lower()

    if not url or b.is_google(url):
        return False, "non_direct_or_missing_url"

    if cat in ("sakh", "sakh_chp", "sakh_quake"):
        trusted_local = any(x in src + " " + url for x in (
            "astv", "sakhalinmedia", "sakh.online", "sakh.com"
        ))
        if not trusted_local and not b.terms(body, b.LOCAL):
            return False, "local_without_geo"

    if cat == "world_ru" and not hits(body, RUSSIA_MARKERS):
        return False, "world_ru_without_russia"

    if ("bbc technology" in src or "guardian technology" in src) and cat != "it":
        return False, "it_source_wrong_stream"

    return True, "ok"


def collect(state):
    items = _old_collect(state) + collect_astv_html(state) + collect_sakh_html(state)

    recent_hashes = {
        p.get("image_hash") for p in state.get("last_posts", [])[-60:] if p.get("image_hash")
    }
    recent_urls = {
        p.get("image_url") for p in state.get("last_posts", [])[-60:] if p.get("image_url")
    }

    seen_hashes, seen_urls, seen_clusters = set(), set(), set()
    filtered = []

    for item in items:
        ok, why = valid_source_stream(item)
        if not ok:
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log(f"skip source-stream guard [{why}]: {item.get('title','')[:90]}")
            continue

        # Interfax frequently exposes branded/title cards rather than event photos.
        if "interfax" in (item.get("source") or "").lower():
            item["image"] = None
            item["image_url"] = None

        ih = image_hash(item)
        iu = item.get("image_url") or ""

        if ih and (ih in seen_hashes or ih in recent_hashes):
            b.log("duplicate image -> text-only: " + item.get("title", "")[:90])
            item["image"] = None
            item["image_url"] = None
            ih = ""
            iu = ""
        elif iu and (iu in seen_urls or iu in recent_urls):
            b.log("duplicate image url -> text-only: " + item.get("title", "")[:90])
            item["image"] = None
            item["image_url"] = None
            ih = ""
            iu = ""

        cluster = topic_cluster(item)
        if cluster in seen_clusters and item.get("category_key") in (
            "ru_security", "ru_pol", "ru_eco", "geo", "sakh_quake"
        ):
            b.STATS["category_skip"] = b.STATS.get("category_skip", 0) + 1
            b.log("skip duplicate topic cluster: " + item.get("title", "")[:90])
            continue

        item["image_hash"] = ih or None
        item["topic_cluster"] = cluster
        if ih:
            seen_hashes.add(ih)
        if iu:
            seen_urls.add(iu)
        seen_clusters.add(cluster)
        filtered.append(item)

    b.STATS["candidates"] = len(filtered)
    return filtered


b.collect = collect


# ---------------------------------------------------------------------------
# Grounded generation and deterministic evidence validation
# ---------------------------------------------------------------------------
def _evidence_norm(text):
    return re.sub(r"\s+", " ", b.norm(text or "")).strip()


def evidence_matches(source, evidence):
    ev = _evidence_norm(evidence)
    src = _evidence_norm(source)
    if len(ev.split()) < 4:
        return False
    if ev in src:
        return True

    e_tokens = ev.split()
    s_tokens = src.split()
    if len(e_tokens) < 5 or len(s_tokens) < len(e_tokens):
        return False

    target = set(e_tokens)
    best = 0.0
    window = len(e_tokens) + 3
    for i in range(0, max(1, len(s_tokens) - window + 1)):
        chunk = set(s_tokens[i:i + window])
        best = max(best, len(target & chunk) / max(1, len(target)))
    return best >= 0.90


def quake_required_facts(c):
    if c.get("category_key") != "sakh_quake":
        return {}

    source = f"{c.get('title','')} {c.get('source_text','')}"
    low = source.lower()
    out = {
        "magnitude": [],
        "depth_km": [],
        "distance_km": [],
        "intensity_points": [],
        "time": [],
    }

    for pat in (
        r"(?:магнитуд\w*|magnitude)\D{0,50}([0-9]+(?:[.,][0-9]+)?)",
        r"\bM\s*([0-9](?:[.,][0-9]+)?)\b",
    ):
        for v in re.findall(pat, source, flags=re.I):
            v = v.replace(",", ".")
            if v not in out["magnitude"]:
                out["magnitude"].append(v)

    for v in re.findall(
        r"(?:глубин\w*|depth)\D{0,45}([0-9]+(?:[.,][0-9]+)?)\s*(?:км|km)",
        source,
        flags=re.I,
    ):
        v = v.replace(",", ".")
        if v not in out["depth_km"]:
            out["depth_km"].append(v)

    for pat in (
        r"(?:эпицентр\w*|epicenter|epicentre)[^.]{0,120}?([0-9]+(?:[.,][0-9]+)?)\s*(?:км|km)\s*(?:от|from)",
        r"([0-9]+(?:[.,][0-9]+)?)\s*(?:км|km)\s+(?:от|from)\s+[^.,;]{2,80}",
    ):
        for v in re.findall(pat, source, flags=re.I):
            v = v.replace(",", ".")
            if v not in out["distance_km"]:
                out["distance_km"].append(v)

    for v in re.findall(
        r"([0-9]+(?:[.,][0-9]+)?)\s*(?:балл|балла|баллов|points?)\b",
        source,
        flags=re.I,
    ):
        v = v.replace(",", ".")
        if v not in out["intensity_points"]:
            out["intensity_points"].append(v)

    if re.search(r"(?:произош\w*|зафикс\w*|зарегистр\w*|occurred|recorded|reported)", low):
        for v in re.findall(r"\b([0-2]?\d:[0-5]\d)\b", source):
            if v not in out["time"]:
                out["time"].append(v)

    limits = {
        "magnitude": 3,
        "depth_km": 1,
        "distance_km": 1,
        "intensity_points": 2,
        "time": 1,
    }
    return {k: v[:limits[k]] for k, v in out.items() if v}


def grounded_prompt(c, error=""):
    data = {
        "category": c["category"],
        "footer": c["footer"],
        "source": c["source"],
        "title": c["title"],
        "source_text": c["source_text"],
        "published_at": c["published_at"],
        "required_facts": quake_required_facts(c),
    }
    return (
        "Сделай профессиональный новостной Telegram-пост строго на русском языке. "
        "Используй ТОЛЬКО факты из title/source_text. Ничего не додумывай. "
        "Каждый абзац должен быть точным переводом или сжатым пересказом указанного evidence. "
        "Evidence копируй ДОСЛОВНО из исходника на языке источника, 5–25 слов. "
        "Все required_facts, если они переданы, обязательно сохрани в тексте. "
        "Без списков, без «Суть», «Что известно», «Источник». 2–3 содержательных абзаца. "
        "Если фактов недостаточно — reject=true. Не добавляй числа, которых нет в исходнике. "
        f"Ошибка предыдущей попытки: {error}\n"
        "Верни только JSON: "
        '{"reject":false,"title_ru":"...","title_evidence":"дословный фрагмент источника",'
        '"body":["абзац 1","абзац 2"],'
        '"body_evidence":["дословный фрагмент к абзацу 1","дословный фрагмент к абзацу 2"],'
        '"footer":"..."}\n'
        + json.dumps(data, ensure_ascii=False)
    )


def generate_grounded(c, error=""):
    text = b.openrouter([
        {
            "role": "system",
            "content": (
                "Ты профессиональный редактор новостей. Возвращай только валидный JSON. "
                "Весь итоговый текст строго на русском. Evidence всегда копируй дословно из source."
            ),
        },
        {"role": "user", "content": grounded_prompt(c, error)},
    ])
    row = b.parse_obj(text)
    row["category"] = c["category"]
    row["footer"] = row.get("footer") or c["footer"]
    return row


def _contains_numeric_value(text, value):
    normalized = (text or "").replace(",", ".")
    return bool(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", normalized))


def validate_quake(row, c):
    required = quake_required_facts(c)
    if not required:
        return []

    joined = b.clean(row.get("title_ru")) + " " + " ".join(
        b.clean(x) for x in (row.get("body") or []) if b.clean(x)
    )
    errors = []

    labels = {
        "magnitude": "quake_missing_magnitude",
        "depth_km": "quake_missing_depth",
        "distance_km": "quake_missing_distance",
        "intensity_points": "quake_missing_intensity",
    }
    for key, prefix in labels.items():
        for value in required.get(key, []):
            if not _contains_numeric_value(joined, value):
                errors.append(prefix + ":" + value)

    for value in required.get("time", []):
        if value not in joined:
            errors.append("quake_missing_time:" + value)

    return errors


def validate_evidence(row, c):
    if row.get("reject") is True:
        return []

    source = f"{c.get('title','')} {c.get('source_text','')}"
    body = row.get("body") if isinstance(row.get("body"), list) else []
    body_evidence = row.get("body_evidence") if isinstance(row.get("body_evidence"), list) else []
    errors = []

    if not evidence_matches(source, b.clean(row.get("title_evidence"))):
        errors.append("title_evidence_not_found")

    if len(body_evidence) != len(body):
        errors.append("body_evidence_count_mismatch")
    else:
        for i, ev in enumerate(body_evidence):
            if not evidence_matches(source, b.clean(ev)):
                errors.append(f"body_evidence_not_found:{i + 1}")

    return errors


def semantic_fact_check(row, c):
    prompt = (
        "Проверь новостной черновик против исходника. "
        "Каждое фактическое утверждение черновика должно прямо следовать из исходника. "
        "Перевод и краткое перефразирование допустимы; домыслы, усиление, изменение причинности, "
        "субъектов, времени, места, количества или статуса события запрещены. "
        'Верни только JSON: {"supported":true,"unsupported":[]} или '
        '{"supported":false,"unsupported":["кратко что не подтверждено"]}.\n'
        "SOURCE=" + json.dumps({
            "title": c.get("title"),
            "source_text": c.get("source_text"),
        }, ensure_ascii=False) + "\n"
        "DRAFT=" + json.dumps({
            "title": row.get("title_ru"),
            "body": row.get("body"),
        }, ensure_ascii=False)
    )
    try:
        raw = b.openrouter(
            [
                {"role": "system", "content": "Ты строгий фактчекер. Только JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=350,
        )
        verdict = b.parse_obj(raw)
        return verdict.get("supported") is True, verdict.get("unsupported") or []
    except Exception as ex:
        # Fail closed: infrastructure uncertainty must not become a fabricated post.
        return False, ["fact_checker_error:" + str(ex)[:160]]


_old_validate = b.validate


def validate_grounded(row, c):
    errors = list(_old_validate(row, c))
    errors.extend(validate_evidence(row, c))
    errors.extend(validate_quake(row, c))
    return errors


def valid_post_grounded(c):
    err = ""
    for _ in range(3):
        try:
            row = generate_grounded(c, err)
            errors = validate_grounded(row, c)

            if not errors:
                supported, unsupported = semantic_fact_check(row, c)
                if supported:
                    return row
                errors = ["semantic_fact_check:" + "; ".join(str(x) for x in unsupported[:3])]

            err = "; ".join(errors)
            b.STATS["rewrite_retry"] += 1
            b.log(f"rewrite required: {c['title'][:70]} | {err[:500]}")
        except Exception as ex:
            err = str(ex)
            b.STATS["rewrite_retry"] += 1
            b.log(f"write retry: {c['title'][:70]} | {err[:500]}")

    b.STATS["editorial_skip"] += 1
    return None


b.generate = generate_grounded
b.validate = validate_grounded
b.valid_post = valid_post_grounded


# ---------------------------------------------------------------------------
# Local-source health
# ---------------------------------------------------------------------------
def _probe_rss(name, rss):
    rec = {"source": name, "status": "down", "entries": 0, "recent": 0}
    try:
        r = requests.get(rss, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=20)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        entries = list(feed.entries[:20])
        rec["entries"] = len(entries)
        rec["recent"] = sum(
            1 for e in entries if (b.entry_dt(e) is not None and strict_fresh(b.entry_dt(e)))
        )
        rec["status"] = "ok" if rec["recent"] else ("stale" if entries else "empty")
        if getattr(feed, "bozo", False):
            rec["bozo"] = True
    except Exception as ex:
        rec["error"] = str(ex)[:180]
    return rec


def _probe_html(name, index_url, discover, date_from_url):
    rec = {"source": name, "status": "down", "entries": 0, "recent": 0}
    try:
        r = requests.get(index_url, headers={"User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0"}, timeout=20)
        r.raise_for_status()
        urls = discover(r.text[:1200000])
        rec["entries"] = len(urls)
        recent = 0
        for u in urls:
            dt = date_from_url(u)
            if dt is not None and strict_fresh(dt):
                recent += 1
        rec["recent"] = recent
        rec["status"] = "ok" if recent else ("stale" if urls else "empty")
    except Exception as ex:
        rec["error"] = str(ex)[:180]
    return rec


def probe_local_sources():
    results = []
    for name, src_type, rss, _weight in b.SOURCES:
        if src_type == "sakhalin":
            results.append(_probe_rss(name, rss))

    results.append(_probe_html("ASTV HTML", ASTV_NEWS_URL, discover_astv_urls, _astv_url_dt))
    results.append(_probe_html("Sakh.online HTML", SAKH_NEWS_URL, discover_sakh_urls, _sakh_url_dt))

    ok_count = sum(1 for x in results if x["status"] == "ok")
    if ok_count >= 2:
        overall = "healthy"
    elif ok_count == 1:
        overall = "degraded"
    else:
        overall = "down"

    return {"status": overall, "ok_sources": ok_count, "sources": results}


# ---------------------------------------------------------------------------
# Editorial balance and Telegram publishing
# ---------------------------------------------------------------------------
def ordered(cands):
    local = [c for c in cands if c["category_key"] in ("sakh_quake", "sakh_chp", "sakh")]
    other = [c for c in cands if c not in local]
    out = []

    if local:
        out.append(local[0])

    for key in ("world_ru", "ru_security", "ru_pol", "ru_eco", "geo", "it"):
        for c in other:
            if c["category_key"] == key and c not in out:
                out.append(c)

    for c in local[1:] + other:
        if c not in out:
            out.append(c)
    return out


b.ordered = ordered


def text_post(row, c):
    title = b.clean(row.get("title_ru"))
    body = [b.clean(x) for x in row.get("body", []) if b.clean(x)]
    text = (
        f"{b.esc(c['category'])}\n\n"
        f"<b>{b.esc(title)}</b>\n\n"
        + "\n\n".join(b.esc(x) for x in body)
        + f"\n\n{b.esc(c['footer'])} · <a href=\"{b.attr(c['url'])}\">{b.esc(c['source'])}</a>"
    )
    return text[:4000]


def send_text(row, c):
    token = b.os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = b.os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat,
            "text": text_post(row, c),
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=90,
    )
    if r.status_code >= 400:
        raise RuntimeError(r.text[:700])
    return r.json()


def main():
    state = b.load_state()
    started = datetime.now(b.TZ).isoformat(timespec="seconds")
    run = {
        "version": VERSION,
        "started_sakhalin": started,
        "status": "running",
        "candidates": 0,
        "published": 0,
        "local_candidates": 0,
    }
    state["last_run"] = run

    try:
        b.log(f"SkySakhNews {VERSION} start")

        local_health = probe_local_sources()
        run["local_stream"] = local_health
        b.log(
            "local stream: " + local_health["status"]
            + f" ({local_health['ok_sources']} sources with recent items)"
        )

        cands = b.collect(state)
        run["candidates"] = len(cands)
        run["local_candidates"] = sum(
            1 for c in cands if c.get("category_key") in ("sakh_quake", "sakh_chp", "sakh")
        )
        b.log(f"Кандидатов после production-фильтра: {len(cands)}")
        b.log(f"Локальных кандидатов: {run['local_candidates']}")

        published = 0
        for c in b.ordered(cands):
            if published >= b.POSTS_PER_RUN:
                break
            if c["url"] in state.get("published_urls", []):
                continue

            row = b.valid_post(c)
            if not row:
                continue

            result = None
            method = None
            with_image = bool(c.get("image"))

            if with_image:
                try:
                    result = b.send_photo(c, b.caption(row, c))
                    method = "sendPhoto/stable-v9.5"
                except Exception as ex:
                    b.STATS["telegram_fail"] += 1
                    b.log(f"photo failed -> text fallback: {c['title'][:90]} | {ex}")
                    result = send_text(row, c)
                    method = "sendMessage/fallback-after-photo"
                    with_image = False
                    c["image"] = None
                    c["image_url"] = None
                    c["image_hash"] = None
            else:
                result = send_text(row, c)
                method = "sendMessage/no-safe-image"

            if result and result.get("ok"):
                state.setdefault("published_urls", []).append(c["url"])
                state.setdefault("published_title_hashes", []).append(c["title_hash"])
                state.setdefault("last_posts", []).append({
                    "time_sakhalin": datetime.now(b.TZ).isoformat(timespec="seconds"),
                    "source": c["source"],
                    "category": c["category"],
                    "category_key": c.get("category_key"),
                    "title": row.get("title_ru") or c["title"],
                    "url": c["url"],
                    "image_url": c.get("image_url"),
                    "image_hash": c.get("image_hash"),
                    "topic_cluster": c.get("topic_cluster"),
                    "published_at": c.get("published_at"),
                    "with_image": with_image,
                    "publish_method": method,
                    "grounded_evidence": True,
                })
                published += 1
                b.STATS["published"] = published
                run["published"] = published
                time.sleep(8)

        run["status"] = "ok"
        run["finished_sakhalin"] = datetime.now(b.TZ).isoformat(timespec="seconds")
        run["stats"] = dict(b.STATS)
        b.log(f"Опубликовано: {published}")
        b.report()
        b.save_state(state)

    except Exception as ex:
        run["status"] = "error"
        run["error"] = str(ex)[:1000]
        run["finished_sakhalin"] = datetime.now(b.TZ).isoformat(timespec="seconds")
        try:
            b.save_state(state)
        finally:
            raise


b.main = main

if __name__ == "__main__":
    b.main()
