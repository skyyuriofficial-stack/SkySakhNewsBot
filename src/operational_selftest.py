from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import editorial_gate_runner
import hardened_digest
import health_gate
import resilient_production


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

    # A generic source/search teaser is not article evidence. The delivery
    # queue must fail closed rather than fabricate a body from its headline.
    teaser_item = {
        "source_text": (
            "Читайте последние актуальные новости главных событий Сахалина на тему "
            "\"Финансовая повестка\" в ленте новостей на сайте Sakh.online"
        )
    }
    assert resilient_production._source_evidence_insufficient(teaser_item), teaser_item
    assert not resilient_production._source_evidence_insufficient({
        "source_text": (
            "Депутаты рассмотрели поправки к областному бюджету. "
            "В документе приведены конкретные параметры доходов и расходов на плановый период."
        )
    })

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

    old_digest_mode = os.environ.get("DIGEST_MODE")
    old_digest_schedule = os.environ.get("DIGEST_SCHEDULE")
    try:
        os.environ["DIGEST_MODE"] = ""
        schedule_cases = {
            "7,37 0,1,21,22,23 * * *": "morning",
            "7 2,3,4,5,6,7 * * *": "morning",
            "7,37 8,9,10,11 * * *": "evening",
        }
        for schedule, expected in schedule_cases.items():
            os.environ["DIGEST_SCHEDULE"] = schedule
            actual = hardened_digest.resolved_mode()
            assert actual == expected, (schedule, expected, actual)
    finally:
        for key, value in (("DIGEST_MODE", old_digest_mode), ("DIGEST_SCHEDULE", old_digest_schedule)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("operational selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
