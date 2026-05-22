# SkySakhNews image pipeline.
# Strict order:
#   1) source image from RSS/article metadata;
#   2) external thematic image search, up to 3 semantic queries;
#   3) local generated semantic image.
# The module is intentionally deterministic and conservative: better generate a clean
# semantic illustration than publish an irrelevant category photo.

import hashlib
import html
import io
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
from PIL import Image, ImageStat

from thematic_image import generate_thematic_image

MIN_WIDTH = int(os.getenv("IMAGE_MIN_WIDTH", "320"))
MIN_HEIGHT = int(os.getenv("IMAGE_MIN_HEIGHT", "180"))
RECENT_IMAGE_LIMIT = int(os.getenv("RECENT_IMAGE_LIMIT", "40"))
USER_AGENT = "SkySakhNewsBot/1.0 (+https://github.com/skyyuriofficial-stack/SkySakhNewsBot)"

BAD_URL_TOKENS = [
    "logo", "icon", "avatar", "sprite", "placeholder", "blank", "tracking", "counter", "pixel",
    "favicon", "banner", "advert", "ads/", "share", "social", "button", "loader",
]

CATEGORY_INCIDENT = "🇷🇺 РФ / происшествия"
CATEGORY_SECURITY = "🇷🇺 РФ / война и безопасность"
CATEGORY_ECONOMY = "🇷🇺 РФ / экономика"
CATEGORY_POLITICS = "🇷🇺 РФ / законы и политика"
CATEGORY_GEOPOLITICS = "🧭 Геополитика"
CATEGORY_IT = "🌐 Мировые IT"
CATEGORY_GAMES = "🎮 Игры / индустрия"
CATEGORY_SAKHALIN = "📍 Сахалин"
CATEGORY_WORLD_RUSSIA = "🌍 Мир о России"

FIRE_TERMS = ["пожар", "возгоран", "сгорел", "сгорела", "огонь", "мчс", "пожарн"]
ROAD_TERMS = ["дтп", "авар", "столкнов", "микроавтобус", "газель", "трасс", "дорог", "водител", "автомоб"]
WATER_TERMS = ["водопровод", "водоснаб", "без воды", "вода", "коллектор", "труба", "коммуналь", "жкх", "авария на вод"]
CRIME_TERMS = ["краж", "мошеннич", "убийств", "напад", "задержан", "полици", "суд", "следств"]
AGRI_TERMS = ["сельхоз", "зерн", "зерно", "пшениц", "аграр", "урож", "посев", "фермер", "россельхозбанк"]
BANK_TERMS = ["банк", "кредит", "вклад", "ставк", "финанс", "ипотек", "заем", "заём", "рубл"]
ENERGY_TERMS = ["нефть", "газ", "спг", "уголь", "энергоресурс", "трубопровод", "месторожд", "энергетик"]
INDUSTRY_TERMS = ["завод", "производств", "промышлен", "предприят", "индустр", "металл"]
WAR_TERMS = ["бпла", "дрон", "пво", "всу", "обстрел", "удар", "ракета", "заэс", "аэс", "диверс", "теракт"]
IT_TERMS = ["openai", "google", "microsoft", "apple", "anthropic", "nvidia", "уязвим", "cve", "ии", "нейросет", "кибер"]
GAMES_TERMS = ["game", "xbox", "playstation", "nintendo", "steam", "witcher", "gta", "игр", "студия"]
POLITICS_TERMS = ["госдума", "закон", "сенат", "правительство", "переговор", "визит", "саммит", "мид", "путин", "си цзиньпин"]
GEOPOLITICS_TERMS = ["иран", "израил", "сша", "нато", "ес", "китай", "тайван", "газа", "оон", "куба"]

ALLOWED_IMAGE_TOKENS = {
    "incident_fire": ["fire", "firefighter", "emergency", "smoke", "burning", "rescue", "пожар", "мчс"],
    "incident_road": ["road", "accident", "crash", "car", "vehicle", "ambulance", "police", "traffic", "дтп", "авария"],
    "incident_water": ["water", "pipe", "pipeline", "plumbing", "repair", "utility", "municipal", "works", "вод", "труб"],
    "incident_crime": ["police", "law", "court", "crime", "handcuffs", "investigation", "полиция", "суд"],
    "security": ["drone", "military", "radar", "air", "defense", "emergency", "security", "missile", "fire", "бпла", "пво"],
    "agriculture": ["grain", "wheat", "field", "farm", "agriculture", "harvest", "crop", "зерно", "сельск"],
    "bank": ["bank", "finance", "credit", "money", "ruble", "loan", "банк", "финанс"],
    "energy": ["oil", "gas", "pipeline", "energy", "power", "industrial", "нефть", "газ"],
    "industry": ["factory", "industrial", "plant", "manufacturing", "завод"],
    "economy": ["economy", "finance", "industry", "market", "business", "эконом"],
    "it": ["server", "data", "chip", "computer", "cyber", "software", "technology", "network", "код", "сервер"],
    "games": ["game", "gaming", "controller", "console", "playstation", "xbox", "steam"],
    "diplomacy": ["summit", "diplomacy", "flags", "united nations", "meeting", "government", "china", "russia"],
    "sakhalin": ["sakhalin", "yuzhno", "island", "russia", "city"],
}

FORBIDDEN_BY_TOPIC = {
    "incident_water": ["road", "car", "vehicle", "drone", "military", "game", "oil platform"],
    "incident_road": ["pipeline", "water pipe", "drone", "server", "grain"],
    "agriculture": ["oil platform", "gas platform", "offshore", "server", "car crash"],
    "bank": ["oil platform", "firefighter", "car crash", "drone"],
    "energy": ["grain field", "game controller", "car crash"],
}

@dataclass
class ImageCandidate:
    url: Optional[str]
    source: str  # source / external_search / generated
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: Optional[str] = None
    query_used: Optional[str] = None
    relevance_score: float = 0.0
    image_kind: Optional[str] = None
    data: Optional[bytes] = None
    filename: str = "image.jpg"
    reason: str = ""


@dataclass
class ImageDecision:
    selected: Optional[ImageCandidate]
    strategy: str  # source / search / generated / none
    reason: str
    attempts: List[Dict]


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def article_text(article: Dict) -> str:
    keys = ["category", "category_hint", "title_ru", "title_original", "source_text", "body", "post_text", "edited_post_text", "url", "source"]
    return norm(" ".join(str(article.get(k) or "") for k in keys))


def has_any(text: str, terms: Iterable[str]) -> bool:
    text = norm(text)
    return any(norm(term) in text for term in terms)


def topic_key(article: Dict) -> str:
    text = article_text(article)
    category = article.get("category") or article.get("category_hint") or ""
    if category == CATEGORY_INCIDENT:
        if has_any(text, FIRE_TERMS):
            return "incident_fire"
        if has_any(text, WATER_TERMS):
            return "incident_water"
        if has_any(text, ROAD_TERMS):
            return "incident_road"
        if has_any(text, CRIME_TERMS):
            return "incident_crime"
        return "incident_fire" if has_any(text, ["погиб", "пострадал", "мчс"]) else "incident_road"
    if category == CATEGORY_SECURITY or has_any(text, WAR_TERMS):
        return "security"
    if category == CATEGORY_ECONOMY:
        if has_any(text, AGRI_TERMS):
            return "agriculture"
        if has_any(text, ENERGY_TERMS):
            return "energy"
        if has_any(text, BANK_TERMS):
            return "bank"
        if has_any(text, INDUSTRY_TERMS):
            return "industry"
        return "economy"
    if category in {CATEGORY_IT, "💻 IT / технологии"} or has_any(text, IT_TERMS):
        return "it"
    if category == CATEGORY_GAMES or has_any(text, GAMES_TERMS):
        return "games"
    if category == CATEGORY_SAKHALIN:
        return "sakhalin"
    if category in {CATEGORY_POLITICS, CATEGORY_GEOPOLITICS, CATEGORY_WORLD_RUSSIA} or has_any(text, POLITICS_TERMS + GEOPOLITICS_TERMS):
        return "diplomacy"
    return "diplomacy"


def filename_from_url(url: Optional[str]) -> str:
    if not url:
        return "image.jpg"
    path = urlparse(url).path.rsplit("/", 1)[-1] or "image.jpg"
    path = re.sub(r"[^A-Za-z0-9_.-]+", "_", path)
    if "." not in path:
        path += ".jpg"
    return path[:80]


def is_bad_url(url: Optional[str]) -> bool:
    u = norm(url or "")
    return not u or any(tok in u for tok in BAD_URL_TOKENS)


def load_image_meta(data: bytes) -> Tuple[Optional[int], Optional[int], str, float]:
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
        mime = Image.MIME.get(img.format, "image/jpeg")
        # Low variance usually means blank/logo/flat placeholder.
        stat = ImageStat.Stat(img.convert("L").resize((64, 64)))
        variance = float(stat.var[0])
        return width, height, mime, variance
    except Exception:
        return None, None, "application/octet-stream", 0.0


def bytes_fingerprint(data: bytes) -> str:
    # Content hash is enough for exact-repeat prevention. Perceptual hash can be added later.
    return hashlib.sha1(data or b"").hexdigest()


def state_recent_sets(state: Dict) -> Tuple[set, set]:
    urls = set(state.get("recent_image_urls", []) or [])
    fps = set(state.get("recent_image_fingerprints", []) or [])
    for post in (state.get("last_posts", []) or [])[-60:]:
        if post.get("image_url"):
            urls.add(post.get("image_url"))
        if post.get("image_fingerprint"):
            fps.add(post.get("image_fingerprint"))
    return urls, fps


def remember_image_in_state(state: Dict, candidate: ImageCandidate) -> None:
    if not candidate or not candidate.data:
        return
    fp = bytes_fingerprint(candidate.data)
    urls = state.setdefault("recent_image_urls", [])
    fps = state.setdefault("recent_image_fingerprints", [])
    prompts = state.setdefault("recent_generated_prompts", [])
    if candidate.url and candidate.url not in urls:
        urls.append(candidate.url)
    if fp and fp not in fps:
        fps.append(fp)
    if candidate.query_used and candidate.source == "generated" and candidate.query_used not in prompts:
        prompts.append(candidate.query_used)
    state["recent_image_urls"] = urls[-RECENT_IMAGE_LIMIT:]
    state["recent_image_fingerprints"] = fps[-RECENT_IMAGE_LIMIT:]
    state["recent_generated_prompts"] = prompts[-RECENT_IMAGE_LIMIT:]


def relevance_score(article: Dict, candidate: ImageCandidate, topic: Optional[str] = None) -> Tuple[float, str]:
    topic = topic or topic_key(article)
    text = norm(" ".join([candidate.url or "", candidate.query_used or "", candidate.filename or "", candidate.reason or ""]))
    allowed = ALLOWED_IMAGE_TOKENS.get(topic, [])
    forbidden = FORBIDDEN_BY_TOPIC.get(topic, [])
    score = 0.0
    if candidate.source == "source":
        score += 0.55
    elif candidate.source == "external_search":
        score += 0.35
    elif candidate.source == "generated":
        score += 0.80
    hits = [tok for tok in allowed if norm(tok) and norm(tok) in text]
    score += min(0.45, len(hits) * 0.12)
    bad_hits = [tok for tok in forbidden if norm(tok) and norm(tok) in text]
    score -= min(0.60, len(bad_hits) * 0.25)
    if topic.startswith("incident") and candidate.source == "generated":
        score += 0.10
    return score, f"topic={topic}; hits={hits[:4]}; bad_hits={bad_hits[:4]}"


def validate_candidate(article: Dict, candidate: ImageCandidate, state: Dict, require_relevance: bool = True) -> Tuple[bool, str]:
    if not candidate or not candidate.data:
        return False, "no image data"
    if candidate.source != "generated" and is_bad_url(candidate.url):
        return False, "bad image URL token"
    width, height, mime, variance = load_image_meta(candidate.data)
    candidate.width, candidate.height, candidate.mime_type = width, height, mime
    if not width or not height:
        return False, "unreadable image"
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return False, f"image too small: {width}x{height}"
    if variance < 18.0:
        return False, "image too flat / likely placeholder"
    recent_urls, recent_fps = state_recent_sets(state)
    fp = bytes_fingerprint(candidate.data)
    if candidate.url and candidate.url in recent_urls:
        return False, "recent image URL duplicate"
    if fp in recent_fps:
        return False, "recent image content duplicate"
    score, reason = relevance_score(article, candidate)
    candidate.relevance_score = score
    candidate.reason = (candidate.reason + "; " + reason).strip("; ")
    if require_relevance and score < 0.42:
        return False, f"low relevance: {score:.2f}; {reason}"
    return True, f"accepted: {width}x{height}; score={score:.2f}; {reason}"


def http_get(url: str, timeout: int = 12) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        return resp
    except Exception:
        return None


def fetch_image(url: str) -> Optional[bytes]:
    resp = http_get(url, timeout=20)
    if not resp:
        return None
    ctype = resp.headers.get("Content-Type", "").lower()
    if "image" not in ctype and not re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", url, re.I):
        return None
    if len(resp.content or b"") < 8_000:
        return None
    return resp.content


def extract_meta_images(html_text: str, base_url: str) -> List[str]:
    urls: List[str] = []
    if not html_text:
        return urls
    html_text = html.unescape(html_text)
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)',
        r'<img[^>]+src=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html_text, flags=re.I | re.S):
            url = urljoin(base_url, m.group(1).strip())
            if url not in urls and not is_bad_url(url):
                urls.append(url)
            if len(urls) >= 10:
                return urls
    return urls


def extract_source_candidates(article: Dict) -> List[str]:
    urls: List[str] = []
    direct = article.get("image_url")
    if direct and not is_bad_url(direct):
        urls.append(direct)
    article_url = article.get("url")
    if article_url:
        resp = http_get(article_url, timeout=12)
        if resp and resp.text:
            for u in extract_meta_images(resp.text, article_url):
                if u not in urls:
                    urls.append(u)
    return urls[:12]


def extract_source_image(article: Dict, state: Dict, logger=None) -> Tuple[Optional[ImageCandidate], List[Dict]]:
    attempts: List[Dict] = []
    for url in extract_source_candidates(article):
        data = fetch_image(url)
        candidate = ImageCandidate(url=url, source="source", data=data, filename=filename_from_url(url), image_kind="photo", reason="source candidate")
        ok, reason = validate_candidate(article, candidate, state, require_relevance=False)
        attempts.append({"stage": "source", "url": url, "ok": ok, "reason": reason})
        if logger:
            logger(f"image source check: ok={ok} reason={reason} url={url[:120]}")
        if ok:
            return candidate, attempts
    return None, attempts


def build_image_queries(article: Dict) -> List[str]:
    text = article_text(article)
    topic = topic_key(article)
    title = re.sub(r"[^А-Яа-яA-Za-z0-9\s-]+", " ", str(article.get("title_ru") or article.get("title_original") or ""))
    title = re.sub(r"\s+", " ", title).strip()
    if topic == "incident_road":
        return ["road accident emergency response", "car crash highway ambulance", "traffic accident rescue"]
    if topic == "incident_water":
        return ["water pipe repair utility workers", "water pipeline repair emergency", "municipal water main break repair"]
    if topic == "incident_fire":
        return ["firefighters emergency fire smoke", "fire truck emergency response", "fire rescue operation"]
    if topic == "incident_crime":
        return ["police investigation emergency", "police car law enforcement", "court police investigation"]
    if topic == "security":
        return ["air defense radar drone", "drone emergency response", "military security radar"]
    if topic == "agriculture":
        return ["grain agriculture wheat field", "grain elevator agriculture", "wheat harvest farming"]
    if topic == "bank":
        return ["bank finance credit money", "banking finance documents", "credit loan finance"]
    if topic == "energy":
        return ["oil gas pipeline energy infrastructure", "energy industry pipeline", "gas pipeline infrastructure"]
    if topic == "industry":
        return ["industrial plant factory", "manufacturing plant industry", "factory production line"]
    if topic == "it":
        return ["data center servers cybersecurity", "computer chip technology", "server room network"]
    if topic == "games":
        # If title contains recognizable game words, use them but keep query generic enough.
        return [f"{title[:60]} official game art".strip(), "video game industry studio", "gaming console controller"]
    if topic == "sakhalin":
        return ["Sakhalin island city", "Yuzhno-Sakhalinsk city", "Sakhalin Russia landscape"]
    if has_any(text, GEOPOLITICS_TERMS + POLITICS_TERMS):
        return ["diplomacy summit flags", "government meeting flags", "international diplomacy meeting"]
    return ["news editorial abstract", "city news editorial", "press conference news"]


def wikimedia_search(query: str, limit: int = 8) -> List[Tuple[str, str]]:
    # Returns (image_url, metadata_text). Uses Commons API, no secret required.
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": query,
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "format": "json",
        "origin": "*",
    }
    try:
        resp = requests.get(api, params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
        if resp.status_code >= 400:
            return []
        data = resp.json()
    except Exception:
        return []
    out: List[Tuple[str, str]] = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        title = page.get("title") or ""
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        ext = info.get("extmetadata") or {}
        meta = " ".join(str((v or {}).get("value", "")) for v in ext.values() if isinstance(v, dict))
        meta = re.sub(r"<[^>]+>", " ", meta)
        out.append((url, f"{title} {meta}"[:800]))
    return out


def external_thematic_search(article: Dict, state: Dict, logger=None) -> Tuple[Optional[ImageCandidate], List[Dict]]:
    attempts: List[Dict] = []
    queries = build_image_queries(article)[:3]
    for query in queries:
        for url, meta in wikimedia_search(query, limit=7):
            data = fetch_image(url)
            candidate = ImageCandidate(
                url=url,
                source="external_search",
                data=data,
                filename=filename_from_url(url),
                query_used=query,
                image_kind="photo",
                reason=meta,
            )
            ok, reason = validate_candidate(article, candidate, state, require_relevance=True)
            attempts.append({"stage": "external_search", "query": query, "url": url, "ok": ok, "reason": reason})
            if logger:
                logger(f"image search check: ok={ok} query={query} reason={reason} url={url[:120]}")
            if ok:
                return candidate, attempts
        if not any(a.get("ok") for a in attempts if a.get("query") == query) and logger:
            logger(f"image search attempt failed: {query}")
    return None, attempts


def generated_candidate(article: Dict, state: Dict, logger=None) -> Tuple[Optional[ImageCandidate], List[Dict]]:
    attempts: List[Dict] = []
    data, content_type, filename = generate_thematic_image(article)
    candidate = ImageCandidate(
        url=None,
        source="generated",
        data=data,
        filename=filename,
        query_used=f"generated:{topic_key(article)}:{article.get('title_ru') or article.get('title_original')}",
        image_kind="generated",
        mime_type=content_type,
        reason="local semantic generation",
    )
    ok, reason = validate_candidate(article, candidate, state, require_relevance=True)
    attempts.append({"stage": "generated", "ok": ok, "reason": reason})
    if logger:
        logger(f"image generated check: ok={ok} reason={reason}")
    return (candidate if ok else None), attempts


def resolve_article_image(article: Dict, state: Dict, logger=None) -> ImageDecision:
    all_attempts: List[Dict] = []

    source, attempts = extract_source_image(article, state, logger=logger)
    all_attempts.extend(attempts)
    if source:
        return ImageDecision(source, "source", "source image accepted", all_attempts)

    searched, attempts = external_thematic_search(article, state, logger=logger)
    all_attempts.extend(attempts)
    if searched:
        return ImageDecision(searched, "search", "external thematic image accepted", all_attempts)

    generated, attempts = generated_candidate(article, state, logger=logger)
    all_attempts.extend(attempts)
    if generated:
        return ImageDecision(generated, "generated", "generated semantic image accepted", all_attempts)

    return ImageDecision(None, "none", "no valid image found", all_attempts)


def candidate_to_file(candidate: ImageCandidate) -> Optional[Tuple[bytes, str, str]]:
    if not candidate or not candidate.data:
        return None
    return candidate.data, candidate.mime_type or "image/jpeg", candidate.filename or "image.jpg"


def decision_to_dict(decision: ImageDecision) -> Dict:
    selected = asdict(decision.selected) if decision.selected else None
    if selected:
        selected.pop("data", None)
    return {"strategy": decision.strategy, "reason": decision.reason, "selected": selected, "attempts": decision.attempts[-12:]}
