from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import editorial_hardening

editorial_hardening.install()

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
STATUS_PATH = ROOT / "monitor_status.json"
TELEGRAM_PATH = ROOT / "telegram_health.json"
MONITOR_MAX_AGE_MINUTES = 40


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _dedupe(values: List[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


def production_report(state=None, monitor=None, telegram=None) -> Dict[str, Any]:
    state = state if isinstance(state, dict) else _load(STATE_PATH)
    monitor = monitor if isinstance(monitor, dict) else _load(STATUS_PATH)
    telegram = telegram if isinstance(telegram, dict) else (_load(TELEGRAM_PATH) or state.get("telegram_health") or {})
    run = state.get("last_run") or {}
    critical: List[str] = []
    warnings: List[str] = []

    if telegram.get("status") != "healthy":
        critical.append("telegram_unhealthy:" + str(telegram.get("error_kind") or "unknown"))
    if run.get("version") != "stable-v12.1":
        critical.append("last_run_version_invalid")
    if run.get("status") != "ok":
        critical.append("last_run_not_ok")
    if not run.get("finished_sakhalin"):
        critical.append("last_run_missing_finished_sakhalin")

    stats = run.get("stats") or {}
    published = int(run.get("published") or 0)
    telegram_fail = int(stats.get("telegram_fail") or 0)
    if telegram_fail:
        critical.append(f"telegram_fail:{telegram_fail}")
    contract_blocked = int(stats.get("publication_contract_blocked") or 0)
    if contract_blocked:
        warnings.append(f"publication_contract_blocked:{contract_blocked}")

    media = run.get("media_policy") or {}
    if int(media.get("pending_ready") or 0) and published == 0:
        critical.append("pending_ready_but_nothing_published")
    if int(media.get("deferred_this_run") or 0):
        critical.append("delivery_deferred_this_run:" + str(media.get("deferred_this_run")))

    posts = (state.get("last_posts") or [])[-published:] if published else []
    groups = []
    for post in posts:
        contract = post.get("publication_contract") or {}
        if contract.get("approved") is not True or contract.get("issues"):
            critical.append("published_contract_invalid:" + str(post.get("title") or "")[:120])
        if not post.get("with_image") or not post.get("image_url") or not post.get("image_hash"):
            critical.append("published_media_invalid:" + str(post.get("title") or "")[:120])
        group = (post.get("news_director") or {}).get("group")
        if group:
            groups.append(str(group))
    if len(groups) == 2 and len(set(groups)) != 2:
        critical.append("published_group_diversity_failed:" + ",".join(groups))

    if monitor and monitor.get("status") != "healthy":
        warnings.append("feed_monitor_reports_problems")
    audit = monitor.get("post_audit") or {}
    if int(audit.get("unresolved") or 0):
        warnings.append("post_audit_unresolved:" + str(audit.get("unresolved")))
    if audit.get("failed_actions"):
        warnings.append("post_audit_failed_actions:" + str(len(audit.get("failed_actions") or [])))

    for item in [value for value in (state.get("pending_media_delivery") or []) if isinstance(value, dict)]:
        candidate = {
            "title": item.get("title"), "source_text": item.get("source_text"),
            "category_key": item.get("category_key"), "url": item.get("url"), "source": item.get("source"),
        }
        quality = editorial_hardening.content_quality_issues(candidate, item.get("row") or {})
        if quality:
            warnings.append("unsafe_pending:" + str(item.get("title") or "")[:80] + ":" + ",".join(quality))

    critical = _dedupe(critical)
    warnings = _dedupe(warnings)
    return {
        "mode": "production",
        "execution_status": "error" if critical else "healthy",
        "service_status": "error" if critical else ("degraded" if warnings else "healthy"),
        "critical": critical,
        "warnings": warnings,
    }


def monitor_report(status=None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    status = status if isinstance(status, dict) else _load(STATUS_PATH)
    now = now or datetime.now(timezone.utc)
    critical: List[str] = []
    warnings: List[str] = []

    if not status:
        critical.append("monitor_status_missing_or_invalid")
    else:
        checked = _parse(status.get("checked_at_utc"))
        if checked is None:
            critical.append("monitor_checked_at_missing_or_invalid")
        else:
            age_minutes = (now - checked.astimezone(timezone.utc)).total_seconds() / 60.0
            if age_minutes > MONITOR_MAX_AGE_MINUTES:
                critical.append(f"monitor_status_stale:{age_minutes:.1f}m")
        if status.get("publisher_version") != "stable-v12.1":
            critical.append("monitor_publisher_version_invalid")
        if not isinstance(status.get("post_audit"), dict):
            critical.append("monitor_post_audit_missing")

        if status.get("status") != "healthy":
            warnings.append("feed_status:" + str(status.get("status") or "unknown"))
        for item in status.get("issues") or []:
            if isinstance(item, dict):
                warnings.append("feed_issue:" + str(item.get("type") or "unknown"))
            else:
                warnings.append("feed_issue:" + str(item))
        audit = status.get("post_audit") or {}
        if int(audit.get("unresolved") or 0):
            warnings.append("post_audit_unresolved:" + str(audit.get("unresolved")))
        if audit.get("failed_actions"):
            warnings.append("post_audit_failed_actions:" + str(len(audit.get("failed_actions") or [])))

    critical = _dedupe(critical)
    warnings = _dedupe(warnings)
    return {
        "mode": "monitor",
        "execution_status": "error" if critical else "healthy",
        "feed_status": status.get("status") if status else "unknown",
        "critical": critical,
        "warnings": warnings,
    }


def production_issues() -> List[str]:
    return production_report()["critical"]


def monitor_issues() -> List[str]:
    return monitor_report()["critical"]


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "production").strip().lower()
    report = production_report() if mode == "production" else monitor_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("execution_status") == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
