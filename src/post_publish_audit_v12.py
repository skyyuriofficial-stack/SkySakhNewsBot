"""Immediate fail-safe audit of posts emitted by stable-v12.0.

The pre-publication gate is primary. This watchdog independently re-reads the
persisted Telegram records. A post that somehow violates category, title,
quality or media invariants is deleted immediately and marked in state.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

import quality_v12 as quality

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
VERSION = "stable-v12.0"


def telegram_delete(token: str, chat_id: Any, message_id: Any) -> Dict[str, Any]:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/deleteMessage",
        data={"chat_id": str(chat_id), "message_id": str(message_id)},
        timeout=30,
    )
    try:
        return response.json()
    except Exception:
        return {"ok": False, "description": f"HTTP {response.status_code}: non-JSON"}


def audit_post(post: Dict[str, Any]) -> Dict[str, Any]:
    candidate = {
        "title": post.get("source_title") or post.get("title"),
        "source_text": post.get("source_text_excerpt") or " ".join(post.get("final_body") or []),
        "source": post.get("source"),
        "category_key": post.get("category_key"),
        "url": post.get("url"),
    }
    result = quality.review(
        candidate,
        title_override=post.get("title"),
        body_override=(post.get("source_text_excerpt") or "") + " " + " ".join(post.get("final_body") or []),
    )
    metadata = post.get("quality_v12") or {}
    failures: List[str] = []
    if result.get("approved") is not True:
        failures.append("quality_review_rejected:" + str(result.get("reason")))
    if result.get("corrected_category") != post.get("category_key"):
        failures.append(
            "category_mismatch:" + str(post.get("category_key"))
            + "->" + str(result.get("corrected_category"))
        )
    if metadata.get("approved") is not True:
        failures.append("missing_or_failed_prepublication_quality_gate")
    if metadata.get("prepublication_checked") is not True:
        failures.append("prepublication_check_marker_missing")
    if post.get("with_image") is not True or not post.get("image_url") or not post.get("image_hash"):
        failures.append("source_media_invariant_failed")
    if not str(post.get("publish_method") or "").startswith("sendPhoto/"):
        failures.append("not_published_as_photo")
    title_ok, title_issues = quality.title_quality(quality.sanitize_title(post.get("title")))
    if not title_ok:
        failures.extend("title:" + issue for issue in title_issues)
    return {"ok": not failures, "failures": failures, "review": quality.compact(result)}


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    run = state.get("last_run") or {}
    if run.get("version") != VERSION:
        print("post-publish audit skipped: latest run is not stable-v12.0")
        return

    published = int(run.get("published") or 0)
    posts = (state.get("last_posts") or [])[-published:] if published else []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    default_chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = []
    deleted_count = 0

    for post in posts:
        result = audit_post(post)
        record = {
            "url": post.get("url"), "title": post.get("title"),
            "category_key": post.get("category_key"),
            "telegram_message_id": post.get("telegram_message_id"), **result,
        }
        if not result["ok"]:
            chat_id = post.get("telegram_chat_id") or default_chat
            message_id = post.get("telegram_message_id")
            deletion = {"ok": False, "description": "Telegram credentials or message id missing"}
            if token and chat_id and message_id:
                deletion = telegram_delete(token, chat_id, message_id)
            record["delete_result"] = deletion
            if deletion.get("ok") is True:
                deleted_count += 1
                post["deleted_at"] = checked_at
                post["post_publish_status"] = "deleted"
            else:
                post["post_publish_status"] = "invalid_delete_failed"
            post["post_publish_failures"] = result["failures"]
        else:
            post["post_publish_status"] = "audited_ok"
            post["post_publish_audited_at"] = checked_at
        records.append(record)

    audit = {
        "version": VERSION, "checked_at": checked_at, "checked": len(posts),
        "passed": sum(1 for row in records if row["ok"]),
        "failed": sum(1 for row in records if not row["ok"]),
        "deleted": deleted_count, "all_pass": all(row["ok"] for row in records),
        "items": records,
    }
    run["post_publish_audit_v12"] = audit
    run["visible_published"] = max(0, published - deleted_count)
    state["last_run"] = run
    state["last_post_publish_audit_v12"] = audit
    state["news_balance"] = quality.balance(state)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in ("checked", "passed", "failed", "deleted", "all_pass")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
