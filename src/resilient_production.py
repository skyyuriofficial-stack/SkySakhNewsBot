from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import hardened_publisher as hardened
import publisher
import telegram_health

ROOT = Path(__file__).resolve().parents[1]
OUTBOX_PATH = ROOT / "delivery_outbox.json"

_GENERIC_SOURCE_TEASER_RE = re.compile(
    r"^\s*читайте\s+последние\s+актуальные\s+новости\s+главных\s+событий.+"
    r"в\s+ленте\s+новостей\s+на\s+сайте",
    flags=re.I | re.S,
)

_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_TIME_BOUND_DATE_RE = re.compile(
    r"\b([0-3]?\d)\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b",
    flags=re.I,
)
_SAKHALIN_TZ = timezone(timedelta(hours=11))


def _delivery_reason(health: Dict[str, Any]) -> str:
    return "telegram_" + str(health.get("error_kind") or "unhealthy")


def _source_evidence_insufficient(item: Dict[str, Any]) -> bool:
    """Reject a scraper SEO stub that cannot ground a publishable body.

    Some source pages occasionally yield only a generic search/SEO sentence whose
    headline contains dates or subjects but whose article facts were not parsed.
    Keeping such an item in the delivery queue can make a syntactically valid
    generated body look source-supported when the underlying article evidence is
    actually absent. Fail closed instead of guessing from the headline.
    """

    source_text = str(item.get("source_text") or "").strip()
    if not source_text or len(source_text) > 500:
        return False
    return bool(_GENERIC_SOURCE_TEASER_RE.search(source_text))


def _pending_evidence(item: Dict[str, Any]) -> str:
    row = item.get("row") if isinstance(item.get("row"), dict) else {}
    body = row.get("body") if isinstance(row.get("body"), list) else []
    return " ".join(
        [
            str(row.get("title_ru") or item.get("title") or ""),
            *[str(value) for value in body if str(value).strip()],
        ]
    ).strip()


def _published_minute(item: Dict[str, Any]) -> str:
    value = str(item.get("published_at") or "").strip()
    return value[:16] if len(value) >= 16 else ""


def _pending_event_type(item: Dict[str, Any]) -> str:
    contract = item.get("publication_contract") if isinstance(item.get("publication_contract"), dict) else {}
    return str(contract.get("event_type") or "").strip()


def _time_sensitive_item_expired(item: Dict[str, Any], *, now_utc: datetime | None = None) -> bool:
    """Expire an explicitly dated service-disruption notice after its local date.

    This guard is intentionally narrow. It applies only to already-reviewed
    ``public_service_disruption`` items and only when the queued title/body contains
    an explicit Russian calendar date such as ``18 сентября``. It does not age out
    general news merely because delivery has been delayed.
    """

    if _pending_event_type(item) != "public_service_disruption":
        return False

    match = _TIME_BOUND_DATE_RE.search(_pending_evidence(item))
    if not match:
        return False

    try:
        day = int(match.group(1))
        month = _RU_MONTHS[match.group(2).lower()]
    except (TypeError, ValueError, KeyError):
        return False

    published_raw = str(item.get("published_at") or "").strip()
    try:
        published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        published_local = published.astimezone(_SAKHALIN_TZ)
    except (TypeError, ValueError):
        return False

    try:
        event_date = published_local.date().replace(month=month, day=day)
    except ValueError:
        return False

    # Handle a notice published near New Year for an event in early January.
    if event_date < published_local.date() and (published_local.date() - event_date).days > 180:
        try:
            event_date = event_date.replace(year=event_date.year + 1)
        except ValueError:
            return False

    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    today_sakhalin = current.astimezone(_SAKHALIN_TZ).date()
    return event_date < today_sakhalin


def _same_deferred_event(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Conservative second-pass dedupe for cross-source outage backlog items.

    The canonical detector is intentionally title/source-centric. During an
    outage, however, two outlets can describe the same event with substantially
    different headlines while their already-reviewed body facts still match.
    Only treat the items as duplicates when category, event type and publication
    minute agree, the outlets/URLs are different, and both title and full queued
    evidence retain measurable semantic overlap.
    """

    if str(left.get("category_key") or "") != str(right.get("category_key") or ""):
        return False
    left_type = _pending_event_type(left)
    right_type = _pending_event_type(right)
    if not left_type or left_type != right_type:
        return False
    left_minute = _published_minute(left)
    right_minute = _published_minute(right)
    if not left_minute or left_minute != right_minute:
        return False
    if str(left.get("url") or "") == str(right.get("url") or ""):
        return False
    if str(left.get("source") or "").strip().lower() == str(right.get("source") or "").strip().lower():
        return False

    left_row = left.get("row") if isinstance(left.get("row"), dict) else {}
    right_row = right.get("row") if isinstance(right.get("row"), dict) else {}
    left_title = str(left_row.get("title_ru") or left.get("title") or "")
    right_title = str(right_row.get("title_ru") or right.get("title") or "")
    title_similarity = hardened.editorial_hardening.text_similarity(left_title, right_title)
    evidence_similarity = hardened.editorial_hardening.text_similarity(
        _pending_evidence(left), _pending_evidence(right)
    )
    return bool(title_similarity >= 0.10 and evidence_similarity >= 0.26)


def _retire_deferred_duplicates(state: Dict[str, Any]) -> int:
    pending = [
        item
        for item in (state.get("pending_media_delivery") or [])
        if isinstance(item, dict)
    ]
    if len(pending) < 2:
        return 0

    accepted = []
    retired = []
    for item in pending:
        duplicate_of = next(
            (kept for kept in accepted if _same_deferred_event(item, kept)),
            None,
        )
        if duplicate_of is None:
            accepted.append(item)
            continue
        retired.append(
            hardened._retire(
                item,
                "pending_semantic_duplicate_cross_source:"
                + str(duplicate_of.get("title") or "")[:240],
            )
        )

    if retired:
        existing_expired = [
            item
            for item in (state.get("expired_media_delivery") or [])
            if isinstance(item, dict)
        ]
        state["pending_media_delivery"] = accepted
        state["expired_media_delivery"] = (existing_expired + retired)[-80:]
    return len(retired)


def _sanitize_delivery_queue(state: Dict[str, Any]) -> Dict[str, int]:
    """Run canonical hardening plus fail-closed evidence, freshness and dedupe guards."""

    report = dict(hardened.sanitize_pending_queue(state))
    cross_source_duplicates = _retire_deferred_duplicates(state)
    if cross_source_duplicates:
        report["duplicates"] = int(report.get("duplicates") or 0) + cross_source_duplicates
        report["retired"] = int(report.get("retired") or 0) + cross_source_duplicates
        report["after"] = len(state.get("pending_media_delivery") or [])

    pending = [
        item
        for item in (state.get("pending_media_delivery") or [])
        if isinstance(item, dict)
    ]
    if not pending:
        report["insufficient_source_retired"] = 0
        report["time_sensitive_retired"] = 0
        return report

    accepted = []
    insufficient_retired = []
    time_sensitive_retired = []
    for item in pending:
        if _time_sensitive_item_expired(item):
            time_sensitive_retired.append(
                hardened._retire(
                    item,
                    "pending_event_expired:public_service_disruption_past_date",
                )
            )
        elif _source_evidence_insufficient(item):
            insufficient_retired.append(
                hardened._retire(
                    item,
                    "pending_revalidation_failed:source_text_insufficient_for_body",
                )
            )
        else:
            accepted.append(item)

    newly_retired = time_sensitive_retired + insufficient_retired
    if newly_retired:
        existing_expired = [
            item
            for item in (state.get("expired_media_delivery") or [])
            if isinstance(item, dict)
        ]
        state["pending_media_delivery"] = accepted
        state["expired_media_delivery"] = (existing_expired + newly_retired)[-80:]

    report["insufficient_source_retired"] = len(insufficient_retired)
    report["time_sensitive_retired"] = len(time_sensitive_retired)
    report["after"] = len(state.get("pending_media_delivery") or [])
    report["retired"] = int(report.get("retired") or 0) + len(newly_retired)
    return report


def _install_queue_only_delivery(health: Dict[str, Any]) -> None:
    """Keep editorial production running while the live delivery adapter is down.

    The lower media layer already persists a fully reviewed post when sendPhoto
    fails and the text fallback is invoked. Replacing sendPhoto with a fast,
    deterministic failure avoids repeatedly calling a credential that is known
    to be invalid while still exercising collection, editorial review, source
    media validation, publication-contract validation and persistent queuing.
    """

    reason = _delivery_reason(health)

    def queue_only_send_photo(candidate: Dict[str, Any], caption: str):
        candidate["_delivery_error"] = "delivery_adapter_unavailable:" + reason
        raise RuntimeError(candidate["_delivery_error"])

    publisher.core.b.send_photo = queue_only_send_photo
    # Existing-post repair is a live Telegram mutation. Do not waste calls or
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
    queue_report = _sanitize_delivery_queue(state)
    health = telegram_health.check_telegram()
    telegram_health.write_status(health)
    hardened._record_health(state, health, queue_report)

    if health.get("status") != "healthy":
        _install_queue_only_delivery(health)

    # Persist the health snapshot before collection so a hard editorial failure
    # still leaves an inspectable record. Telegram health never stops the
    # editorial plane here.
    hardened._save_state(state)

    publisher.main()

    # Freshly deferred items are created inside publisher.main(), after the
    # preflight queue sanitation above. Revalidate them before they become the
    # durable source of truth or are emitted to delivery_outbox.json.
    state = hardened._load_state()
    postflight_queue_report = _sanitize_delivery_queue(state)
    state["telegram_health"] = health
    hardened._record_health(state, health, postflight_queue_report)
    _record_plane_status(state, health)
    _write_outbox(state, health)
    hardened._save_state(state)

    print(json.dumps({
        "status": "ok" if health.get("status") == "healthy" else "editorial_ok_delivery_blocked",
        "telegram_health": health,
        "last_run": state.get("last_run") or {},
        "preflight_queue": queue_report,
        "postflight_queue": postflight_queue_report,
        "outbox_count": len(state.get("pending_media_delivery") or []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
