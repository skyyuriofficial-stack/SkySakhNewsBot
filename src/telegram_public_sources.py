from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

import requests


# Owner-required public Telegram sources. They are scanned on every production
# collection pass, but their posts still have to pass the normal SkySakhNews
# newsworthiness, freshness, category, deduplication and media contracts.
PUBLIC_TELEGRAM_SOURCES = (
    {
        "name": "TechMedia",
        "handle": "techmedia",
        "url": "https://t.me/s/techmedia",
        "weight": 90,
    },
    {
        "name": "Exploit",
        "handle": "exploitex",
        "url": "https://t.me/s/exploitex",
        "weight": 90,
    },
)

_DATA_POST_RE = re.compile(r'data-post=["\']([^"\']+/\d+)["\']', flags=re.I)
_MESSAGE_TEXT_RE = re.compile(
    r'<div[^>]+class=["\'][^"\']*tgme_widget_message_text[^"\']*["\'][^>]*>'
    r'(.*?)</div>',
    flags=re.I | re.S,
)
_DATETIME_RE = re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', flags=re.I)
_BACKGROUND_IMAGE_RE = re.compile(
    r'background-image\s*:\s*url\((?:["\'])(.*?)(?:["\'])\)',
    flags=re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>", flags=re.S)
_BR_RE = re.compile(r"<br\s*/?>", flags=re.I)
_BLOCK_END_RE = re.compile(r"</(?:p|blockquote|li)>", flags=re.I)
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _clean_fragment(fragment: str) -> str:
    value = _BR_RE.sub("\n", fragment or "")
    value = _BLOCK_END_RE.sub("\n", value)
    value = _TAG_RE.sub(" ", value)
    value = html.unescape(value)
    lines = []
    for raw in value.splitlines():
        line = _SPACE_RE.sub(" ", raw).strip()
        if line:
            lines.append(line)
    return _BLANK_RE.sub("\n\n", "\n".join(lines)).strip()


def _parse_datetime(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _headline(text: str, *, limit: int = 220) -> str:
    first = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    first = re.sub(r"^(?:[⚡❗‼️🔥🚨]+\s*)+", "", first).strip()
    if len(first) <= limit:
        return first
    shortened = first[:limit].rsplit(" ", 1)[0].strip()
    return (shortened or first[:limit]).rstrip(" ,;:-") + "…"


def parse_public_channel(page_text: str, source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Parse Telegram's public /s/ preview without private API credentials."""
    handle = str(source.get("handle") or "").strip().lstrip("@").lower()
    if not handle:
        return []

    matches = list(_DATA_POST_RE.finditer(page_text or ""))
    rows: List[Dict[str, Any]] = []
    seen = set()

    for index, match in enumerate(matches):
        data_post = html.unescape(match.group(1)).strip().lstrip("/")
        if not data_post.lower().startswith(handle + "/"):
            continue
        if data_post in seen:
            continue
        seen.add(data_post)

        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
        chunk = page_text[start:end]

        text_match = _MESSAGE_TEXT_RE.search(chunk)
        body = _clean_fragment(text_match.group(1)) if text_match else ""
        # Telegram can expose media-only/meme posts; those are not safe factual
        # news candidates for the text-grounded editorial pipeline.
        if len(body) < 40:
            continue

        date_match = _DATETIME_RE.search(chunk)
        published = _parse_datetime(date_match.group(1) if date_match else "")
        if published is None:
            continue

        image_match = _BACKGROUND_IMAGE_RE.search(chunk)
        image_url = html.unescape(image_match.group(1)).strip() if image_match else None
        post_url = "https://t.me/" + data_post
        rows.append(
            {
                "source": str(source.get("name") or handle),
                "handle": handle,
                "url": post_url,
                "published_at": published,
                "title": _headline(body),
                "text": body,
                "image_url": image_url,
            }
        )

    rows.sort(key=lambda item: item["published_at"], reverse=True)
    return rows


def fetch_public_channel(
    source: Mapping[str, Any],
    *,
    timeout: int = 25,
    limit: int = 18,
) -> List[Dict[str, Any]]:
    url = str(source.get("url") or "").strip()
    if not url:
        return []
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 SkySakhNewsBot/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_public_channel(response.text[:2_000_000], source)[: max(1, int(limit))]
