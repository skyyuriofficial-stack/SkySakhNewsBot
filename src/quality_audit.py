"""End-to-end dry production audit for SkySakhNews stable-v10.2.

The audit uses live sources and the real collector, category reconciler,
editorial gate, ordering and state logic. Telegram calls are captured rather
than sent. The report is intentionally machine-readable and fails closed.
"""

from __future__ import annotations

import copy
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

import category_reconciler as reconciler
import editorial_gate as gate
import editorial_gate_runner as runner

core = runner.core
prod = runner.prod

LOCAL_KEYS = {"sakh", "sakh_chp", "sakh_quake"}


def _candidate_row(candidate):
    return {
        "title_ru": prod._display_title(candidate),
        "body": [],
        "editorial_mode": "extractive_fallback",
    }


def _apply_suggestion(candidate, suggested):
    item = copy.deepcopy(candidate)
    if suggested in core.b.CAT:
        item["category_key"] = suggested
        item["category"], item["footer"] = core.b.CAT[suggested]
    return item


def _historical_cases():
    def c(cat, source, title, text, url):
        return {
            "category_key": cat,
            "category": cat,
            "source": source,
            "title": title,
            "source_text": text,
            "url": url,
        }

    return [
        ("iran_not_sakhalin", c("sakh", "Interfax", "В парламенте Ирана заявили, что давление на Тегеран не поможет США", "Иран и США обсуждают соглашение.", "https://www.interfax.ru/world/1110010"), "geo"),
        ("canada_tariffs_not_ru_economy", c("ru_eco", "Interfax", "Трамп рассматривает отсрочку пошлин в отношении Канады", "Президент США обсуждает канадские пошлины.", "https://www.interfax.ru/world/1110016"), "geo"),
        ("child_death_is_incident", c("ru_pol", "Interfax", "Ребенок погиб в Ростовской области, упав за борт катера", "Следователи устанавливают обстоятельства происшествия.", "https://www.interfax.ru/russia/1110068"), "ru_incident"),
        ("airport_drone_is_security", c("ru_pol", "Interfax", "Аэропорт ограничил прием самолетов из-за угрозы БПЛА", "Росавиация сообщила об ограничениях.", "https://www.interfax.ru/russia/1110011"), "ru_security"),
        ("sakhalin_rain_not_emergency", c("sakh_chp", "SakhalinMedia.ru", "Сильный дождь пройдет в центральных районах Сахалина", "Сахалинское УГМС прогнозирует осадки.", "https://sakhalinmedia.ru/news/2593484/"), "sakh"),
        ("habr_audio_offtopic", c("sakh", "Habr", "Сравнение типов магнитных лент на Kenwood", "Материал об аналоговом звуке и кассетах.", "https://habr.com/ru/articles/1/"), None),
        ("local_publisher_habarovsk_offtopic", c("sakh", "SakhalinMedia.ru", "Мэр Хабаровска рассказал об автобусной остановке", "Материал о Хабаровске без Сахалинской географии.", "https://sakhalinmedia.ru/news/2594805/"), None),
        ("japan_russia_not_local", c("sakh", "Interfax", "Японист РАН: Токио наказывает Россию за Украину, но держит в уме Китай", "В статье также упоминаются Курильские острова.", "https://www.interfax.ru/world/1110153"), "geo"),
        ("global_brent_not_ru_economy", c("ru_eco", "Interfax", "Нефть слабо дорожает, Brent торгуется у $91,7 за баррель", "Мировые цены на Brent и фьючерсы ICE растут.", "https://www.interfax.ru/business/1110251"), None),
        ("local_crime", c("sakh", "SakhalinMedia.ru", "Житель Долинска украл банковскую карту у приятеля", "Полиция Долинска возбудила уголовное дело по факту кражи.", "https://sakhalinmedia.ru/news/2593525/"), "sakh_chp"),
        ("local_infrastructure", c("sakh_chp", "SakhalinMedia.ru", "В Аниве завершили возведение опор моста через Лютогу", "Работы выполнены в Анивском районе Сахалинской области.", "https://sakhalinmedia.ru/news/2594807/"), "sakh"),
        ("local_quake", c("sakh", "Interfax", "Землетрясение магнитудой 5,1 зарегистрировано возле Южных Курил", "Эпицентр находился восточнее Итурупа.", "https://www.interfax.ru/russia/1"), "sakh_quake"),
    ]


def run_audit(report_path="final_quality_report.json"):
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": runner.VERSION,
        "mode": "live-sources / dry-Telegram / headline-first reconciliation / mandatory semantic gate",
        "candidate_count": 0,
        "reconciled_count": 0,
        "offtopic_count": 0,
        "candidate_violations": [],
        "candidate_audit": [],
        "historical_cases": [],
        "run": {},
        "captured_posts": [],
        "dry_last_posts": [],
        "checks": [],
        "run_error": None,
    }

    checks = report["checks"]

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:2400]})

    try:
        original_state = json.loads(Path("state.json").read_text(encoding="utf-8"))
        candidates = core.b.collect(copy.deepcopy(original_state))
        report["candidate_count"] = len(candidates)

        violations = []
        reconciled = 0
        offtopic = 0
        for candidate in candidates:
            suggested = reconciler.suggest_category(candidate)
            if suggested is None:
                offtopic += 1
                report["candidate_audit"].append({
                    "source": candidate.get("source"),
                    "url": candidate.get("url"),
                    "title": candidate.get("title"),
                    "original_category": candidate.get("category_key"),
                    "suggested_category": None,
                    "decision": "reject_offtopic_or_ambiguous",
                })
                continue

            item = _apply_suggestion(candidate, suggested)
            verdict = gate.deterministic_review(item, _candidate_row(item))
            if suggested != candidate.get("category_key"):
                reconciled += 1

            hard_ok = (
                int(verdict.get("title_matches_source") or 0) >= 90
                and int(verdict.get("category_matches_story") or 0) >= 90
                and verdict.get("facts_supported") is True
                and verdict.get("meaning_changed") is False
            )
            row = {
                "source": candidate.get("source"),
                "url": candidate.get("url"),
                "title": candidate.get("title"),
                "original_category": candidate.get("category_key"),
                "suggested_category": suggested,
                "title_matches_source": verdict.get("title_matches_source"),
                "category_matches_story": verdict.get("category_matches_story"),
                "issues": verdict.get("issues"),
                "decision": "safe_candidate" if hard_ok else "reject_semantic_mismatch",
            }
            report["candidate_audit"].append(row)
            if not hard_ok:
                violations.append(row)

        report["reconciled_count"] = reconciled
        report["offtopic_count"] = offtopic
        report["candidate_violations"] = violations

        for name, candidate, expected in _historical_cases():
            actual = reconciler.suggest_category(candidate)
            ok = actual == expected
            report["historical_cases"].append({
                "name": name,
                "expected": expected,
                "actual": actual,
                "ok": ok,
            })

        # Execute the real publishing pipeline with Telegram and state writes captured.
        working_state = copy.deepcopy(original_state)
        captured_state = {}
        captured_posts = []

        def dry_photo(candidate, caption):
            captured_posts.append({
                "method": "dry-sendPhoto",
                "url": candidate.get("url"),
                "source": candidate.get("source"),
                "title": candidate.get("title"),
                "category_key": candidate.get("category_key"),
                "caption": caption,
            })
            return {"ok": True, "result": {"message_id": 1}}

        def dry_text(row, candidate):
            captured_posts.append({
                "method": "dry-sendMessage",
                "url": candidate.get("url"),
                "source": candidate.get("source"),
                "title": candidate.get("title"),
                "category_key": candidate.get("category_key"),
                "row": row,
            })
            return {"ok": True, "result": {"message_id": 1}}

        core.b.load_state = lambda: copy.deepcopy(working_state)

        def fake_save(state):
            captured_state.clear()
            captured_state.update(copy.deepcopy(state))

        core.b.save_state = fake_save
        core.b.send_photo = dry_photo
        core.send_text = dry_text
        core.time.sleep = lambda _seconds: None

        runner.main()

        run = captured_state.get("last_run") or {}
        published = int(run.get("published") or 0)
        dry_last_posts = (captured_state.get("last_posts") or [])[-published:] if published else []
        report["run"] = run
        report["captured_posts"] = captured_posts
        report["dry_last_posts"] = dry_last_posts

        check("version_stable_v10_2", runner.VERSION == "stable-v10.2", runner.VERSION)
        check("candidate_pool_nonempty", len(candidates) > 0, len(candidates))
        check("historical_regressions", all(x["ok"] for x in report["historical_cases"]), [x for x in report["historical_cases"] if not x["ok"]])
        check("safe_candidates_have_no_semantic_violations", not violations, violations[:12])
        check("runtime_status_ok", run.get("status") == "ok", run)
        check("runtime_version", run.get("version") == "stable-v10.2", run.get("version"))
        check("local_stream_operational", (run.get("local_stream") or {}).get("status") in {"healthy", "degraded"}, run.get("local_stream"))
        check("published_two_dry_posts", published == 2, published)
        check("captured_two_dry_posts", len(captured_posts) == 2, len(captured_posts))

        urls = [post.get("url") for post in dry_last_posts]
        clusters = [post.get("topic_cluster") for post in dry_last_posts if post.get("topic_cluster")]
        image_hashes = [post.get("image_hash") for post in dry_last_posts if post.get("image_hash")]
        check("no_duplicate_urls", len(urls) == len(set(urls)), urls)
        check("no_duplicate_topics", len(clusters) == len(set(clusters)), clusters)
        check("no_duplicate_images", len(image_hashes) == len(set(image_hashes)), image_hashes)

        for index, post in enumerate(dry_last_posts, 1):
            verdict = post.get("editorial_gate") or {}
            check(f"post_{index}_gate_approved", verdict.get("approved") is True, verdict)
            check(f"post_{index}_title_matches_source", int(verdict.get("title_matches_source") or 0) >= 90, verdict)
            check(f"post_{index}_category_matches_story", int(verdict.get("category_matches_story") or 0) >= 90, verdict)
            check(f"post_{index}_facts_supported", verdict.get("facts_supported") is True, verdict)
            check(f"post_{index}_meaning_unchanged", verdict.get("meaning_changed") is False, verdict)

    except Exception as exc:
        report["run_error"] = repr(exc)
        report["traceback"] = traceback.format_exc()[-8000:]
        check("audit_runtime", False, repr(exc))

    report["passed"] = sum(1 for item in checks if item["ok"])
    report["failed"] = sum(1 for item in checks if not item["ok"])
    report["all_pass"] = bool(checks) and report["failed"] == 0
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_audit()
    print(json.dumps({
        "version": result.get("version"),
        "candidate_count": result.get("candidate_count"),
        "reconciled_count": result.get("reconciled_count"),
        "offtopic_count": result.get("offtopic_count"),
        "passed": result.get("passed"),
        "failed": result.get("failed"),
        "all_pass": result.get("all_pass"),
        "run_error": result.get("run_error"),
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("all_pass") else 1)
