"""Self-healing audit for posts published by SkySakhNews v12.

Every v12 photo post stores its source excerpt, final row, Telegram identifiers
and publication contract. On the next run this module re-evaluates recent v12
posts under the current policy. It may edit a caption when only title/category
needs correction, or delete a v12 post that is no longer a valid news item.
Legacy posts are reported but never mutated automatically.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

import requests

import editorial_policy as policy
import news_director as director

VERSION = "post-audit-v1.1"
MAX_AUDIT_POSTS = 20
MAX_MUTATION_AGE_HOURS = 48


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _within_mutation_window(post: Mapping[str, Any]) -> bool:
    dt = _parse_dt(post.get("time_sakhalin")) or _parse_dt(post.get("published_at"))
    if dt is None:
        return False
    age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return 0 <= age.total_seconds() <= MAX_MUTATION_AGE_HOURS * 3600


def _telegram_call(method: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "description": "telegram_token_missing"}
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            data=dict(data),
            timeout=(15, 45),
        )
        payload = response.json()
    except Exception as exc:
        return {"ok": False, "description": f"{type(exc).__name__}: {str(exc)[:300]}"}
    if response.status_code >= 400 or payload.get("ok") is not True:
        return {
            "ok": False,
            "description": str(payload.get("description") or payload)[:400],
        }
    return payload


def _candidate_from_post(post: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "title": post.get("title"),
        "title_original": post.get("title_original"),
        "source_text": post.get("source_text_excerpt") or "",
        "source": post.get("source"),
        "url": post.get("url"),
        "category_key": post.get("category_key"),
        "category": post.get("category"),
        "footer": post.get("footer"),
        "published_at": post.get("published_at"),
        "title_hash": post.get("title_hash"),
        "topic_cluster": post.get("topic_cluster"),
    }


def audit_recent_posts(
    state: MutableMapping[str, Any],
    *,
    category_map: Mapping[str, tuple[str, str]],
    render_caption: Callable[[Mapping[str, Any], Mapping[str, Any]], str],
    mutate: bool = True,
) -> Dict[str, Any]:
    checked = 0
    passed = 0
    anomalies = []
    corrected = []
    deleted = []
    failed_actions = []

    posts = [
        post for post in (state.get("last_posts") or [])[-MAX_AUDIT_POSTS:]
        if isinstance(post, dict) and not post.get("auto_deleted")
    ]

    for post in posts:
        checked += 1
        candidate = _candidate_from_post(post)
        row = copy.deepcopy(post.get("published_row") or {})
        review = director.review_candidate(candidate)
        contract = (
            director.validate_final(candidate, row)
            if row
            else {
                "approved": bool(review.get("approved"))
                and review.get("corrected_category") == post.get("category_key"),
                "issues": [] if review.get("approved") else [str(review.get("reason"))],
            }
        )

        if review.get("approved") and contract.get("approved"):
            passed += 1
            post["post_audit"] = {
                "version": VERSION,
                "approved": True,
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            continue

        anomaly = {
            "title": post.get("title"),
            "url": post.get("url"),
            "publisher_version": post.get("publisher_version"),
            "category_key": post.get("category_key"),
            "corrected_category": review.get("corrected_category"),
            "reason": review.get("reason"),
            "contract_issues": list(contract.get("issues") or [])[:10],
        }
        anomalies.append(anomaly)
        post["post_audit"] = {
            "version": VERSION,
            "approved": False,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": review.get("reason"),
            "issues": list(contract.get("issues") or [])[:10],
        }

        # Never rewrite historical posts created by an older policy.
        if (
            not mutate
            or not str(post.get("publisher_version") or "").startswith("stable-v12.")
        ):
            continue
        if not _within_mutation_window(post):
            continue
        message_id = post.get("telegram_message_id")
        chat_id = post.get("telegram_chat_id")
        if message_id is None or chat_id is None:
            continue

        corrected_category = review.get("corrected_category")
        if review.get("approved") and corrected_category in category_map and row:
            repaired = dict(candidate)
            repaired["category_key"] = corrected_category
            repaired["category"], repaired["footer"] = category_map[corrected_category]
            repaired_title = str(review.get("title_corrected") or repaired.get("title") or "")
            row["title_ru"] = repaired_title
            caption = render_caption(row, repaired)
            result = _telegram_call(
                "editMessageCaption",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
            )
            if result.get("ok"):
                post.update({
                    "title": repaired_title,
                    "category_key": corrected_category,
                    "category": repaired["category"],
                    "footer": repaired["footer"],
                    "published_caption": caption,
                    "published_row": row,
                })
                post["post_audit"]["auto_action"] = "caption_corrected"
                corrected.append({"message_id": message_id, **anomaly})
            else:
                failed_actions.append({
                    "action": "editMessageCaption",
                    "message_id": message_id,
                    "error": result.get("description"),
                })
            continue

        result = _telegram_call(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": message_id},
        )
        if result.get("ok"):
            post["post_audit"]["auto_action"] = "deleted_invalid_v12_post"
            post["auto_deleted"] = True
            deleted.append({"message_id": message_id, **anomaly})
        else:
            failed_actions.append({
                "action": "deleteMessage",
                "message_id": message_id,
                "error": result.get("description"),
            })

    resolved_keys = {
        (item.get("url"), item.get("title"))
        for item in corrected + deleted
    }
    unresolved = [
        item for item in anomalies
        if str(item.get("publisher_version") or "").startswith("stable-v12.")
        and (item.get("url"), item.get("title")) not in resolved_keys
    ]

    report = {
        "version": VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked": checked,
        "passed": passed,
        "anomalies": anomalies[-20:],
        "corrected": corrected[-20:],
        "deleted": deleted[-20:],
        "failed_actions": failed_actions[-20:],
        "unresolved": len(unresolved),
        "unresolved_items": unresolved[-20:],
        "mutations_enabled": bool(mutate),
        "legacy_posts_mutated": False,
    }
    state["post_publication_audit"] = report
    return report
