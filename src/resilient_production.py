from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import hardened_publisher as hardened
import publisher
import telegram_health

ROOT = Path(__file__).resolve().parents[1]
OUTBOX_PATH = ROOT / "delivery_outbox.json"


def _delivery_reason(health: Dict[str, Any]) -> str:
    return "telegram_" + str(health.get("error_kind") or "unhealthy")


def _install_queue_only_delivery(health: Dict[str, Any]) -> None:
    """Keep editorial production running while the live delivery adapter is down.

    The lower media layer already persists a fully reviewed post when sendPhoto
    fails and the text fallback is invoked.  Replacing sendPhoto with a fast,
    deterministic failure avoids repeatedly calling a credential that is known
    to be invalid while still exercising collection, editorial review, source
    media validation, publication-contract validation and persistent queuing.
    """

    reason = _delivery_reason(health)

    def queue_only_send_photo(candidate: Dict[str, Any], caption: str):
        candidate["_delivery_error"] = "delivery_adapter_unavailable:" + reason
        raise RuntimeError(candidate["_delivery_error"])

    publisher.core.b.send_photo = queue_only_send_photo
    # Existing-post repair is a live Telegram mutation.  Do not waste calls or
    # manufacture successful corrections while the adapter is known unhealthy.
    publisher.POST_AUDIT_AUTOCORRECT = False


def _outbox_item(item: Dict[str, Any]) -> Dict[str, Any]:
    row = item.get("row") if isinstance(item.get("row"), dict) else {}
    contract = item.get("publication_contract") if isinstance(item.get("publication_contract"), dict) else {}
    return {
        "queued_at": item.get("queued_at"),
        "last_attempt_at": item.get("last_attempt_at"),
        "delivery_attempts": int(item.get("delivery_attempts") or 0),
        "delivery_status": "queued",
        "source": item.get("source"),
        "source_url": item.get("url"),
        "category_key": item.get("category_key"),
        "category": item.get("category"),
        "title": row.get("title_ru") or item.get("title"),
        "body": [str(value) for value in (row.get("body") or []) if str(value).strip()][:3],
        "image_url": item.get("image_url"),
        "image_hash": item.get("image_hash"),
        "published_at": item.get("published_at"),
        "publication_contract": copy.deepcopy(contract),
        "last_error": item.get("last_error"),
    }


def _write_outbox(state: Dict[str, Any], health: Dict[str, Any]) -> None:
    pending = [
        item for item in (state.get("pending_media_delivery") or [])
        if isinstance(item, dict) and item.get("url")
    ]
    payload = {
        "version": "delivery-outbox-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_of_truth": "github_repository",
        "live_delivery_adapter": "telegram",
        "delivery_adapter_status": health.get("status") or "unknown",
        "delivery_adapter_error": health.get("error_kind"),
        "count": len(pending),
        "items": [_outbox_item(item) for item in pending],
    }
    OUTBOX_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _record_plane_status(state: Dict[str, Any], health: Dict[str, Any]) -> None:
    run = state.get("last_run") if isinstance(state.get("last_run"), dict) else {}
    pending_count = len([
        item for item in (state.get("pending_media_delivery") or [])
        if isinstance(item, dict)
    ])
    delivery_ok = health.get("status") == "healthy"
    state["service_planes"] = {
        "version": "split-plane-v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "editorial": {
            "status": "healthy" if run.get("status") == "ok" else str(run.get("status") or "unknown"),
            "finished_sakhalin": run.get("finished_sakhalin"),
            "candidates": int(run.get("candidates") or 0),
            "queued_for_delivery": pending_count,
        },
        "delivery": {
            "status": "healthy" if delivery_ok else "blocked",
            "adapter": "telegram",
            "reason": None if delivery_ok else _delivery_reason(health),
            "http_status": health.get("http_status"),
            "queue_size": pending_count,
        },
    }
    state["last_production_attempt"] = {
        "status": "ok" if delivery_ok else "editorial_ok_delivery_blocked",
        "reason": None if delivery_ok else _delivery_reason(health),
        "checked_at_utc": health.get("checked_at_utc") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher_version": publisher.VERSION,
        "queue_preserved": pending_count,
        "editorial_run_status": run.get("status"),
    }


def main() -> int:
    hardened.install_run_diversity_guard()

    state = hardened._load_state()
    queue_report = hardened.sanitize_pending_queue(state)
    health = telegram_health.check_telegram()
    telegram_health.write_status(health)
    hardened._record_health(state, health, queue_report)

    if health.get("status") != "healthy":
        _install_queue_only_delivery(health)

    # Persist the health snapshot before collection so a hard editorial failure
    # still leaves an inspectable record.  Telegram health never stops the
    # editorial plane here.
    hardened._save_state(state)

    publisher.main()

    state = hardened._load_state()
    state["telegram_health"] = health
    _record_plane_status(state, health)
    _write_outbox(state, health)
    hardened._save_state(state)

    print(json.dumps({
        "status": "ok" if health.get("status") == "healthy" else "editorial_ok_delivery_blocked",
        "telegram_health": health,
        "last_run": state.get("last_run") or {},
        "outbox_count": len(state.get("pending_media_delivery") or []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
