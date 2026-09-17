from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import resilient_production as rp


def main() -> int:
    fire_astv = {
        "source": "ASTV",
        "url": "https://astv.ru/news/criminal/example-red-tym",
        "category_key": "sakh_chp",
        "published_at": "2026-09-17T13:00:00+00:00",
        "publication_contract": {"event_type": "major_emergency"},
        "row": {
            "title_ru": "Тело женщины обнаружили при тушении пожара в жилом доме в селе Красная Тымь",
            "body": [
                "Признаков насильственной смерти не обнаружено, назначена экспертиза.",
                "Как сообщают в сахалинском следкоме, возгорание произошло 17 сентября в одной из квартир дома по улице Юбилейной.",
            ],
        },
    }
    fire_sakh_online = {
        "source": "Sakh.online",
        "url": "https://sakh.online/news/example-tym-fire",
        "category_key": "sakh_chp",
        "published_at": "2026-09-17T13:00:00+00:00",
        "publication_contract": {"event_type": "major_emergency"},
        "row": {
            "title_ru": "Следователи выяснят причины гибели женщины при пожаре в селе Тымовского района",
            "body": [
                "При осмотре специалисты не выявили признаков насильственной смерти.",
                "В четверг, 17 сентября, в одной из квартир дома по улице Юбилейной обнаружили тело 42-летней местной жительницы.",
            ],
        },
    }
    assert rp._same_deferred_event(fire_astv, fire_sakh_online), (
        fire_astv,
        fire_sakh_online,
    )

    unrelated = copy.deepcopy(fire_sakh_online)
    unrelated["url"] = "https://sakh.online/news/unrelated-fire"
    unrelated["published_at"] = "2026-09-17T14:00:00+00:00"
    assert not rp._same_deferred_event(fire_astv, unrelated), unrelated

    fake_state = {
        "pending_media_delivery": [],
        "last_run": {},
    }
    health = {
        "status": "error",
        "error_kind": "token_unauthorized",
        "http_status": 401,
        "checked_at_utc": "2026-09-17T00:00:00+00:00",
    }

    original = {
        "load": rp.hardened._load_state,
        "save": rp.hardened._save_state,
        "sanitize": rp.hardened.sanitize_pending_queue,
        "record": rp.hardened._record_health,
        "install_guard": rp.hardened.install_run_diversity_guard,
        "check": rp.telegram_health.check_telegram,
        "write": rp.telegram_health.write_status,
        "publisher_main": rp.publisher.main,
        "queue_only": rp._install_queue_only_delivery,
        "outbox": rp.OUTBOX_PATH,
    }

    with tempfile.TemporaryDirectory() as tmp:
        rp.OUTBOX_PATH = Path(tmp) / "delivery_outbox.json"

        def load_state():
            return fake_state

        def save_state(state):
            snapshot = copy.deepcopy(state)
            fake_state.clear()
            fake_state.update(snapshot)

        def publisher_main():
            fake_state["last_run"] = {
                "version": "stable-v12.1",
                "status": "ok",
                "finished_sakhalin": "2026-09-17T11:00:00+11:00",
                "candidates": 2,
                "published": 0,
            }
            fake_state["pending_media_delivery"] = [{
                "queued_at": "2026-09-17T00:00:00+00:00",
                "url": "https://example.test/news/1",
                "source": "test-source",
                "category_key": "ru_eco",
                "category": "Экономика",
                "row": {
                    "title_ru": "Тестовый материал",
                    "body": ["Первое предложение.", "Второе предложение."],
                },
                "publication_contract": {"status": "valid"},
                "last_error": "delivery_adapter_unavailable:telegram_token_unauthorized",
            }]
            return None

        try:
            rp.hardened._load_state = load_state
            rp.hardened._save_state = save_state
            rp.hardened.sanitize_pending_queue = lambda state: {"kept": len(state.get("pending_media_delivery") or [])}
            rp.hardened._record_health = lambda state, h, q: state.__setitem__("telegram_health", h)
            rp.hardened.install_run_diversity_guard = lambda: None
            rp.telegram_health.check_telegram = lambda: dict(health)
            rp.telegram_health.write_status = lambda h: None
            rp.publisher.main = publisher_main
            rp._install_queue_only_delivery = lambda h: None

            rc = rp.main()
            assert rc == 0, rc
            assert fake_state["last_run"]["status"] == "ok"
            attempt = fake_state.get("last_production_attempt") or {}
            assert attempt.get("status") == "editorial_ok_delivery_blocked", attempt
            planes = fake_state.get("service_planes") or {}
            assert (planes.get("editorial") or {}).get("status") == "healthy", planes
            assert (planes.get("delivery") or {}).get("status") == "blocked", planes
            assert (planes.get("delivery") or {}).get("queue_size") == 1, planes

            outbox = json.loads(rp.OUTBOX_PATH.read_text(encoding="utf-8"))
            assert outbox.get("count") == 1, outbox
            assert outbox["items"][0]["title"] == "Тестовый материал", outbox
            assert outbox.get("delivery_adapter_error") == "token_unauthorized", outbox
        finally:
            rp.hardened._load_state = original["load"]
            rp.hardened._save_state = original["save"]
            rp.hardened.sanitize_pending_queue = original["sanitize"]
            rp.hardened._record_health = original["record"]
            rp.hardened.install_run_diversity_guard = original["install_guard"]
            rp.telegram_health.check_telegram = original["check"]
            rp.telegram_health.write_status = original["write"]
            rp.publisher.main = original["publisher_main"]
            rp._install_queue_only_delivery = original["queue_only"]
            rp.OUTBOX_PATH = original["outbox"]

    print("resilient_selftest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
