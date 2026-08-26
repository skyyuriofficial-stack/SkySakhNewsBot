"""SkySakhNews stable-v10.4: mandatory source media with lossless delivery recovery.

Every published post still carries a source photo. A temporary Telegram
sendPhoto failure no longer discards the story: the publisher tries several
safe delivery transports and, if Telegram remains unavailable, stores the
already editorially-approved post in a persistent retry queue. Queued stories
are retried before fresh candidates on the next scheduled run.
"""

from __future__ import annotations

import copy
import hashlib
import html
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, Optional

import requests
from PIL import Image, ImageOps

import editorial_gate_runner as editorial

VERSION = "stable-v10.4"
editorial.VERSION = VERSION
editorial.prod.VERSION = VERSION
editorial.core.VERSION = VERSION
core = editorial.core
prod = editorial.prod

# The lower collector may discover text candidates; this layer is the final,
# authoritative media and delivery policy.
core.b.IMAGE_REQUIRED = True

PENDING_KEY = "pending_media_delivery"
EXPIRED_KEY = "expired_media_delivery"
MAX_PENDING_HOURS = max(6, int(os.getenv("MEDIA_PENDING_MAX_HOURS", "36")))
MAX_PENDING_ITEMS = max(4, int(os.getenv("MEDIA_PENDING_MAX_ITEMS", "24")))

for key in (
    "media_required_skip",
    "media_generic_skip",
    "media_ready_candidates",
    "photo_retry",
    "photo_publish",
    "photo_upload_original",
    "photo_upload_reencoded",
    "photo_upload_plain_caption",
    "photo_remote_url",
    "photo_alternate_source",
    "media_deferred",
    "media_queue_ready",
    "media_queue_unresolved",
    "media_queue_recovered",
    "media_queue_expired",
    "text_publish_blocked",
):
    core.b.STATS.setdefault(key, 0)

GENERIC_MEDIA_HOST_PARTS = (
    "upload.wikimedia.org",
    "commons.wikimedia.org",
    "images.unsplash.com",
    "unsplash.com",
    "pixabay.com",
    "pexels.com",
    "placehold.co",
    "placeholder.com",
)
GENERIC_MEDIA_PATH_PARTS = (
    "placeholder",
    "default-image",
    "default_image",
    "no-image",
    "no_image",
    "fallback",
    "category-",
    "thematic-",
    "generated-",
)

_PENDING_EXISTING: Dict[str, Dict[str, Any]] = {}
_DEFERRED_THIS_RUN: Dict[str, Dict[str, Any]] = {}
_DELIVERY_BY_URL: Dict[str, Dict[str, Any]] = {}
_EXPIRED_THIS_RUN: list[Dict[str, Any]] = []
_RECENT_IMAGE_HASHES: set[str] = set()
_RECENT_IMAGE_URLS: set[str] = set()


class TelegramPhotoError(RuntimeError):
    """Telegram delivery error with retry-safety metadata."""

    def __init__(
        self,
        message: str,
        *,
        retry_safe: bool,
        retry_after: int = 0,
    ) -> None:
        super().__init__(message)
        self.retry_safe = retry_safe
        self.retry_after = max(0, int(retry_after or 0))


def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""


def _is_generic_media_url(url: str) -> bool:
    host = _host(url)
    low_url = str(url or "").lower()
    return (
        any(part in host for part in GENERIC_MEDIA_HOST_PARTS)
        or any(part in low_url for part in GENERIC_MEDIA_PATH_PARTS)
    )


def _is_source_media(candidate: Dict[str, Any]) -> tuple[bool, str]:
    """Accept only real upstream media selected from the story page/feed."""
    image = candidate.get("image")
    image_url = str(candidate.get("image_url") or "")
    image_hash = str(candidate.get("image_hash") or "")

    if not isinstance(image, (bytes, bytearray)) or len(image) < 10_000:
        return False, "missing_image_bytes"
    if not image_url or not image_url.startswith(("http://", "https://")):
        return False, "missing_image_url"
    if not image_hash:
        return False, "missing_image_hash"
    if _is_generic_media_url(image_url):
        return False, "generic_media_url"
    return True, "source_article_or_feed"


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _pending_is_fresh(item: Dict[str, Any]) -> bool:
    base = _parse_dt(item.get("published_at")) or _parse_dt(item.get("queued_at"))
    if base is None:
        return True
    age = datetime.now(timezone.utc) - base.astimezone(timezone.utc)
    return age.total_seconds() <= MAX_PENDING_HOURS * 3600


def _normalize_photo_bytes(
    data: bytes,
    *,
    max_side: int = 1280,
    quality: int = 84,
) -> bytes:
    """Produce a conservative Telegram-safe baseline JPEG."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("empty image bytes")

    with Image.open(BytesIO(bytes(data))) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")

        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        if image.width < 320 or image.height < 180:
            raise ValueError(f"image dimensions too small: {image.size}")

        for current_quality in (quality, 78, 70, 62):
            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=current_quality,
                optimize=True,
                progressive=False,
            )
            payload = output.getvalue()
            if 1_000 <= len(payload) <= 9_500_000:
                return payload

    raise ValueError("cannot encode Telegram-safe JPEG")


def _plain_caption(caption: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(caption or ""))
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:1024]


def _telegram_credentials() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram secrets missing")
    return token, chat


def _telegram_send_photo(
    *,
    image_bytes: Optional[bytes],
    image_url: Optional[str],
    caption: str,
    parse_html: bool,
) -> Dict[str, Any]:
    token, chat = _telegram_credentials()
    data: Dict[str, Any] = {
        "chat_id": chat,
        "caption": caption,
    }
    if parse_html:
        data["parse_mode"] = "HTML"

    files = None
    if image_bytes is not None:
        files = {
            "photo": (
                "news.jpg",
                bytes(image_bytes),
                "image/jpeg",
            )
        }
    elif image_url:
        data["photo"] = image_url
    else:
        raise ValueError("photo payload missing")

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=data,
            files=files,
            timeout=(20, 90),
        )
    except requests.exceptions.ReadTimeout as exc:
        # Telegram may have accepted a request before the client timed out.
        # Do not immediately issue another send that could create a duplicate.
        raise TelegramPhotoError(
            f"Telegram read timeout: {exc}",
            retry_safe=False,
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise TelegramPhotoError(
            f"Telegram transport error: {exc}",
            retry_safe=False,
        ) from exc

    try:
        payload = response.json()
    except Exception:
        payload = {
            "ok": False,
            "description": f"non-JSON response HTTP {response.status_code}",
        }

    if response.status_code < 400 and payload.get("ok") is True:
        return payload

    parameters = payload.get("parameters") if isinstance(payload, dict) else {}
    retry_after = parameters.get("retry_after", 0) if isinstance(parameters, dict) else 0
    description = payload.get("description") if isinstance(payload, dict) else None
    raise TelegramPhotoError(
        f"Telegram HTTP {response.status_code}: {description or str(payload)[:300]}",
        retry_safe=True,
        retry_after=int(retry_after or 0),
    )


def _delivery_success(
    candidate: Dict[str, Any],
    result: Dict[str, Any],
    mode: str,
) -> Dict[str, Any]:
    candidate["_media_delivery_mode"] = mode
    _DELIVERY_BY_URL[str(candidate.get("url") or "")] = {
        "mode": mode,
        "recovered": bool(candidate.get("_pending_delivery")),
        "attempts": int(candidate.get("_media_delivery_attempts") or 0) + 1,
        "origin": str(candidate.get("media_origin") or "source_article_or_feed"),
    }
    core.b.STATS["photo_publish"] += 1
    if mode == "upload_original_html":
        core.b.STATS["photo_upload_original"] += 1
    if mode.startswith("upload_reencoded"):
        core.b.STATS["photo_upload_reencoded"] += 1
    if mode.endswith("plain_caption"):
        core.b.STATS["photo_upload_plain_caption"] += 1
    if mode.startswith("remote_source_url"):
        core.b.STATS["photo_remote_url"] += 1
    if mode.startswith("alternate_source"):
        core.b.STATS["photo_alternate_source"] += 1
    if candidate.get("_pending_delivery"):
        core.b.STATS["media_queue_recovered"] += 1
    return result


def _safe_wait(error: TelegramPhotoError, attempt: int) -> None:
    wait = error.retry_after or min(12, max(2, attempt * 2))
    time.sleep(wait)


def _try_delivery_mode(
    candidate: Dict[str, Any],
    caption: str,
    *,
    mode: str,
    image_bytes: Optional[bytes] = None,
    image_url: Optional[str] = None,
    parse_html: bool = True,
) -> Optional[Dict[str, Any]]:
    try:
        return _telegram_send_photo(
            image_bytes=image_bytes,
            image_url=image_url,
            caption=caption if parse_html else _plain_caption(caption),
            parse_html=parse_html,
        )
    except TelegramPhotoError as error:
        candidate["_delivery_error"] = str(error)[:700]
        if not error.retry_safe:
            raise
        core.b.STATS["photo_retry"] += 1
        core.b.log(
            f"sendPhoto recovery mode failed [{mode}]: "
            + str(candidate.get("title") or "")[:80]
            + f" | {str(error)[:220]}"
        )
        _safe_wait(error, int(core.b.STATS.get("photo_retry", 1)))
        return None


def _alternate_source_media(
    candidate: Dict[str, Any],
) -> Optional[tuple[bytes, str, str]]:
    """Find another valid image from the same original article."""
    url = str(candidate.get("url") or "")
    if not url:
        return None

    page = core.b.page_info(url)
    images = []
    current_url = str(candidate.get("image_url") or "")
    for media in page.get("images", []) or []:
        media_url = str(media.get("url") or "")
        if not media_url or media_url == current_url or _is_generic_media_url(media_url):
            continue
        images.append(media)

    if not images:
        return None

    image, image_url, _reason = core.b.select_image(
        images,
        str(candidate.get("title") or ""),
    )
    if not image or not image_url:
        return None

    image_hash = hashlib.sha1(bytes(image)).hexdigest()
    if image_hash in _RECENT_IMAGE_HASHES or image_url in _RECENT_IMAGE_URLS:
        return None
    return bytes(image), str(image_url), image_hash


def send_photo_with_recovery(
    candidate: Dict[str, Any],
    caption: str,
) -> Dict[str, Any]:
    """Deliver source media without discarding the story on a single failure."""
    original = bytes(candidate.get("image") or b"")
    image_url = str(candidate.get("image_url") or "")
    last_error: Optional[BaseException] = None

    try:
        result = _try_delivery_mode(
            candidate,
            caption,
            mode="upload_original_html",
            image_bytes=original,
            parse_html=True,
        )
        if result:
            return _delivery_success(candidate, result, "upload_original_html")

        normalized = _normalize_photo_bytes(original)
        candidate["image"] = normalized
        candidate["image_hash"] = hashlib.sha1(normalized).hexdigest()

        result = _try_delivery_mode(
            candidate,
            caption,
            mode="upload_reencoded_html",
            image_bytes=normalized,
            parse_html=True,
        )
        if result:
            return _delivery_success(candidate, result, "upload_reencoded_html")

        result = _try_delivery_mode(
            candidate,
            caption,
            mode="upload_reencoded_plain_caption",
            image_bytes=normalized,
            parse_html=False,
        )
        if result:
            return _delivery_success(candidate, result, "upload_reencoded_plain_caption")

        if image_url:
            result = _try_delivery_mode(
                candidate,
                caption,
                mode="remote_source_url_html",
                image_url=image_url,
                parse_html=True,
            )
            if result:
                return _delivery_success(candidate, result, "remote_source_url_html")

            result = _try_delivery_mode(
                candidate,
                caption,
                mode="remote_source_url_plain_caption",
                image_url=image_url,
                parse_html=False,
            )
            if result:
                return _delivery_success(candidate, result, "remote_source_url_plain_caption")

        alternate = _alternate_source_media(candidate)
        if alternate:
            alt_bytes, alt_url, alt_hash = alternate
            candidate["image"] = alt_bytes
            candidate["image_url"] = alt_url
            candidate["image_hash"] = alt_hash
            candidate["media_origin"] = "alternate_source_article_media"

            result = _try_delivery_mode(
                candidate,
                caption,
                mode="alternate_source_upload_html",
                image_bytes=alt_bytes,
                parse_html=True,
            )
            if result:
                return _delivery_success(candidate, result, "alternate_source_upload_html")

            result = _try_delivery_mode(
                candidate,
                caption,
                mode="alternate_source_url_html",
                image_url=alt_url,
                parse_html=True,
            )
            if result:
                return _delivery_success(candidate, result, "alternate_source_url_html")
    except TelegramPhotoError as error:
        last_error = error
    except Exception as error:
        last_error = error

    if last_error is None:
        last_error = RuntimeError(
            candidate.get("_delivery_error") or "all source-photo delivery modes rejected"
        )
    candidate["_delivery_error"] = str(last_error)[:700]
    raise RuntimeError(
        "source-photo delivery deferred: " + str(last_error)[:500]
    ) from last_error


def _row_for_storage(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reject": bool(row.get("reject", False)),
        "title_ru": str(row.get("title_ru") or ""),
        "body": [
            str(value)
            for value in (row.get("body") or [])
            if str(value).strip()
        ][:3],
        "footer": str(row.get("footer") or ""),
        "editorial_mode": str(row.get("editorial_mode") or ""),
        "editorial_gate": copy.deepcopy(row.get("editorial_gate") or {}),
    }


def _pending_payload(
    row: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    url = str(candidate.get("url") or "")
    existing = _PENDING_EXISTING.get(url) or {}
    attempts = int(existing.get("delivery_attempts") or 0) + 1
    queued_at = existing.get("queued_at") or datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    return {
        "queued_at": queued_at,
        "last_attempt_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "delivery_attempts": attempts,
        "last_error": str(candidate.get("_delivery_error") or "")[:700],
        "url": url,
        "title_hash": str(candidate.get("title_hash") or ""),
        "source": str(candidate.get("source") or ""),
        "category": str(candidate.get("category") or ""),
        "category_key": str(candidate.get("category_key") or ""),
        "footer": str(candidate.get("footer") or ""),
        "title": str(candidate.get("title") or ""),
        "source_text": str(candidate.get("source_text") or "")[:2200],
        "published_at": str(candidate.get("published_at") or ""),
        "image_url": str(candidate.get("image_url") or ""),
        "image_hash": str(candidate.get("image_hash") or ""),
        "topic_cluster": str(candidate.get("topic_cluster") or ""),
        "media_origin": str(
            candidate.get("media_origin") or "source_article_or_feed"
        ),
        "row": _row_for_storage(row),
    }


def defer_media_publication(
    row: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist a technically failed photo post instead of losing the story."""
    core.b.STATS["text_publish_blocked"] += 1
    core.b.STATS["media_deferred"] += 1
    payload = _pending_payload(row, candidate)
    _DEFERRED_THIS_RUN[payload["url"]] = payload
    core.b.log(
        "media delivery deferred, not discarded: "
        + str(candidate.get("title") or "")[:100]
    )
    return {
        "ok": False,
        "description": "source_media_delivery_deferred",
    }


def _approved_pending_row(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = copy.deepcopy(item.get("row") or {})
    audit = row.get("editorial_gate") or {}
    if (
        audit.get("approved") is True
        and int(audit.get("title_matches_source") or 0) >= 90
        and int(audit.get("category_matches_story") or 0) >= 90
        and audit.get("facts_supported") is True
        and audit.get("meaning_changed") is False
    ):
        return row
    return None


def _download_pending_media(
    item: Dict[str, Any],
) -> Optional[tuple[bytes, str, str]]:
    title = str(item.get("title") or "")
    image_url = str(item.get("image_url") or "")

    if image_url and not _is_generic_media_url(image_url):
        image, _reason = core.b.image_to_jpeg(
            {
                "url": image_url,
                "source": "article",
                "context": title,
            },
            title,
        )
        if image:
            payload = _normalize_photo_bytes(bytes(image))
            image_hash = hashlib.sha1(payload).hexdigest()
            if (
                image_hash not in _RECENT_IMAGE_HASHES
                and image_url not in _RECENT_IMAGE_URLS
            ):
                return payload, image_url, image_hash

    candidate = {
        "url": item.get("url"),
        "title": title,
        "image_url": image_url,
    }
    alternate = _alternate_source_media(candidate)
    if alternate:
        return alternate
    return None


def _pending_to_candidate(
    item: Dict[str, Any],
    index: int,
) -> Optional[Dict[str, Any]]:
    if not _pending_is_fresh(item):
        core.b.STATS["media_queue_expired"] += 1
        expired = copy.deepcopy(item)
        expired["expired_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        expired["expired_reason"] = "news_stale_before_delivery"
        _EXPIRED_THIS_RUN.append(expired)
        return None

    row = _approved_pending_row(item)
    if row is None:
        expired = copy.deepcopy(item)
        expired["expired_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        expired["expired_reason"] = "stored_editorial_gate_invalid"
        _EXPIRED_THIS_RUN.append(expired)
        return None

    media = _download_pending_media(item)
    if not media:
        core.b.STATS["media_queue_unresolved"] += 1
        return None

    image, image_url, image_hash = media
    category_key = str(item.get("category_key") or "")
    if category_key not in core.b.CAT:
        return None
    category, footer = core.b.CAT[category_key]

    core.b.STATS["media_queue_ready"] += 1
    return {
        "id": -1000 - index,
        "source": str(item.get("source") or ""),
        "category_key": category_key,
        "category": category,
        "footer": str(item.get("footer") or footer),
        "score": 1_000_000 - index,
        "reason": "deferred_media_delivery",
        "title": str(item.get("title") or ""),
        "source_text": str(item.get("source_text") or ""),
        "url": str(item.get("url") or ""),
        "image_url": image_url,
        "image": image,
        "image_hash": image_hash,
        "published_at": str(item.get("published_at") or ""),
        "title_hash": str(
            item.get("title_hash") or core.b.htitle(item.get("title") or "")
        ),
        "topic_cluster": str(item.get("topic_cluster") or ""),
        "media_type": "photo",
        "media_origin": str(
            item.get("media_origin") or "source_article_or_feed"
        ),
        "_pending_delivery": True,
        "_pending_row": row,
        "_media_delivery_attempts": int(item.get("delivery_attempts") or 0),
    }


_original_collect = core.b.collect


def collect_media_required(state):
    global _PENDING_EXISTING, _RECENT_IMAGE_HASHES, _RECENT_IMAGE_URLS

    pending_items = [
        item
        for item in (state.get(PENDING_KEY) or [])
        if isinstance(item, dict) and item.get("url")
    ]
    _PENDING_EXISTING = {
        str(item["url"]): copy.deepcopy(item)
        for item in pending_items
    }
    _RECENT_IMAGE_HASHES = {
        str(post.get("image_hash"))
        for post in (state.get("last_posts") or [])[-60:]
        if post.get("image_hash")
    }
    _RECENT_IMAGE_URLS = {
        str(post.get("image_url"))
        for post in (state.get("last_posts") or [])[-60:]
        if post.get("image_url")
    }

    fresh_candidates = _original_collect(state)
    ready = []

    for index, item in enumerate(pending_items):
        candidate = _pending_to_candidate(item, index)
        if candidate:
            ready.append(candidate)

    pending_urls = set(_PENDING_EXISTING)
    for candidate in fresh_candidates:
        if str(candidate.get("url") or "") in pending_urls:
            continue

        ok, reason = _is_source_media(candidate)
        if not ok:
            if reason.startswith("generic_"):
                core.b.STATS["media_generic_skip"] += 1
            else:
                core.b.STATS["media_required_skip"] += 1
            core.b.log(
                f"media-required skip [{reason}]: "
                + str(candidate.get("title") or "")[:100]
            )
            continue

        candidate["media_type"] = "photo"
        candidate["media_origin"] = reason
        ready.append(candidate)

    core.b.STATS["media_ready_candidates"] = len(ready)
    core.b.STATS["candidates"] = len(ready)
    return ready


core.b.collect = collect_media_required


_original_ordered = core.b.ordered


def ordered_with_delivery_queue(candidates):
    pending = [
        candidate
        for candidate in candidates
        if candidate.get("_pending_delivery")
    ]
    fresh = [
        candidate
        for candidate in candidates
        if not candidate.get("_pending_delivery")
    ]
    return pending + _original_ordered(fresh)


core.b.ordered = ordered_with_delivery_queue


_original_valid_post = core.b.valid_post


def valid_post_with_pending(candidate):
    if candidate.get("_pending_delivery"):
        row = copy.deepcopy(candidate.get("_pending_row") or {})
        audit = row.get("editorial_gate") or {}
        if audit.get("approved") is True:
            editorial.AUDIT_BY_URL[
                str(candidate.get("url") or "")
            ] = copy.deepcopy(audit)
            return row
        return None
    return _original_valid_post(candidate)


core.b.valid_post = valid_post_with_pending
core.b.send_photo = send_photo_with_recovery

# news_bot_v9.main calls send_text only after sendPhoto raises. Turning this
# callback into a persistent queue preserves the post without violating the
# rule that every publication must contain source media.
core.send_text = defer_media_publication


_original_save_state = core.b.save_state


def _merge_pending_queue(state: Dict[str, Any]) -> None:
    published_urls = {
        str(value)
        for value in (state.get("published_urls") or [])
        if value
    }
    merged = {
        url: copy.deepcopy(item)
        for url, item in _PENDING_EXISTING.items()
        if url not in published_urls
    }
    for url, item in _DEFERRED_THIS_RUN.items():
        if url not in published_urls:
            merged[url] = copy.deepcopy(item)

    expired_urls = {
        str(item.get("url") or "")
        for item in _EXPIRED_THIS_RUN
    }
    for url in expired_urls:
        merged.pop(url, None)

    queue = sorted(
        merged.values(),
        key=lambda item: str(item.get("queued_at") or ""),
    )[:MAX_PENDING_ITEMS]
    state[PENDING_KEY] = queue

    if _EXPIRED_THIS_RUN:
        existing = [
            item
            for item in (state.get(EXPIRED_KEY) or [])
            if isinstance(item, dict)
        ]
        state[EXPIRED_KEY] = (
            existing + copy.deepcopy(_EXPIRED_THIS_RUN)
        )[-40:]


def save_state_with_media_policy(state):
    _merge_pending_queue(state)

    run = state.get("last_run") or {}
    run["version"] = VERSION
    run["media_policy"] = {
        "required": True,
        "allowed": ["source_photo", "source_video"],
        "implemented_publish_mode": "source_photo",
        "text_only_allowed": False,
        "delivery_failure_policy": "retry_transports_then_persistent_queue",
        "ready_candidates": int(
            core.b.STATS.get("media_ready_candidates", 0)
        ),
        "missing_media_rejected": int(
            core.b.STATS.get("media_required_skip", 0)
        ),
        "generic_media_rejected": int(
            core.b.STATS.get("media_generic_skip", 0)
        ),
        "photo_retries": int(core.b.STATS.get("photo_retry", 0)),
        "photo_published": int(core.b.STATS.get("photo_publish", 0)),
        "deferred_this_run": int(core.b.STATS.get("media_deferred", 0)),
        "pending_queue_size": len(state.get(PENDING_KEY) or []),
        "pending_ready": int(core.b.STATS.get("media_queue_ready", 0)),
        "pending_recovered": int(
            core.b.STATS.get("media_queue_recovered", 0)
        ),
        "pending_unresolved": int(
            core.b.STATS.get("media_queue_unresolved", 0)
        ),
        "pending_expired": int(
            core.b.STATS.get("media_queue_expired", 0)
        ),
        "text_publication_blocked": int(
            core.b.STATS.get("text_publish_blocked", 0)
        ),
    }

    published = int(run.get("published") or 0)
    if published:
        for post in (state.get("last_posts") or [])[-published:]:
            url = str(post.get("url") or "")
            delivery = _DELIVERY_BY_URL.get(url) or {}
            post["media_required"] = True
            post["media_type"] = "photo"
            post["media_origin"] = str(
                delivery.get("origin") or "source_article_or_feed"
            )
            if delivery:
                mode = str(delivery.get("mode") or "source_photo")
                post["media_delivery_mode"] = mode
                post["media_delivery_recovered"] = bool(
                    delivery.get("recovered")
                )
                post["media_delivery_attempts"] = int(
                    delivery.get("attempts") or 1
                )
                post["publish_method"] = "sendPhoto/" + mode

    state["last_run"] = run
    _original_save_state(state)


core.b.save_state = save_state_with_media_policy


def main():
    editorial.main()


if __name__ == "__main__":
    main()
