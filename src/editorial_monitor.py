"""Continuous self-healing monitor for the SkySakhNews production feed.

This job is intentionally independent from the publisher schedule. Every hour it
re-reads the actual state of the Telegram feed, re-runs the current editorial
policy against recent posts, edits/deletes recent v12 posts when the policy can
prove they are wrong, and records a machine-readable health report.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import editorial_policy as policy
import news_director as director
import publication_auditor
import publisher

VERSION = "editorial-monitor-v1"
ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
STATUS_PATH = ROOT / "monitor_status.json"


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _last_run_age_hours(state: Dict[str, Any]) -> Optional[float]:
    run = state.get("last_run") or {}
    finished = _parse_dt(run.get("finished_sakhalin"))
    if not finished:
        return None
    age = datetime.now(timezone.utc) - finished.astimezone(timezone.utc)
    return round(age.total_seconds() / 3600.0, 2)


def _active_recent_posts(state: Dict[str, Any]):
    return [
        post
        for post in (state.get("last_posts") or [])[-20:]
        if isinstance(post, dict) and not post.get("auto_deleted")
    ]


def run_monitor(*, mutate: bool = True) -> Dict[str, Any]:
    state = _load_state()
    now_local = datetime.now(publisher.core.b.TZ)

    audit = publication_auditor.audit_recent_posts(
        state,
        category_map=publisher.core.b.CAT,
        render_caption=publisher.core.b.caption,
        mutate=mutate,
    )

    issues = []
    checked_posts = []
    for post in _active_recent_posts(state):
        candidate = {
            "title": post.get("title"),
            "title_original": post.get("title_original"),
            "source_text": post.get("source_text_excerpt") or "",
            "source": post.get("source"),
            "url": post.get("url"),
            "category_key": post.get("category_key"),
            "category": post.get("category"),
            "footer": post.get("footer"),
            "published_at": post.get("published_at"),
        }
        review = director.review_candidate(candidate)
        title_issues = policy.title_quality_issues(str(post.get("title") or ""))
        media_ok = bool(
            post.get("with_image")
            and post.get("image_url")
            and post.get("image_hash")
            and post.get("telegram_message_id") is not None
        )
        category_ok = (
            review.get("approved") is True
            and review.get("corrected_category") == post.get("category_key")
        )
        row = post.get("published_row") or {}
        contract = post.get("publication_contract") or {}
        contract_ok = bool(contract.get("approved")) if row else True

        item = {
            "message_id": post.get("telegram_message_id"),
            "title": post.get("title"),
            "category_key": post.get("category_key"),
            "publisher_version": post.get("publisher_version"),
            "category_ok": category_ok,
            "title_ok": not title_issues,
            "media_ok": media_ok,
            "contract_ok": contract_ok,
            "review_reason": review.get("reason"),
            "corrected_category": review.get("corrected_category"),
            "title_issues": title_issues,
        }
        checked_posts.append(item)

        if str(post.get("publisher_version") or "").startswith("stable-v12."):
            if not category_ok:
                issues.append({"type": "category", **item})
            if title_issues:
                issues.append({"type": "title", **item})
            if not media_ok:
                issues.append({"type": "media", **item})
            if not contract_ok:
                issues.append({"type": "contract", **item})

    run = state.get("last_run") or {}
    last_run_age = _last_run_age_hours(state)
    if run.get("status") not in {None, "ok"}:
        issues.append({
            "type": "publisher_status",
            "status": run.get("status"),
            "version": run.get("version"),
        })

    # Scheduled publisher runs every three hours between 07:00 and 22:00.
    # At night the 22:00 run may legitimately be up to nine hours old.
    freshness_limit = 4.5 if 7 <= now_local.hour <= 23 else 10.5
    if last_run_age is not None and last_run_age > freshness_limit:
        issues.append({
            "type": "publisher_stale",
            "age_hours": last_run_age,
            "limit_hours": freshness_limit,
        })

    unresolved = int(audit.get("unresolved") or 0)
    failed_actions = list(audit.get("failed_actions") or [])
    if unresolved:
        issues.append({
            "type": "post_audit_unresolved",
            "count": unresolved,
            "items": (audit.get("unresolved_items") or [])[-8:],
        })
    if failed_actions:
        issues.append({
            "type": "post_audit_action_failure",
            "count": len(failed_actions),
            "items": failed_actions[-8:],
        })

    balance = director.balance_snapshot(state)
    status = "healthy" if not issues else "error"
    report = {
        "version": VERSION,
        "publisher_version": publisher.VERSION,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked_at_sakhalin": now_local.isoformat(timespec="seconds"),
        "status": status,
        "mutations_enabled": bool(mutate),
        "issues": issues,
        "last_run": {
            "version": run.get("version"),
            "status": run.get("status"),
            "finished_sakhalin": run.get("finished_sakhalin"),
            "age_hours": last_run_age,
            "published": run.get("published"),
        },
        "post_audit": audit,
        "recent_active_posts": checked_posts,
        "balance": balance,
    }

    state["continuous_editorial_monitor"] = report
    _save_json(STATE_PATH, state)
    _save_json(STATUS_PATH, report)
    return report


def main() -> None:
    mutate = os.getenv("POST_AUDIT_AUTOCORRECT", "1") == "1"
    report = run_monitor(mutate=mutate)
    print(json.dumps({
        "status": report.get("status"),
        "publisher_version": report.get("publisher_version"),
        "issues": report.get("issues"),
        "post_audit": {
            "checked": (report.get("post_audit") or {}).get("checked"),
            "corrected": len((report.get("post_audit") or {}).get("corrected") or []),
            "deleted": len((report.get("post_audit") or {}).get("deleted") or []),
            "unresolved": (report.get("post_audit") or {}).get("unresolved"),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
