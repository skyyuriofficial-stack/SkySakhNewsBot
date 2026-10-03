from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone

import editorial_gate_runner
import editorial_monitor
import editorial_policy
import hardened_digest
import health_gate
import news_director
import resilient_production
import schedule_guard


def main() -> int:
    now = datetime.now(timezone.utc)

    post_monitor_workflow = Path(".github/workflows/post_publication_monitor.yml").read_text(
        encoding="utf-8"
    )
    assert "publication_auditor.audit_recent_posts(" in post_monitor_workflow
    assert "publication_auditor.audit_posts(" not in post_monitor_workflow
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

    blocked_health_state = {
        **state,
        "last_production_attempt": {
            "status": "blocked",
            "reason": "generation_provider_unavailable",
        },
    }
    blocked_health_report = health_gate.production_report(
        blocked_health_state, healthy_monitor, healthy_tg
    )
    assert blocked_health_report["execution_status"] == "healthy", blocked_health_report
    assert blocked_health_report["service_status"] == "degraded", blocked_health_report
    assert (
        "production_attempt_blocked:generation_provider_unavailable"
        in blocked_health_report["warnings"]
    ), blocked_health_report

    bad_tg = {"status": "error", "error_kind": "token_unauthorized"}
    report = health_gate.production_report(state, healthy_monitor, bad_tg)
    assert report["execution_status"] == "error", report

    # Core-classifier regression: Russian pet/animal-identification verbs must
    # not be promoted to major IT merely because they start with noun stem
    # "чип". Semiconductor noun forms must continue to classify as IT.
    pet_chipping = {
        "title": "В Сахалинской области чипировали и внесли в единую базу уже 36,8 тысячи кошек и собак",
        "source_text": (
            "Владельцам напоминают о возможности бесплатно зарегистрировать питомца. "
            "В Сахалинской области продолжается работа по учету домашних питомцев."
        ),
        "source": "ASTV",
        "url": "https://astv.ru/news/society/pet-chipping-regression",
        "category_key": "sakh",
    }
    pet_class = editorial_policy.classify(pet_chipping)
    assert pet_class.event_type != "major_it", pet_class
    pet_review = news_director.review_candidate(pet_chipping)
    assert pet_review["approved"] is False, pet_review
    assert pet_review["corrected_category"] == "sakh", pet_review

    semiconductor = {
        "title": "Производитель представил новые чипы для процессоров",
        "source_text": "Компания начала выпуск новых полупроводниковых чипов для серверных процессоров.",
        "source": "Reuters",
        "url": "https://www.reuters.com/technology/chip-regression",
        "category_key": "it",
    }
    semiconductor_class = editorial_policy.classify(semiconductor)
    assert semiconductor_class.event_type == "major_it", semiconductor_class

    # Corporate PR must not become "economy news" merely because ru_eco is
    # underrepresented in the rolling mix.
    sber_pr = {
        "title": "Сбер объединит технологии российских стартапов для развития сервисов в сфере здоровья",
        "source_text": (
            "Проекты представили в рамках Московского стартап-саммита. "
            "Об этом сообщает пресс-служба Сбера."
        ),
        "source": "SakhalinMedia.ru",
        "url": "https://sakhalinmedia.ru/news/corporate-pr-regression/",
        "category_key": "ru_eco",
    }
    sber_pr_class = editorial_policy.classify(sber_pr)
    assert sber_pr_class.hard_reject_reason == "corporate_product_or_brand_pr", sber_pr_class.to_dict()
    sber_pr_review = news_director.review_candidate(sber_pr)
    assert sber_pr_review["approved"] is False, sber_pr_review

    # Mix optimization is bounded: even a severe ru_eco deficit cannot make a
    # materially weaker story outrank a much more important one.
    synthetic_balance = {
        "sequence": (
            ["local"] * 12
            + ["ru_safety"] * 3
            + ["world"] * 3
            + ["ru_eco"] * 2
        ),
        "source_sequence": [],
    }
    strong_local_utility = news_director._utility(
        {"source": "ASTV", "category_key": "sakh_chp"},
        {"group": "local", "seriousness": 90, "event_type": "major_emergency"},
        synthetic_balance,
        [],
    )
    threshold_eco_utility = news_director._utility(
        {"source": "SakhalinMedia.ru", "category_key": "ru_eco"},
        {"group": "ru_eco", "seriousness": 80, "event_type": "macro_economy"},
        synthetic_balance,
        [],
    )
    assert strong_local_utility > threshold_eco_utility, (
        strong_local_utility,
        threshold_eco_utility,
    )

    # Generic "напал/нападение" markers must not turn a wild-animal incident
    # into violent crime. The local emergency category remains sakh_chp.
    bear_attack = {
        "title": "Медведя весом около 350 кг ликвидировали после нападения на человека в Рейдово",
        "source_text": (
            "В Рейдово крупный медведь напал на человека возле хозяйственной постройки. "
            "После нападения специалисты ликвидировали животное."
        ),
        "source": "Sakh.online",
        "url": "https://sakh.online/news/wild-animal-attack-regression",
        "category_key": "sakh_chp",
    }
    bear_class = editorial_policy.classify(bear_attack)
    assert bear_class.event_type == "major_emergency", bear_class.to_dict()
    assert bear_class.category_key == "sakh_chp", bear_class.to_dict()

    human_attack = {
        "title": "Мужчина напал на человека с ножом в Южно-Сахалинске",
        "source_text": "Подозреваемый напал на человека и нанес ножевое ранение.",
        "source": "ASTV",
        "url": "https://astv.ru/news/criminal/human-attack-regression",
        "category_key": "sakh_chp",
    }
    human_attack_class = editorial_policy.classify(human_attack)
    assert human_attack_class.event_type == "violent_crime", human_attack_class.to_dict()

    medvedev_attack = {
        "title": "Медведев напал на человека в Южно-Сахалинске",
        "source_text": "Мужчина по фамилии Медведев напал на человека во время конфликта.",
        "source": "ASTV",
        "url": "https://astv.ru/news/criminal/medvedev-surname-regression",
        "category_key": "sakh_chp",
    }
    medvedev_attack_class = editorial_policy.classify(medvedev_attack)
    assert medvedev_attack_class.event_type == "violent_crime", medvedev_attack_class.to_dict()

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

    # The 07:00 publisher slot is not overdue until its 45-minute grace period
    # expires. At 07:35 the latest required slot must therefore still be the
    # previous day's 22:00 slot; at 07:45 it must advance to 07:00.
    sakhalin_tz = timezone(timedelta(hours=11))
    before_due = datetime(2026, 9, 18, 7, 35, tzinfo=sakhalin_tz)
    at_due = datetime(2026, 9, 18, 7, 45, tzinfo=sakhalin_tz)
    assert editorial_monitor._latest_required_production_slot(before_due) == datetime(
        2026, 9, 17, 22, 0, tzinfo=sakhalin_tz
    )
    assert editorial_monitor._latest_required_production_slot(at_due) == datetime(
        2026, 9, 18, 7, 0, tzinfo=sakhalin_tz
    )

    # Cross-midnight publisher guard: before 07:00, the logical production
    # slot is the previous calendar day's 22:00 slot, not "before first slot".
    old_schedule_state_path = schedule_guard.STATE_PATH
    old_event_name = os.environ.get("GITHUB_EVENT_NAME")
    old_force_production = os.environ.get("FORCE_PRODUCTION")
    try:
        with TemporaryDirectory() as td:
            schedule_guard.STATE_PATH = Path(td) / "state.json"
            os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
            os.environ["FORCE_PRODUCTION"] = "0"
            cross_midnight = datetime(2026, 10, 3, 2, 15, tzinfo=sakhalin_tz)

            schedule_guard.STATE_PATH.write_text(
                json.dumps({"last_run": {}}), encoding="utf-8"
            )
            missing = schedule_guard.production_due(cross_midnight)
            assert missing["due"] is True, missing
            assert missing["slot"] == "2026-10-02T22:00+1100", missing
            assert missing["reason"] == "slot_missing_or_failed", missing

            schedule_guard.STATE_PATH.write_text(
                json.dumps({
                    "last_run": {
                        "finished_sakhalin": "2026-10-02T22:01:00+11:00"
                    }
                }),
                encoding="utf-8",
            )
            processed = schedule_guard.production_due(cross_midnight)
            assert processed["due"] is False, processed
            assert processed["slot"] == "2026-10-02T22:00+1100", processed
            assert processed["reason"] == "slot_already_processed", processed
    finally:
        schedule_guard.STATE_PATH = old_schedule_state_path
        if old_event_name is None:
            os.environ.pop("GITHUB_EVENT_NAME", None)
        else:
            os.environ["GITHUB_EVENT_NAME"] = old_event_name
        if old_force_production is None:
            os.environ.pop("FORCE_PRODUCTION", None)
        else:
            os.environ["FORCE_PRODUCTION"] = old_force_production

    # A complete generation-provider outage must not close a logical slot merely
    # because publisher.main() wrote a fresh finished_sakhalin timestamp.
    generation_outage_run = {
        "status": "ok",
        "published": 0,
        "finished_sakhalin": "2026-10-04T08:13:58+11:00",
        "stats": {
            "director_approved": 3,
            "ai_calls": 4,
            "ai_api_fail": 4,
            "ai_budget_exhausted": 1,
            "telegram_fail": 0,
            "publication_contract_blocked": 0,
        },
    }
    healthy_generation_transport = {"status": "healthy"}
    assert resilient_production._generation_provider_unavailable(
        generation_outage_run, healthy_generation_transport
    )

    contract_reject_run = {
        **generation_outage_run,
        "stats": {
            **generation_outage_run["stats"],
            "publication_contract_blocked": 1,
        },
    }
    assert not resilient_production._generation_provider_unavailable(
        contract_reject_run, healthy_generation_transport
    )
    partial_ai_failure = {
        **generation_outage_run,
        "stats": {
            **generation_outage_run["stats"],
            "ai_api_fail": 3,
        },
    }
    assert not resilient_production._generation_provider_unavailable(
        partial_ai_failure, healthy_generation_transport
    )
    published_fallback = {**generation_outage_run, "published": 1}
    assert not resilient_production._generation_provider_unavailable(
        published_fallback, healthy_generation_transport
    )
    assert not resilient_production._generation_provider_unavailable(
        generation_outage_run, {"status": "error"}
    )

    blocked_attempt = {
        "status": "blocked",
        "reason": "generation_provider_unavailable",
        "checked_at_utc": "2026-10-03T21:13:59+00:00",
    }
    blocked_latest_slot = datetime(2026, 10, 4, 7, 0, tzinfo=sakhalin_tz)
    blocked_issue = editorial_monitor._publisher_slot_issue(
        generation_outage_run,
        blocked_attempt,
        blocked_latest_slot,
        datetime(2026, 10, 4, 8, 20, tzinfo=sakhalin_tz),
    )
    assert blocked_issue is not None, blocked_issue
    assert blocked_issue["type"] == "publisher_blocked", blocked_issue
    assert blocked_issue["reason"] == "generation_provider_unavailable", blocked_issue
    processed_issue = editorial_monitor._publisher_slot_issue(
        generation_outage_run,
        {"status": "ok", "checked_at_utc": "2026-10-03T21:13:59+00:00"},
        blocked_latest_slot,
        datetime(2026, 10, 4, 8, 20, tzinfo=sakhalin_tz),
    )
    assert processed_issue is None, processed_issue

    old_schedule_state_path = schedule_guard.STATE_PATH
    old_event_name = os.environ.get("GITHUB_EVENT_NAME")
    old_force_production = os.environ.get("FORCE_PRODUCTION")
    try:
        with TemporaryDirectory() as td:
            schedule_guard.STATE_PATH = Path(td) / "state.json"
            os.environ["GITHUB_EVENT_NAME"] = "workflow_dispatch"
            os.environ["FORCE_PRODUCTION"] = "0"
            schedule_guard.STATE_PATH.write_text(
                json.dumps({
                    "last_run": generation_outage_run,
                    "last_production_attempt": blocked_attempt,
                }),
                encoding="utf-8",
            )
            cooling_down = schedule_guard.production_due(
                datetime(2026, 10, 4, 8, 20, tzinfo=sakhalin_tz)
            )
            assert cooling_down["due"] is False, cooling_down
            assert cooling_down["reason"] == "blocked_attempt_cooldown", cooling_down

            retry_due = schedule_guard.production_due(
                datetime(2026, 10, 4, 8, 30, tzinfo=sakhalin_tz)
            )
            assert retry_due["due"] is True, retry_due
            assert retry_due["reason"] == "blocked_attempt_retry_due", retry_due
            assert retry_due["blocked_reason"] == "generation_provider_unavailable", retry_due

            schedule_guard.STATE_PATH.write_text(
                json.dumps({
                    "last_run": generation_outage_run,
                    "last_production_attempt": {
                        "status": "ok",
                        "checked_at_utc": "2026-10-03T21:29:00+00:00",
                    },
                }),
                encoding="utf-8",
            )
            recovered = schedule_guard.production_due(
                datetime(2026, 10, 4, 8, 31, tzinfo=sakhalin_tz)
            )
            assert recovered["due"] is False, recovered
            assert recovered["reason"] == "slot_already_processed", recovered
    finally:
        schedule_guard.STATE_PATH = old_schedule_state_path
        if old_event_name is None:
            os.environ.pop("GITHUB_EVENT_NAME", None)
        else:
            os.environ["GITHUB_EVENT_NAME"] = old_event_name
        if old_force_production is None:
            os.environ.pop("FORCE_PRODUCTION", None)
        else:
            os.environ["FORCE_PRODUCTION"] = old_force_production

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

    digest_missing_status = {
        "mobilization_digest": {
            "missing": [
                {"type": "mobilization_digest_missing", "slot": "morning"},
                {"type": "mobilization_digest_missing", "slot": "evening"},
            ]
        }
    }
    assert editorial_monitor.digest_recovery_mode(
        digest_missing_status, {"status": "healthy"}
    ) == "evening"
    assert editorial_monitor.digest_recovery_mode(
        digest_missing_status, {"status": "error", "error_kind": "chat_access"}
    ) is None
    assert editorial_monitor.digest_recovery_mode(
        {"mobilization_digest": {"missing": []}}, {"status": "healthy"}
    ) is None

    old_digest_mode = os.environ.get("DIGEST_MODE")
    old_digest_schedule = os.environ.get("DIGEST_SCHEDULE")
    try:
        os.environ["DIGEST_MODE"] = ""
        sakhalin_tz = timezone(timedelta(hours=11))
        pre_evening = datetime(2026, 10, 1, 18, 0, tzinfo=sakhalin_tz)
        schedule_cases = {
            "7,37 0,1,21,22,23 * * *": "morning",
            "7 2,3,4,5,6,7 * * *": "morning",
            "7,37 8,9,10,11 * * *": "evening",
        }
        for schedule, expected in schedule_cases.items():
            os.environ["DIGEST_SCHEDULE"] = schedule
            actual = hardened_digest.resolved_mode(now_local=pre_evening)
            assert actual == expected, (schedule, expected, actual)

        os.environ["DIGEST_SCHEDULE"] = "7 2,3,4,5,6,7 * * *"
        delayed_watchdog = hardened_digest.resolved_mode(
            now_local=datetime(2026, 10, 1, 19, 30, tzinfo=sakhalin_tz)
        )
        assert delayed_watchdog == "evening", delayed_watchdog
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
