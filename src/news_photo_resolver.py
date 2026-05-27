# Source-first photo resolver.
# Goal: use real article/source photos where possible and reserve local generated art only as last fallback.
# It is intentionally lighter than image_pipeline.py and biased toward real photos, while rejecting obvious text cards/logos/placeholders.

import io
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image, ImageStat

USER_AGENT = "SkySakhNewsBot/1.0 (+https://github.com/skyyuriofficial-stack/SkySakhNewsBot)"
MIN_W = 420
MIN_H = 230

BAD_URL_TOKENS = [
    "logo", "icon", "avatar", "sprite", "placeholder", "blank", "tracking", "counter", "pixel",
    "favicon", "button", "loader", "ads/", "advert", "banner-ads",
]

BAD_TEXT_CARD_TOKENS = [
    "ogimage", "og-image", "social-card", "share-card", "preview-card", "twitter-card",
    "title-card", "text-card", "poster", "infographic", "stamp", "postage", "postal",
    "logo", "placeholder", "banner", "icon", "avatar",
]

PHOTO_HINT_TOKENS = [
    "photo", "image", "jpg", "jpeg", "webp", "png", "uploads", "media", "pictures", "cdn",
    "reuters", "apnews", "euronews", "bbc", "guardian", "interfax",
]


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def has_any(text: str, terms) -> bool:
    text = norm(text)
    return any(norm(t) in text for t in terms)


def is_bad_url(url: str) -> bool:
    u = norm(url)
    return not u or has_any(u, BAD_URL_TOKENS)


def is_text_card_url(url: str, meta: str = "") -> bool:
    return has_any((url or "") + " " + (meta or ""), BAD_TEXT_CARD_TOKENS)


def http_get(url: str, timeout: int = 12) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        return resp
    except Exception:
        return None


def image_meta(data: bytes) -> Tuple[Optional[int], Optional[int], str, float]:
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
        mime = Image.MIME.get(img.format, "image/jpeg")
        variance = float(ImageStat.Stat(img.convert("L").resize((64, 64))).var[0])
        return width, height, mime, variance
    except Exception:
        return None, None, "application/octet-stream", 0.0


def fetch_image(url: str) -> Optional[Tuple[bytes, str, int, int]]:
    if not url or is_bad_url(url):
        return None
    resp = http_get(url, timeout=18)
    if not resp:
        return None
    ctype = resp.headers.get("Content-Type", "").lower()
    if "image" not in ctype and not re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", url, re.I):
        return None
    if len(resp.content or b"") < 12_000:
        return None
    w, h, mime, var = image_meta(resp.content)
    if not w or not h or w < MIN_W or h < MIN_H or var < 20:
        return None
    return resp.content, mime, w, h


def filename_from_url(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1] or "image.jpg"
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    if "." not in name:
        name += ".jpg"
    return name[:90]


def extract_meta_images(html_text: str, base_url: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    if not html_text:
        return out
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)',
        r'<img[^>]+(?:data-src|src)=["\']([^"\']+)',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html_text, flags=re.I | re.S):
            url = urljoin(base_url, m.group(1).strip())
            meta_span = html_text[max(0, m.start()-180):m.end()+180]
            meta = re.sub(r"<[^>]+>", " ", meta_span)
            if url and url not in [x[0] for x in out] and not is_bad_url(url):
                out.append((url, meta[:600]))
            if len(out) >= 14:
                return out
    return out


def source_candidates(article: Dict) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    direct = article.get("image_url")
    if direct and not is_bad_url(direct):
        out.append((direct, "direct image_url"))
    url = article.get("url")
    if url:
        resp = http_get(url, timeout=14)
        if resp and resp.text:
            out.extend(extract_meta_images(resp.text, url))
    # Deduplicate preserving order.
    seen = set()
    clean = []
    for url, meta in out:
        if url in seen:
            continue
        seen.add(url)
        clean.append((url, meta))
    return clean[:14]


def source_photo(article: Dict, state: Dict, logger=None) -> Tuple[Optional[Tuple[bytes, str, str]], Dict]:
    attempts = []
    recent = set(state.get("recent_image_urls", []) or [])
    for url, meta in source_candidates(article):
        if url in recent:
            attempts.append({"url": url, "ok": False, "reason": "recent url duplicate"})
            continue
        if is_text_card_url(url, meta):
            attempts.append({"url": url, "ok": False, "reason": "text-card/logo/poster token"})
            continue
        fetched = fetch_image(url)
        if not fetched:
            attempts.append({"url": url, "ok": False, "reason": "fetch/size/variance failed"})
            continue
        data, mime, w, h = fetched
        # Strongly prefer real source photos; allow if URL/meta carries photo-ish source hints.
        if not has_any(url + " " + meta, PHOTO_HINT_TOKENS):
            attempts.append({"url": url, "ok": False, "reason": "no photo/source hint", "size": f"{w}x{h}"})
            continue
        attempts.append({"url": url, "ok": True, "reason": "source photo accepted", "size": f"{w}x{h}"})
        if logger:
            logger(f"source-photo accepted: {w}x{h} {url[:140]}")
        return (data, mime, filename_from_url(url)), {"strategy": "source_photo", "url": url, "attempts": attempts[-8:]}
    if logger:
        logger("source-photo unavailable; attempts=" + str(attempts[-3:]))
    return None, {"strategy": "none", "attempts": attempts[-8:]}
