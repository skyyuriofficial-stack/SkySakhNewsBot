from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import editorial_hardening

editorial_hardening.install()

import editorial_monitor
import telegram_health

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
STATUS_PATH = ROOT / "monitor_status.json"

MIX_ERROR_LIMIT = float(os.getenv("THEMATIC_MIX_ERROR_LIMIT", "8"))


def _save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    health = telegram_health.check_telegram()
    telegram_health.write_status(health)
    requested_mutation = os.getenv("POST_AUDIT_AUTOCORRECT", "1") == "1"
    mutate = bool(requested_mutation and health.get("status") == "healthy")

    report = editorial_monitor.run_monitor(mutate=mutate)
    report["telegram_health"] = health

    issues = list(report.get("issues") or [])
    if health.get("status") != "healthy":
        issues.append({
            "type": "telegram_delivery_unhealthy",
            "reason": health.get("error_kind"),
            "http_status": health.get("http_status"),
            "description": health.get("description"),
        })

    balance = report.get("balance") or {}
    mix_error = float(balance.get("distribution_error") or 0.0)
    if mix_error >= MIX_ERROR_LIMIT:
        issues.append({
            "type": "thematic_mix_drift",
            "distribution_error": mix_error,
            "limit": MIX_ERROR_LIMIT,
            "counts": balance.get("counts") or {},
            "targets": balance.get("targets") or {},
            "deficits": balance.get("deficits") or {},
        })

    # De-duplicate issue types that may already have been emitted by the base monitor.
    deduped = []
    seen = set()
    for issue in issues:
        key = json.dumps(issue, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)

    report["issues"] = deduped
    report["status"] = "healthy" if not deduped else "error"
    report["mutations_enabled"] = mutate
    report["checked_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    except Exception:
        state = {}
    state["continuous_editorial_monitor"] = report
    state["telegram_health"] = health
    _save(STATE_PATH, state)
    _save(STATUS_PATH, report)

    print(json.dumps({
        "status": report.get("status"),
        "issues": report.get("issues"),
        "telegram_health": health,
        "post_audit": {
            "checked": (report.get("post_audit") or {}).get("checked"),
            "passed": (report.get("post_audit") or {}).get("passed"),
            "unresolved": (report.get("post_audit") or {}).get("unresolved"),
            "failed_actions": len((report.get("post_audit") or {}).get("failed_actions") or []),
        },
        "balance": report.get("balance"),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "healthy" else 3


if __name__ == "__main__":
    raise SystemExit(main())
