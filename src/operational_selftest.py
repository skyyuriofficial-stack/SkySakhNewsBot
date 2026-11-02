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
import mobilization_digest as mobdigest
import mobilization_digest_final as mobfinal
import mobilization_digest_runner as mobrunner
import mobilization_sources as mobsources
import health_gate
import news_director
import resilient_production
import schedule_guard


def mobilization_depth_regression() -> None:
    legal = mobsources.verified_legal_reference_rows()
    today = datetime.now(timezone.utc)
    observed = {
        "group": "civil_society",
        "trust": 84,
        "source": "Идите лесом — сообщение проекта",
        "title": "Запасникам сразу из пяти регионов России пришли повестки для уточнения данных",
        "summary": (
            "29 октября сообщили о повестках запасникам из Ставропольского "
            "края, Башкортостана, Марий Эл, Оренбургской и Саратовской областей. "
            "Назначено уточнение военно-учётных данных, а не мобилизация."
        ),
        "url": "https://t.me/iditelesom_help/999",
        "published_utc": today.isoformat(),
    }
    fake = {
        **observed,
        "title": "В Краснодаре рассылают фейковые повестки по мобилизации",
        "summary": (
            "По сообщению проекта, в Краснодаре появились поддельные "
            "повестки, отправленные обычной электронной почтой."
        ),
        "url": "https://t.me/iditelesom_help/1000",
    }
    evidence = [
        {**item, "id": index}
        for index, item in enumerate(legal + [observed, fake], 1)
    ]
    assert all(mobsources.is_relevant(row) for row in evidence)
    draft = mobfinal.safe_fallback_draft(evidence)
    assert not mobrunner.validate_draft(draft, evidence), (
        draft, mobrunner.validate_draft(draft, evidence)
    )
    assert "19.5.5" in draft["legal"] and "31-ФЗ" in draft["legal"]
    assert "757" in draft["legal"]
    assert "27.10.2026" in draft["legal"]
    assert "Идите лесом" in draft["practice"]
    assert any(
        "Ставропольский край" in item["text"]
        for item in draft["items"]
    ), draft
    assert any(
        "фейков" in item["text"].lower()
        for item in draft["items"]
    ), draft
    assert "НИЗКИЙ" not in draft["assessment"]["near_term"]
    wire = mobdigest.format_message(draft, evidence, "morning")
    assert "<b>Юридические изменения</b>" in wire
    assert "19.5.5" in wire and "300 тыс." in wire
    assert "https://t.me/iditelesom_help/999" in wire, wire
    assert "https://sozd.duma.gov.ru/bill/1322096-8" in wire
    assert "https://base.garant.ru/411685332/" in wire
    assert len(wire) <= 4000 and wire.endswith("</a>"), (len(wire), wire[-100:])

    shallow = {
        **draft,
        "items": [
            {"status": "ПОДТВЕРЖДЕНО", "text": "Законопроект обсуждается.",
             "source_ids": [1]},
            {"status": "ПОДТВЕРЖДЕНО", "text": "Идёт рассмотрение законопроекта.",
             "source_ids": [2]},
        ],
        "legal": "Есть законопроект.",
        "practice": "Повесток не обнаружено.",
        "assessment": {**draft["assessment"], "near_term": "НИЗКИЙ"},
        "source_ids": [1, 2],
    }
    shallow_issues = mobrunner.validate_draft(shallow, evidence)
    assert "legal_analysis_missing_statute_or_decree" in shallow_issues
    assert "recent_civil_society_evidence_omitted" in shallow_issues
    assert "duplicate_bill_as_multiple_news" in shallow_issues
    assert "unsupported_low_mobilization_risk_from_absence_of_evidence" in shallow_issues

    original = mobsources.telegram_public_sources.fetch_public_channel
    try:
        mobsources.telegram_public_sources.fetch_public_channel = lambda src, **kw: [
            {
                "title": observed["title"], "text": observed["summary"],
                "url": observed["url"], "published_at": today,
            },
            {
                "title": "Объявлен список футбольных матчей",
                "text": "Спортивные расписания и объявления о футболе",
                "url": "https://t.me/iditelesom_help/1001", "published_at": today,
            },
        ]
        rows = mobsources.fetch_iditelesom_recent()
        assert len(rows) == 1, rows
        assert rows[0]["group"] == "civil_society", rows
        assert rows[0]["source"] == "Идите лесом — сообщение проекта", rows
    finally:
        mobsources.telegram_public_sources.fetch_public_channel = original


def mobilization_live_integrity_regression() -> None:
    # The historical source collector returned a shallow GARANT landing
    # snippet before the verified bill text and URL-deduplication suppressed
    # the actual legal description. Preserve the full proposed 19.5.5 text.
    original = {
        "isw": mobsources.fetch_isw_daily,
        "kremlin": mobsources.fetch_kremlin_index,
        "bills": mobsources.fetch_bill_pages,
        "civil": mobsources.fetch_iditelesom_recent,
        "feeds": mobsources.fetch_direct_feeds,
    }
    verified = mobsources.verified_legal_reference_rows()
    duplicate = {
        "group": "law",
        "trust": 96,
        "source": "ГАРАНТ — старый краткий фрагмент страницы",
        "title": "Проект федерального закона №1322096-8",
        "summary": "Законопроект №1322096-8 о КоАП внесён в Думу.",
        "url": "https://base.garant.ru/411685332/",
        "published_utc": None,
    }
    try:
        mobsources.fetch_isw_daily = lambda: []
        mobsources.fetch_kremlin_index = lambda: []
        mobsources.fetch_bill_pages = lambda: [duplicate]
        mobsources.fetch_iditelesom_recent = lambda: []
        mobsources.fetch_direct_feeds = lambda: []
        merged = mobsources.collect_fallback()
    finally:
        mobsources.fetch_isw_daily = original["isw"]
        mobsources.fetch_kremlin_index = original["kremlin"]
        mobsources.fetch_bill_pages = original["bills"]
        mobsources.fetch_iditelesom_recent = original["civil"]
        mobsources.fetch_direct_feeds = original["feeds"]

    matched = [
        row for row in merged
        if row.get("url") == "https://base.garant.ru/411685332/"
    ]
    assert len(matched) == 1, matched
    assert matched[0].get("legal_role") == "bill_text", matched
    assert "300 тыс" in matched[0].get("summary", ""), matched
    assert "19.5.5" in matched[0].get("summary", ""), matched

    # Live preview once leaked "fake summons" tokens into an unrelated
    # source summary. A fake-summons alert must cite the real fake-summons
    # headline, not a neighbouring post about a help-line.
    now = datetime.now(timezone.utc).isoformat()
    calls = {
        "group": "civil_society", "trust": 84,
        "source": "Идите лесом — сообщение проекта",
        "title": "Запасникам пришли повестки для уточнения воинского учёта",
        "summary": "Повестки запасникам для уточнения данных в регионах.",
        "url": "https://t.me/iditelesom_help/8213",
        "published_utc": now,
    }
    unrelated = {
        **calls, "title": "Наша линия помощи верифицирована",
        "summary": "Линия помощи действует. В соседнем посте сообщали о фейковых повестках.",
        "url": "https://t.me/iditelesom_help/8219",
    }
    fake = {
        **calls,
        "title": "В Краснодаре рассылают фейковые повестки по мобилизации",
        "summary": "По данным проекта в Краснодаре появились поддельные повестки.",
        "url": "https://t.me/iditelesom_help/8220",
    }
    evidence = [
        {**row, "id": i}
        for i, row in enumerate(verified + [calls, unrelated, fake], 1)
    ]
    draft = mobfinal.safe_fallback_draft(evidence)
    id_unrelated = next(row["id"] for row in evidence
                        if row.get("url") == unrelated["url"])
    id_fake = next(row["id"] for row in evidence
                   if row.get("url") == fake["url"])
    fake_items = [
        item for item in draft.get("items", [])
        if item.get("status") == "ПРЕДУПРЕЖДЕНИЕ ИСТОЧНИКА"
    ]
    assert len(fake_items) == 1, (fake_items, draft)
    assert fake_items[0]["source_ids"] == [id_fake], fake_items
    assert id_unrelated not in fake_items[0]["source_ids"], fake_items
    assert "Краснодаре" in fake_items[0]["text"], fake_items
    assert not mobrunner.validate_draft(draft, evidence), draft

    # Already published morning digest (message 543) must not rerun on a
    # code push, even though dry-run is always allowed for safe verification.
    saved_loader = mobdigest.load_state
    saved_env = {
        name: os.environ.get(name)
        for name in ("GITHUB_EVENT_NAME", "DIGEST_DRY_RUN")
    }
    day = datetime.now(mobdigest.TZ).date().isoformat()
    status = {
        "slots": {
            day: {
                "morning": {"status": "ok", "telegram_message_id": 543}
            }
        }
    }
    try:
        os.environ["GITHUB_EVENT_NAME"] = "push"
        os.environ["DIGEST_DRY_RUN"] = "0"
        mobdigest.load_state = lambda: status
        assert mobfinal._should_execute("morning") is False
        assert mobfinal._should_execute("evening") is True
        status = {"slots": {}}
        assert mobfinal._should_execute("morning") is True
        os.environ["DIGEST_DRY_RUN"] = "1"
        assert mobfinal._should_execute("morning") is True
    finally:
        mobdigest.load_state = saved_loader
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    mobilization_live_integrity_regression()
    mobilization_depth_regression()
    now = datetime.now(timezone.utc)

    post_monitor_workflow = Path(".github/workflows/post_publication_monitor.yml").read_text(
        encoding="utf-8"
    )
    assert "publication_auditor.audit_recent_posts(" in post_monitor_workflow
    assert "publication_auditor.audit_posts(" not in post_monitor_workflow
    editorial_monitor_workflow = Path(".github/workflows/editorial_monitor.yml").read_text(
        encoding="utf-8"
    )
    assert "legacy_generation_blocked" in editorial_monitor_workflow
    assert "--connect-timeout 10 --max-time 30" in editorial_monitor_workflow
    assert "auto_publish_v7.yml/runs?status=${run_status}" in editorial_monitor_workflow
    assert "Publisher recovery already active/queued; no competing dispatch" in editorial_monitor_workflow
    assert "guard=schedule_guard.production_due()" in editorial_monitor_workflow
    assert "Recovery intent held by schedule guard:" in editorial_monitor_workflow
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

            # Backward compatibility: a pre-fix outage recorded an "ok"
            # attempt before publisher.main() finished. Durable last_run stats
            # must still reopen that logical slot after the cooldown.
            schedule_guard.STATE_PATH.write_text(
                json.dumps({
                    "last_run": generation_outage_run,
                    "last_production_attempt": {
                        "status": "ok",
                        "checked_at_utc": "2026-10-03T21:08:39+00:00",
                    },
                }),
                encoding="utf-8",
            )
            legacy_retry = schedule_guard.production_due(
                datetime(2026, 10, 4, 8, 31, tzinfo=sakhalin_tz)
            )
            assert legacy_retry["due"] is True, legacy_retry
            assert legacy_retry["reason"] == "blocked_attempt_retry_due", legacy_retry
            assert (
                legacy_retry["blocked_reason"] == "generation_provider_unavailable"
            ), legacy_retry

            # A genuine successful/fallback publication must still close the slot.
            schedule_guard.STATE_PATH.write_text(
                json.dumps({
                    "last_run": published_fallback,
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
