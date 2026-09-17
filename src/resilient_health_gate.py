from __future__ import annotations

import json

import health_gate

DELIVERY_ONLY_PREFIXES = (
    "telegram_unhealthy:",
    "telegram_fail:",
    "pending_ready_but_nothing_published",
    "delivery_deferred_this_run:",
)


def _is_delivery_only(issue: str) -> bool:
    return any(str(issue).startswith(prefix) for prefix in DELIVERY_ONLY_PREFIXES)


def main() -> int:
    report = health_gate.production_report()
    original_critical = [str(value) for value in (report.get("critical") or [])]
    delivery_issues = [value for value in original_critical if _is_delivery_only(value)]
    blocking = [value for value in original_critical if not _is_delivery_only(value)]

    state = health_gate._load(health_gate.STATE_PATH)
    run = state.get("last_run") if isinstance(state.get("last_run"), dict) else {}
    editorial_ok = (
        run.get("version") == "stable-v12.1"
        and run.get("status") == "ok"
        and bool(run.get("finished_sakhalin"))
    )

    if editorial_ok and not blocking:
        report["execution_status"] = "healthy"
        report["service_status"] = "degraded" if delivery_issues or report.get("warnings") else "healthy"
        report["critical"] = []
        report["warnings"] = list(dict.fromkeys(
            [str(value) for value in (report.get("warnings") or [])]
            + ["delivery_plane:" + value for value in delivery_issues]
        ))
        report["editorial_plane"] = "healthy"
        report["delivery_plane"] = "blocked" if delivery_issues else "healthy"
    else:
        report["editorial_plane"] = "error"
        report["delivery_plane"] = "blocked" if delivery_issues else "unknown"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("execution_status") == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
