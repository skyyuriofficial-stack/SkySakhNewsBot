"""Offline regressions for substantive mobilization digest safety.

Run with PYTHONPATH=src python src/mobilization_quality_selftest.py.
No Telegram credentials or network access required.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import mobilization_digest as digest
import mobilization_digest_final as final
import mobilization_digest_runner as runner
import mobilization_sources as sources


def legal_rows():
    return copy.deepcopy(sources.verified_legal_reference_rows())


def civil_row():
    return {
        "group": "civil_society",
        "trust": 84,
        "source": "Идите лесом — сообщение проекта",
        "title": "«Идите лесом» сообщило о повестках запасникам для уточнения данных",
        "summary": (
            "Проект «Идите лесом» сообщает о повестках запасникам для "
            "уточнения военно-учётных данных. Это сообщения проекта; "
            "они не доказывают начало массовой мобилизации."
        ),
        "url": "https://t.me/iditelesom_help/123456",
        "published_utc": datetime.now(timezone.utc).isoformat(),
    }


def assigned(rows):
    return [dict(row, id=i) for i, row in enumerate(rows, start=1)]


def check_old_three_source_regression():
    old_three = assigned([
        {
            "group": "law", "trust": 96,
            "source": "ГАРАНТ",
            "title": "Досье законопроекта 1322096-8",
            "summary": "Проект федерального закона 1322096-8",
            "url": f"https://base.garant.ru/{x}/",
        }
        for x in ("414784137", "411685332", "411685333")
    ])
    try:
        final._require_substantive_evidence(old_three)
    except RuntimeError as exc:
        assert "digest_evidence_incomplete" in str(exc), exc
    else:
        raise AssertionError("Three repetitive GARANT headlines cannot pass")


def check_robust_collection_keeps_distinct_legal_and_civil():
    original = runner._original_collect
    fallback = sources.collect_fallback
    try:
        # 50 fresher/high-trust headlines must not evict the four legal acts
        # or the dated civil-society observation from the 42-evidence budget.
        runner._original_collect = lambda: [
            {
                "group": "official", "trust": 100,
                "source": "Synthetic test",
                "title": f"Военкомат опубликовал повестки запасникам — fixture {i}",
                "summary": "В тестовом сценарии предусмотрено уточнение учётных данных.",
                "url": f"https://example.org/fixture/{i}",
                "published_utc": datetime.now(timezone.utc).isoformat(),
            } for i in range(50)
        ]
        sources.collect_fallback = lambda: legal_rows() + [civil_row()]
        rows = final.robust_collect()
    finally:
        runner._original_collect = original
        sources.collect_fallback = fallback

    assert len(rows) <= digest.MAX_EVIDENCE, len(rows)
    final._require_substantive_evidence(rows)
    assert len([r for r in rows if r.get("legal_role")]) == 4
    assert any(r.get("group") == "civil_society" for r in rows), rows
    assert len({x["id"] for x in rows}) == len(rows)
    return rows


def check_analytical_draft(rows):
    old_status = copy.deepcopy(sources.IDITELESOM_STATUS)
    try:
        sources.IDITELESOM_STATUS.update(
            {"state": "reachable", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
             "sampled": 18, "relevant": 1}
        )
        draft = final.safe_fallback_draft(rows)
        problems = runner.validate_draft(draft, rows)
        problems += final._substantive_draft_issues(draft, rows)
        assert not problems, problems
        assert sum(bool(x.get("source_ids")) for x in draft["items"]) >= 2
        assert "Неисполнение решения" in draft["legal"]
        assert "это не вступившая" in draft["legal"].lower() or "не действующие" in draft["legal"].lower()
        assert "недостаточно данных" in draft["assessment"]["near_term"].lower()
        assert "Идите лесом" in draft["practice"]

        msg = digest.format_message(draft, rows, "morning")
        for required in (
            "19.5.5", "31-ФЗ", "757", "3–5", "30–50",
            "Идите лесом", "1322096-8",
        ):
            assert required in msg, (required, msg)
        assert "https://t.me/iditelesom_help/123456" in msg
        assert len(msg) <= 4000, len(msg)

        weak = copy.deepcopy(draft)
        weak["legal"] = "Досье, текст и пояснительная записка к законопроекту."
        weak["source_ids"] = [rows[0]["id"]]
        assert "legal_explanation_too_shallow" in (
            final._substantive_draft_issues(weak, rows)
        )
        assert "legal_sources_not_all_cited" in (
            final._substantive_draft_issues(weak, rows)
        )
    finally:
        sources.IDITELESOM_STATUS.clear()
        sources.IDITELESOM_STATUS.update(old_status)


def check_civil_source_failure_is_not_reported_empty():
    old_status = copy.deepcopy(sources.IDITELESOM_STATUS)
    try:
        rows = assigned(legal_rows())
        sources.IDITELESOM_STATUS.update(
            {"state": "unavailable", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
             "sampled": 0, "relevant": 0}
        )
        draft = final.safe_fallback_draft(rows)
        assert "недоступен" in draft["practice"], draft
        assert not final._substantive_draft_issues(draft, rows), draft
        msg = digest.format_message(draft, rows, "evening")
        assert "https://t.me/s/iditelesom_help" in msg, msg
        assert "Идите лесом" in msg
    finally:
        sources.IDITELESOM_STATUS.clear()
        sources.IDITELESOM_STATUS.update(old_status)


def check_first_party_source_attribution():
    original = sources.telegram_public_sources.fetch_public_channel
    previous = copy.deepcopy(sources.IDITELESOM_STATUS)
    now = datetime.now(timezone.utc)
    try:
        sources.telegram_public_sources.fetch_public_channel = lambda source, **kw: [
            {
                "title": "Уточнение воинского учёта — повестки запасникам",
                "text": "Проект «Идите лесом» сообщил о повестках запасникам для уточнения данных.",
                "url": "https://t.me/iditelesom_help/991",
                "published_at": now - timedelta(days=2),
            },
            {
                "title": "Нерелевантная заметка",
                "text": "Сведения о работе волонтёров без военной тематики.",
                "url": "https://t.me/iditelesom_help/992",
                "published_at": now - timedelta(days=1),
            },
        ]
        rows = sources.fetch_iditelesom_recent()
        assert len(rows) == 1, rows
        assert rows[0]["url"].endswith("/991"), rows
        assert sources.IDITELESOM_STATUS["state"] == "reachable"
        assert sources.IDITELESOM_STATUS["sampled"] == 2
        assert sources.IDITELESOM_STATUS["relevant"] == 1
    finally:
        sources.telegram_public_sources.fetch_public_channel = original
        sources.IDITELESOM_STATUS.clear()
        sources.IDITELESOM_STATUS.update(previous)


def main():
    check_old_three_source_regression()
    rows = check_robust_collection_keeps_distinct_legal_and_civil()
    check_analytical_draft(rows)
    check_civil_source_failure_is_not_reported_empty()
    check_first_party_source_attribution()
    print("mobilization quality selftest: ALL PASS")


if __name__ == "__main__":
    main()
