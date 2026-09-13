from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"pattern not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def main() -> int:
    # 1. Remove the retired OpenRouter model from the bounded fallback plan.
    replace_once(
        "src/editorial_gate_runner.py",
        '''    plan = []
    for model in configured:
        if model not in plan:
            plan.append(model)
    # Prefer the explicit free model that has proven stable in our live
    # production runs; retain the OpenRouter free router as a second path.
    for model in ("z-ai/glm-5.2:free", "openrouter/free"):
        if model not in plan:
            plan.append(model)

    while len(plan) < max_attempts:
        plan.append("openrouter/free")
    return plan[:max_attempts]
''',
        '''    retired = {"z-ai/glm-5.2:free"}
    plan = []
    for model in configured:
        if model in retired:
            continue
        if model not in plan:
            plan.append(model)
    # Never silently switch to a paid model. The free router is the only
    # implicit fallback; retired free model ids are skipped completely.
    if "openrouter/free" not in plan:
        plan.append("openrouter/free")

    while len(plan) < max_attempts:
        plan.append("openrouter/free")
    return plan[:max_attempts]
''',
    )

    # 2. Retry blocked production cheaply after a credential repair.
    replace_once(
        "src/schedule_guard.py",
        "PRODUCTION_HOURS = (7, 10, 13, 16, 19, 22)\n",
        "PRODUCTION_HOURS = (7, 10, 13, 16, 19, 22)\nBLOCKED_RETRY_COOLDOWN_MINUTES = 15\n",
    )
    path = "src/schedule_guard.py"
    write(path, read(path).replace("55 * 60", "BLOCKED_RETRY_COOLDOWN_MINUTES * 60"))

    # 3. Monitor reports exact scheduled-slot health and is a read-only observer by default.
    replace_once(
        "src/editorial_monitor.py",
        "from datetime import datetime, timezone\n",
        "from datetime import datetime, timedelta, timezone\n",
    )
    replace_once(
        "src/editorial_monitor.py",
        'DIGEST_STATE_PATH = ROOT / "mobilization_digest_state.json"\n',
        'DIGEST_STATE_PATH = ROOT / "mobilization_digest_state.json"\nPRODUCTION_HOURS = (7, 10, 13, 16, 19, 22)\nPRODUCTION_SLOT_GRACE_MINUTES = 45\n',
    )
    replace_once(
        "src/editorial_monitor.py",
        '''def _active_recent_posts(state: Dict[str, Any]):
''',
        '''def _latest_required_production_slot(now_local: datetime) -> Optional[datetime]:
    candidates = []
    for day_offset in (0, -1):
        day = now_local.date() + timedelta(days=day_offset)
        for hour in PRODUCTION_HOURS:
            slot = datetime(day.year, day.month, day.day, hour, 0, tzinfo=now_local.tzinfo)
            if slot + timedelta(minutes=PRODUCTION_SLOT_GRACE_MINUTES) <= now_local:
                candidates.append(slot)
    return max(candidates) if candidates else None


def _active_recent_posts(state: Dict[str, Any]):
''',
    )
    replace_once(
        "src/editorial_monitor.py",
        "def run_monitor(*, mutate: bool = True) -> Dict[str, Any]:\n",
        "def run_monitor(*, mutate: bool = True, persist_state: bool = True) -> Dict[str, Any]:\n",
    )
    replace_once(
        "src/editorial_monitor.py",
        '''    if last_run_age is not None and last_run_age > freshness_limit:
        issues.append({
            "type": "publisher_stale",
            "age_hours": last_run_age,
            "limit_hours": freshness_limit,
        })

    unresolved = int(audit.get("unresolved") or 0)
''',
        '''    if last_run_age is not None and last_run_age > freshness_limit:
        issues.append({
            "type": "publisher_stale",
            "age_hours": last_run_age,
            "limit_hours": freshness_limit,
        })

    latest_slot = _latest_required_production_slot(now_local)
    attempt = state.get("last_production_attempt") or {}
    finished = _parse_dt(run.get("finished_sakhalin"))
    attempted = _parse_dt(attempt.get("checked_at_utc"))
    if latest_slot is not None:
        run_covers_slot = bool(finished and finished.astimezone(now_local.tzinfo) >= latest_slot)
        blocked_covers_slot = bool(
            attempt.get("status") == "blocked"
            and attempted
            and attempted.astimezone(now_local.tzinfo) >= latest_slot
        )
        if not run_covers_slot:
            if blocked_covers_slot:
                issues.append({
                    "type": "publisher_blocked",
                    "slot_sakhalin": latest_slot.isoformat(timespec="minutes"),
                    "reason": attempt.get("reason"),
                    "attempted_at_utc": attempt.get("checked_at_utc"),
                })
            else:
                issues.append({
                    "type": "publisher_slot_missed",
                    "slot_sakhalin": latest_slot.isoformat(timespec="minutes"),
                    "grace_minutes": PRODUCTION_SLOT_GRACE_MINUTES,
                    "last_finished_sakhalin": run.get("finished_sakhalin"),
                })

    unresolved = int(audit.get("unresolved") or 0)
''',
    )
    replace_once(
        "src/editorial_monitor.py",
        '        "mobilization_digest": digest_health,\n',
        '        "last_production_attempt": state.get("last_production_attempt") or {},\n        "mobilization_digest": digest_health,\n',
    )
    replace_once(
        "src/editorial_monitor.py",
        '''    state["continuous_editorial_monitor"] = report
    _save_json(STATE_PATH, state)
    _save_json(STATUS_PATH, report)
    return report
''',
        '''    mutated_state = bool((audit.get("corrected") or []) or (audit.get("deleted") or []))
    if persist_state:
        state["continuous_editorial_monitor"] = report
        _save_json(STATE_PATH, state)
    elif mutated_state:
        _save_json(STATE_PATH, state)
    _save_json(STATUS_PATH, report)
    return report
''',
    )

    # 4. Hardened monitor only persists state when it actually changed a post.
    replace_once(
        "src/hardened_monitor.py",
        "    if actions or failures:\n        _save(STATE_PATH, state)\n",
        "    if actions:\n        _save(STATE_PATH, state)\n",
    )
    replace_once(
        "src/hardened_monitor.py",
        "    report = editorial_monitor.run_monitor(mutate=mutate)\n",
        "    report = editorial_monitor.run_monitor(mutate=mutate, persist_state=False)\n",
    )
    replace_once(
        "src/hardened_monitor.py",
        '''    state = _load_state()
    state["continuous_editorial_monitor"] = report
    state["telegram_health"] = health
    _save(STATE_PATH, state)
    _save(STATUS_PATH, report)
''',
        '''    _save(STATUS_PATH, report)
''',
    )

    # 5. Digest code-push dry-runs must not depend on a live Telegram token.
    replace_once(
        "src/hardened_digest.py",
        '''def main() -> int:
    mode = final.resolved_mode()
    health = telegram_health.check_telegram()
''',
        '''def main() -> int:
    mode = final.resolved_mode()
    if __import__("os").getenv("DIGEST_DRY_RUN", "0") == "1":
        return int(final.main() or 0)
    health = telegram_health.check_telegram()
''',
    )

    # 6. Separate process health from feed/service health.
    write("src/health_gate.py", HEALTH_GATE)
    write("src/operational_selftest.py", OPERATIONAL_SELFTEST)

    # 7. Workflow recovery cadence, one state-writer lock, and cached dependencies.
    path = ".github/workflows/auto_publish_v7.yml"
    text = read(path)
    text = text.replace('cron: "17,47 0-11,20-23 * * *"', 'cron: "7,17,27,37,47,57 0-12,20-23 * * *"')
    text = text.replace("group: skysakhnews-production-publisher", "group: skysakhnews-live-state")
    text = text.replace('          python-version: "3.11"\n\n      - name: Install dependencies', '          python-version: "3.11"\n          cache: "pip"\n          cache-dependency-path: requirements.txt\n\n      - name: Install dependencies', 1)
    text = text.replace("          python -m pip install --upgrade pip\n          pip install -r requirements.txt", "          pip install -r requirements.txt", 1)
    text = text.replace("src/schedule_guard.py src/health_gate.py src/hardening_selftest.py", "src/schedule_guard.py src/health_gate.py src/hardening_selftest.py src/operational_selftest.py")
    text = text.replace("          python src/hardening_selftest.py\n\n      - name: Publish", "          python src/hardening_selftest.py\n          python src/operational_selftest.py\n\n      - name: Publish")
    write(path, text)

    path = ".github/workflows/editorial_monitor.yml"
    text = read(path)
    text = text.replace('cron: "7,22,37,52 * * * *"', 'cron: "3,13,23,33,43,53 * * * *"')
    text = text.replace("group: skysakhnews-editorial-monitor", "group: skysakhnews-live-state")
    text = text.replace('          python-version: "3.11"\n\n      - name: Install dependencies', '          python-version: "3.11"\n          cache: "pip"\n          cache-dependency-path: requirements.txt\n\n      - name: Install dependencies', 1)
    text = text.replace("          python -m pip install --upgrade pip\n          pip install -r requirements.txt", "          pip install -r requirements.txt", 1)
    text = text.replace("src/hardened_monitor.py src/health_gate.py src/hardening_selftest.py", "src/hardened_monitor.py src/health_gate.py src/hardening_selftest.py src/operational_selftest.py")
    text = text.replace("      - name: Require current regression suite\n        env:", "      - name: Require current regression suite\n        if: github.event_name == 'workflow_dispatch'\n        env:")
    text = text.replace("          audit=data.get('post_audit') or {}\n          sys.exit(0 if (audit.get('corrected') or audit.get('deleted')) else 1)", "          audit=data.get('post_audit') or {}\n          actions=data.get('hardening_actions') or []\n          sys.exit(0 if (audit.get('corrected') or audit.get('deleted') or actions) else 1)")
    write(path, text)

    path = ".github/workflows/mobilization_digest.yml"
    text = read(path)
    text = text.replace('          python-version: "3.11"\n\n      - name: Install dependencies', '          python-version: "3.11"\n          cache: "pip"\n          cache-dependency-path: requirements.txt\n\n      - name: Install dependencies', 1)
    text = text.replace("          python -m pip install --upgrade pip\n          pip install -r requirements.txt", "          pip install -r requirements.txt", 1)
    write(path, text)

    path = ".github/workflows/production_ci.yml"
    text = read(path)
    text = text.replace('      - "src/hardening_selftest.py"\n', '      - "src/hardening_selftest.py"\n      - "src/operational_selftest.py"\n')
    text = text.replace('          python-version: "3.11"\n\n      - name: Install dependencies', '          python-version: "3.11"\n          cache: "pip"\n          cache-dependency-path: requirements.txt\n\n      - name: Install dependencies', 1)
    text = text.replace("          python -m pip install --upgrade pip\n          pip install -r requirements.txt", "          pip install -r requirements.txt", 1)
    text = text.replace("src/schedule_guard.py src/health_gate.py src/hardening_selftest.py", "src/schedule_guard.py src/health_gate.py src/hardening_selftest.py src/operational_selftest.py")
    text = text.replace("          python src/hardening_selftest.py\n", "          python src/hardening_selftest.py\n          python src/operational_selftest.py\n")
    write(path, text)

    print("root-cause hardening patch applied")
    return 0


HEALTH_GATE = r'''from __future__ import annotations

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
'''


OPERATIONAL_SELFTEST = r'''from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import editorial_gate_runner
import health_gate


def main() -> int:
    now = datetime.now(timezone.utc)
    status = {
        "publisher_version": "stable-v12.1",
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "status": "error",
        "issues": [{"type": "telegram_delivery_unhealthy"}],
        "post_audit": {"unresolved": 3, "failed_actions": []},
    }
    report = health_gate.monitor_report(status, now=now)
    assert report["execution_status"] == "healthy", report
    assert report["feed_status"] == "error", report

    stale = dict(status)
    stale["checked_at_utc"] = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    report = health_gate.monitor_report(stale, now=now)
    assert report["execution_status"] == "error", report

    state = {
        "last_run": {
            "version": "stable-v12.1", "status": "ok", "finished_sakhalin": now.isoformat(),
            "published": 0, "stats": {"publication_contract_blocked": 1},
            "media_policy": {"pending_ready": 0, "deferred_this_run": 0},
        },
        "pending_media_delivery": [],
    }
    healthy_tg = {"status": "healthy"}
    healthy_monitor = {"status": "healthy", "post_audit": {"unresolved": 0, "failed_actions": []}}
    report = health_gate.production_report(state, healthy_monitor, healthy_tg)
    assert report["execution_status"] == "healthy", report
    assert "publication_contract_blocked:1" in report["warnings"], report

    bad_tg = {"status": "error", "error_kind": "token_unauthorized"}
    report = health_gate.production_report(state, healthy_monitor, bad_tg)
    assert report["execution_status"] == "error", report

    old_model = os.environ.get("OPENROUTER_MODEL")
    old_fallback = os.environ.get("OPENROUTER_FALLBACK_MODELS")
    old_attempts = os.environ.get("OPENROUTER_MAX_ATTEMPTS")
    try:
        os.environ["OPENROUTER_MODEL"] = "z-ai/glm-5.2:free"
        os.environ["OPENROUTER_FALLBACK_MODELS"] = ""
        os.environ["OPENROUTER_MAX_ATTEMPTS"] = "3"
        plan = editorial_gate_runner._openrouter_model_plan()
        assert "z-ai/glm-5.2:free" not in plan, plan
        assert plan == ["openrouter/free", "openrouter/free", "openrouter/free"], plan
    finally:
        for key, value in (("OPENROUTER_MODEL", old_model), ("OPENROUTER_FALLBACK_MODELS", old_fallback), ("OPENROUTER_MAX_ATTEMPTS", old_attempts)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("operational selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


if __name__ == "__main__":
    raise SystemExit(main())
