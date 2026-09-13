from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import editorial_hardening

editorial_hardening.install()

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
STATUS_PATH = ROOT / "monitor_status.json"
TELEGRAM_PATH = ROOT / "telegram_health.json"


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def production_issues() -> List[str]:
    state = _load(STATE_PATH)
    monitor = _load(STATUS_PATH)
    telegram = _load(TELEGRAM_PATH) or state.get("telegram_health") or {}
    run = state.get("last_run") or {}
    issues: List[str] = []

    if telegram.get("status") != "healthy":
        issues.append("telegram_unhealthy:" + str(telegram.get("error_kind") or "unknown"))

    if run.get("version") != "stable-v12.1":
        issues.append("last_run_version_invalid")
    if run.get("status") != "ok":
        issues.append("last_run_not_ok")
    if not run.get("finished_sakhalin"):
        issues.append("last_run_missing_finished_sakhalin")

    stats = run.get("stats") or {}
    published = int(run.get("published") or 0)
    telegram_fail = int(stats.get("telegram_fail") or 0)
    if telegram_fail:
        issues.append(f"telegram_fail:{telegram_fail}")
    if int(stats.get("publication_contract_blocked") or 0):
        issues.append("publication_contract_blocked:" + str(stats.get("publication_contract_blocked")))

    media = run.get("media_policy") or {}
    if int(media.get("pending_ready") or 0) and published == 0:
        issues.append("pending_ready_but_nothing_published")
    if int(media.get("deferred_this_run") or 0):
        issues.append("delivery_deferred_this_run:" + str(media.get("deferred_this_run")))

    posts = (state.get("last_posts") or [])[-published:] if published else []
    groups = []
    for post in posts:
        contract = post.get("publication_contract") or {}
        if contract.get("approved") is not True or contract.get("issues"):
            issues.append("published_contract_invalid:" + str(post.get("title") or "")[:120])
        if not post.get("with_image") or not post.get("image_url") or not post.get("image_hash"):
            issues.append("published_media_invalid:" + str(post.get("title") or "")[:120])
        group = ((post.get("news_director") or {}).get("group"))
        if group:
            groups.append(str(group))
    if len(groups) == 2 and len(set(groups)) != 2:
        issues.append("published_group_diversity_failed:" + ",".join(groups))

    if monitor.get("status") != "healthy":
        issues.append("monitor_not_healthy")
    audit = monitor.get("post_audit") or {}
    if int(audit.get("unresolved") or 0):
        issues.append("post_audit_unresolved:" + str(audit.get("unresolved")))
    if audit.get("failed_actions"):
        issues.append("post_audit_failed_actions:" + str(len(audit.get("failed_actions") or [])))

    pending = [item for item in (state.get("pending_media_delivery") or []) if isinstance(item, dict)]
    for item in pending:
        candidate = {
            "title": item.get("title"),
            "source_text": item.get("source_text"),
            "category_key": item.get("category_key"),
            "url": item.get("url"),
            "source": item.get("source"),
        }
        quality = editorial_hardening.content_quality_issues(candidate, item.get("row") or {})
        if quality:
            issues.append(
                "unsafe_pending:" + str(item.get("title") or "")[:100] + ":" + ",".join(quality)
            )

    return list(dict.fromkeys(issues))


def monitor_issues() -> List[str]:
    status = _load(STATUS_PATH)
    issues: List[str] = []
    if status.get("status") != "healthy":
        issues.append("monitor_not_healthy")
    if status.get("issues"):
        issues.extend("monitor_issue:" + str(item.get("type") or item) for item in status.get("issues") or [])
    audit = status.get("post_audit") or {}
    if int(audit.get("unresolved") or 0):
        issues.append("post_audit_unresolved")
    if audit.get("failed_actions"):
        issues.append("post_audit_failed_actions")
    return list(dict.fromkeys(issues))


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "production").strip().lower()
    issues = production_issues() if mode == "production" else monitor_issues()
    print(json.dumps({"mode": mode, "status": "healthy" if not issues else "error", "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
