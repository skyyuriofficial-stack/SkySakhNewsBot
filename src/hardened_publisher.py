from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import editorial_hardening

editorial_hardening.install()

import publisher
import telegram_health

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"

_PUBLISHED_GROUPS: set[str] = set()
_PUBLISHED_EVENTS: List[Dict[str, Any]] = []


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _candidate_from_pending(item: Dict[str, Any]) -> Dict[str, Any]:
    category_key = str(item.get("category_key") or "")
    category, footer = publisher.core.b.CAT.get(category_key, (str(item.get("category") or ""), str(item.get("footer") or "")))
    return {
        "source": item.get("source"),
        "category_key": category_key,
        "category": category,
        "footer": footer,
        "title": item.get("title"),
        "title_original": item.get("title_original"),
        "source_text": item.get("source_text"),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "topic_cluster": item.get("topic_cluster"),
        "image_url": item.get("image_url"),
        "image_hash": item.get("image_hash"),
        "_pending_delivery": True,
    }


def _pending_score(item: Dict[str, Any]) -> int:
    row = item.get("row") or {}
    body = row.get("body") if isinstance(row.get("body"), list) else []
    body_chars = sum(len(str(value or "")) for value in body)
    return body_chars + (250 if item.get("image_url") else 0) - 20 * int(item.get("delivery_attempts") or 0)


def _retire(item: Dict[str, Any], reason: str) -> Dict[str, Any]:
    value = copy.deepcopy(item)
    value["expired_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    value["expired_reason"] = reason[:500]
    return value


def sanitize_pending_queue(state: Dict[str, Any]) -> Dict[str, int]:
    pending = [item for item in (state.get("pending_media_delivery") or []) if isinstance(item, dict)]
    if not pending:
        return {"before": 0, "after": 0, "retired": 0, "duplicates": 0}

    accepted: List[Dict[str, Any]] = []
    retired: List[Dict[str, Any]] = []

    for item in sorted(pending, key=_pending_score, reverse=True):
        candidate = _candidate_from_pending(item)
        row = copy.deepcopy(item.get("row") or {})
        issues = editorial_hardening.content_quality_issues(candidate, row)

        try:
            contract = publisher.director.validate_final(candidate, row)
        except Exception as exc:
            contract = {"approved": False, "issues": ["pending_contract_exception:" + str(exc)[:180]]}

        if issues or contract.get("approved") is not True:
            reasons = list(issues) + [str(value) for value in (contract.get("issues") or [])]
            retired.append(_retire(item, "pending_revalidation_failed:" + ";".join(dict.fromkeys(reasons))[:420]))
            continue

        duplicate_of = next(
            (kept for kept in accepted if editorial_hardening.duplicate_event(candidate, _candidate_from_pending(kept))),
            None,
        )
        if duplicate_of is not None:
            retired.append(_retire(item, "pending_semantic_duplicate:" + str(duplicate_of.get("title") or "")[:240]))
            continue

        accepted.append(item)

    existing_expired = [item for item in (state.get("expired_media_delivery") or []) if isinstance(item, dict)]
    state["pending_media_delivery"] = accepted[:24]
    if retired:
        state["expired_media_delivery"] = (existing_expired + retired)[-80:]

    return {
        "before": len(pending),
        "after": len(state.get("pending_media_delivery") or []),
        "retired": len(retired),
        "duplicates": sum(1 for item in retired if str(item.get("expired_reason") or "").startswith("pending_semantic_duplicate")),
    }


def install_run_diversity_guard() -> None:
    original_valid_post = publisher.core.b.valid_post
    original_delivery_success = publisher.media._delivery_success
    original_utility = publisher.director._utility

    def balanced_utility(candidate, review, balance, selected):
        value = float(original_utility(candidate, review, balance, selected))
        group = str(review.get("group") or "")
        counts = balance.get("counts") or {}
        targets = balance.get("targets") or publisher.director.TARGET_COUNTS
        count = float(counts.get(group, 0) or 0)
        target = float(targets.get(group, 0) or 0)
        delta = target - count
        if delta > 0:
            value += min(160.0, 28.0 * delta)
        elif delta < 0:
            value -= min(280.0, 40.0 * abs(delta))
        return value

    def diverse_valid_post(candidate):
        review = candidate.get("_news_director") or {}
        group = str(review.get("group") or "")
        if group and group in _PUBLISHED_GROUPS:
            publisher.core.b.log(
                f"run diversity guard skip [{group}]: " + str(candidate.get("title") or "")[:110]
            )
            return None
        if any(editorial_hardening.duplicate_event(candidate, old) for old in _PUBLISHED_EVENTS):
            publisher.core.b.log(
                "run semantic-duplicate guard skip: " + str(candidate.get("title") or "")[:110]
            )
            return None
        return original_valid_post(candidate)

    def tracked_delivery_success(candidate, result, mode):
        value = original_delivery_success(candidate, result, mode)
        review = candidate.get("_news_director") or {}
        group = str(review.get("group") or "")
        if group:
            _PUBLISHED_GROUPS.add(group)
        _PUBLISHED_EVENTS.append(copy.deepcopy(candidate))
        return value

    publisher.director._utility = balanced_utility
    publisher.core.b.valid_post = diverse_valid_post
    publisher.media._delivery_success = tracked_delivery_success


def _record_health(state: Dict[str, Any], health: Dict[str, Any], queue_report: Dict[str, int]) -> None:
    state["telegram_health"] = health
    state["pending_queue_hardening"] = {
        **queue_report,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "pending-hardening-v1",
    }


def main() -> int:
    install_run_diversity_guard()
    state = _load_state()
    queue_report = sanitize_pending_queue(state)
    health = telegram_health.check_telegram()
    telegram_health.write_status(health)
    _record_health(state, health, queue_report)

    if health.get("status") != "healthy":
        state["last_production_attempt"] = {
            "status": "blocked",
            "reason": "telegram_" + str(health.get("error_kind") or "unhealthy"),
            "checked_at_utc": health.get("checked_at_utc"),
            "publisher_version": publisher.VERSION,
            "queue_preserved": len(state.get("pending_media_delivery") or []),
        }
        _save_state(state)
        print(json.dumps({
            "status": "blocked_before_collection",
            "telegram_health": health,
            "pending_queue": queue_report,
        }, ensure_ascii=False, indent=2))
        return 23

    _save_state(state)
    publisher.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
