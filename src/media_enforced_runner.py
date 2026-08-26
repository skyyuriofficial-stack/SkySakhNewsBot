"""SkySakhNews stable-v10.3: every published post must carry source media.

This runner is the final production layer.  It does not generate generic
category pictures and never falls back to a text-only Telegram post.  A story
without a safe image attached to the original article/RSS entry is skipped.
"""

from __future__ import annotations

import time
import urllib.parse
from typing import Any, Dict

import editorial_gate_runner as editorial

VERSION = "stable-v10.3"
editorial.VERSION = VERSION
editorial.prod.VERSION = VERSION
editorial.core.VERSION = VERSION
core = editorial.core
prod = editorial.prod

# The lower collector is intentionally allowed to discover text candidates;
# this final layer is the authoritative media gate.
core.b.IMAGE_REQUIRED = True

for key in (
    "media_required_skip",
    "media_generic_skip",
    "media_ready_candidates",
    "photo_retry",
    "photo_publish",
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


def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""


def _is_source_media(candidate: Dict[str, Any]) -> tuple[bool, str]:
    """Accept only a real upstream image selected from the story page/feed."""
    image = candidate.get("image")
    image_url = str(candidate.get("image_url") or "")
    image_hash = str(candidate.get("image_hash") or "")

    if not isinstance(image, (bytes, bytearray)) or len(image) < 10_000:
        return False, "missing_image_bytes"
    if not image_url or not image_url.startswith(("http://", "https://")):
        return False, "missing_image_url"
    if not image_hash:
        return False, "missing_image_hash"

    host = _host(image_url)
    low_url = image_url.lower()
    if any(part in host for part in GENERIC_MEDIA_HOST_PARTS):
        return False, "generic_media_host"
    if any(part in low_url for part in GENERIC_MEDIA_PATH_PARTS):
        return False, "generic_media_path"

    # Current v8/v9 collection obtains images exclusively from RSS media or the
    # exact original article page.  Record this invariant explicitly.
    return True, "source_article_or_feed"


_original_collect = core.b.collect


def collect_media_required(state):
    candidates = _original_collect(state)
    ready = []

    for candidate in candidates:
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


_original_send_photo = core.b.send_photo


def send_photo_with_retry(candidate, caption):
    last_error = None
    for attempt in range(1, 4):
        try:
            result = _original_send_photo(candidate, caption)
            if result and result.get("ok"):
                core.b.STATS["photo_publish"] += 1
                return result
            last_error = RuntimeError(f"Telegram sendPhoto returned: {result}")
        except Exception as exc:
            last_error = exc

        if attempt < 3:
            core.b.STATS["photo_retry"] += 1
            core.b.log(
                f"sendPhoto retry {attempt}/2: "
                + str(candidate.get("title") or "")[:80]
                + f" | {str(last_error)[:220]}"
            )
            time.sleep(attempt * 2)

    raise RuntimeError(f"sendPhoto failed after 3 attempts: {last_error}")


core.b.send_photo = send_photo_with_retry


def block_text_publication(_row, candidate):
    """Photo failure means skip this candidate, never a text-only post."""
    core.b.STATS["text_publish_blocked"] += 1
    core.b.log(
        "text-only publication blocked by media policy: "
        + str(candidate.get("title") or "")[:100]
    )
    return {"ok": False, "description": "source_media_required"}


# news_bot_v9.main resolves send_text from its module global namespace.
core.send_text = block_text_publication


_original_save_state = core.b.save_state


def save_state_with_media_policy(state):
    run = state.get("last_run") or {}
    run["version"] = VERSION
    run["media_policy"] = {
        "required": True,
        "allowed": ["source_photo", "source_video"],
        "implemented_publish_mode": "source_photo",
        "text_only_allowed": False,
        "ready_candidates": int(core.b.STATS.get("media_ready_candidates", 0)),
        "missing_media_rejected": int(core.b.STATS.get("media_required_skip", 0)),
        "generic_media_rejected": int(core.b.STATS.get("media_generic_skip", 0)),
        "photo_retries": int(core.b.STATS.get("photo_retry", 0)),
        "photo_published": int(core.b.STATS.get("photo_publish", 0)),
        "text_publication_blocked": int(core.b.STATS.get("text_publish_blocked", 0)),
    }

    published = int(run.get("published") or 0)
    if published:
        for post in (state.get("last_posts") or [])[-published:]:
            post["media_required"] = True
            post["media_type"] = "photo"
            post["media_origin"] = "source_article_or_feed"

    state["last_run"] = run
    _original_save_state(state)


core.b.save_state = save_state_with_media_policy


def main():
    editorial.main()


if __name__ == "__main__":
    main()
