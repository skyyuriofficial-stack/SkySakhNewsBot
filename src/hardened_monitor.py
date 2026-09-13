from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import editorial_hardening

editorial_hardening.install()

import editorial_monitor
import news_director
import publication_auditor
import publisher
import telegram_health

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
STATUS_PATH = ROOT / "monitor_status.json"

MIX_ERROR_LIMIT = float(os.getenv("THEMATIC_MIX_ERROR_LIMIT", "8"))
publication_auditor.MAX_MUTATION_AGE_HOURS = 48


def _save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    except Exception:
        return {}


def _delete_post(post, reason):
    message_id = post.get("telegram_message_id")
    chat_id = post.get("telegram_chat_id")
    if message_id is None or chat_id is None:
        return {"ok": False, "description": "telegram_identifiers_missing"}
    result = publication_auditor._telegram_call(
        "deleteMessage",
        {"chat_id": chat_id, "message_id": message_id},
    )
    if result.get("ok"):
        post["auto_deleted"] = True
        post["post_audit"] = {
            "version": "post-audit-hardening-v1.1",
            "approved": False,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "auto_action": "deleted_by_hardening",
            "reason": reason,
        }
    return result


def _repair_post(post, candidate, row, issues):
    message_id = post.get("telegram_message_id")
    chat_id = post.get("telegram_chat_id")
    if message_id is None or chat_id is None:
        return {"ok": False, "description": "telegram_identifiers_missing"}, None, None

    repaired = editorial_hardening.repair_row(candidate, row)
    contract = news_director.validate_final(candidate, repaired)
    if contract.get("approved") is not True:
        return {
            "ok": False,
            "description": "repair_contract_failed:" + ";".join(str(x) for x in (contract.get("issues") or [])[:6]),
        }, repaired, contract

    caption = publisher.core.b.caption(repaired, candidate)
    result = publication_auditor._telegram_call(
        "editMessageCaption",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": "HTML",
        },
    )
    if result.get("ok"):
        post["title"] = str(repaired.get("title_ru") or post.get("title") or "")
        post["published_row"] = repaired
        post["published_caption"] = caption
        post["publication_contract"] = contract
        post["post_audit"] = {
            "version": "post-audit-hardening-v1.1",
            "approved": True,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "auto_action": "caption_repaired_by_hardening",
            "repaired_issues": list(issues),
        }
    return result, repaired, contract


def _pre_audit_cleanup(state, *, mutate: bool):
    actions = []
    failures = []
    if not mutate:
        return actions, failures

    posts = [
        post for post in (state.get("last_posts") or [])[-20:]
        if isinstance(post, dict) and not post.get("auto_deleted")
    ]

    # Repair deterministic caption defects first. Edits are preferred to deletion
    # because they preserve the post, reactions and publication history.
    for post in posts:
        if post.get("auto_deleted"):
            continue
        candidate = publication_auditor._candidate_from_post(post)
        candidate["source_text"] = editorial_hardening.dedupe_source_text(candidate.get("source_text"))
        row = copy.deepcopy(post.get("published_row") or {})
        if not row:
            continue
        contract = news_director.validate_final(candidate, row)
        repairable = [
            issue for issue in (contract.get("issues") or [])
            if str(issue).startswith((
                "body_", "repetitive_body_", "unsupported_sakhalin_resident_identity",
            ))
        ]
        if not repairable:
            continue

        result, repaired, repaired_contract = _repair_post(post, candidate, row, repairable)
        item = {
            "message_id": post.get("telegram_message_id"),
            "title": post.get("title"),
            "category_key": post.get("category_key"),
            "reason": repairable,
        }
        if result.get("ok"):
            actions.append({"action": "repair_caption", **item})
            continue

        # Delete only severe, still-recent contamination that cannot be repaired.
        severe = any(
            issue in {
                "body_contains_publisher_boilerplate",
                "body_contains_contact_or_url",
                "unsupported_sakhalin_resident_identity",
            }
            for issue in repairable
        )
        if severe and publication_auditor._within_mutation_window(post):
            delete_result = _delete_post(post, ";".join(repairable))
            if delete_result.get("ok"):
                actions.append({"action": "delete_unrepairable_post", **item})
                continue
            failures.append({
                "action": "delete_unrepairable_post",
                "error": delete_result.get("description"),
                **item,
            })
            continue

        failures.append({
            "action": "repair_caption",
            "error": result.get("description"),
            "repair_contract": (repaired_contract or {}).get("issues") or [],
            **item,
        })

    # Then remove the newer member of an obvious semantic duplicate pair.
    active = [post for post in posts if not post.get("auto_deleted")]
    for index, post in enumerate(active):
        if post.get("auto_deleted"):
            continue
        candidate = publication_auditor._candidate_from_post(post)
        for older in active[:index]:
            if older.get("auto_deleted"):
                continue
            older_candidate = publication_auditor._candidate_from_post(older)
            if not editorial_hardening.duplicate_event(candidate, older_candidate):
                continue
            if not publication_auditor._within_mutation_window(post):
                break
            result = _delete_post(post, "semantic_duplicate_of:" + str(older.get("title") or "")[:220])
            item = {
                "message_id": post.get("telegram_message_id"),
                "title": post.get("title"),
                "category_key": post.get("category_key"),
                "duplicate_of": older.get("title"),
            }
            if result.get("ok"):
                actions.append({"action": "delete_semantic_duplicate", **item})
            else:
                failures.append({"action": "delete_semantic_duplicate", "error": result.get("description"), **item})
            break

    if actions:
        _save(STATE_PATH, state)
    return actions, failures


def main() -> int:
    health = telegram_health.check_telegram()
    telegram_health.write_status(health)
    requested_mutation = os.getenv("POST_AUDIT_AUTOCORRECT", "1") == "1"
    mutate = bool(requested_mutation and health.get("status") == "healthy")

    state = _load_state()
    hardening_actions, hardening_failures = _pre_audit_cleanup(state, mutate=mutate)

    report = editorial_monitor.run_monitor(mutate=mutate, persist_state=False)
    report["telegram_health"] = health
    report["hardening_actions"] = hardening_actions
    report["hardening_failed_actions"] = hardening_failures

    issues = list(report.get("issues") or [])
    if health.get("status") != "healthy":
        issues.append({
            "type": "telegram_delivery_unhealthy",
            "reason": health.get("error_kind"),
            "http_status": health.get("http_status"),
            "description": health.get("description"),
        })
    if hardening_failures:
        issues.append({
            "type": "hardening_action_failure",
            "count": len(hardening_failures),
            "items": hardening_failures[-8:],
        })

    balance = report.get("balance") or {}
    mix_error = float(balance.get("distribution_error") or 0.0)
    if mix_error >= MIX_ERROR_LIMIT:
        issues.append({
            "type": "thematic_mix_drift",
            "distribution_error": mix_error,
            "limit": MIX_ERROR_LIMIT,
            "counts": balance.get("counts") or {},
            "targets": balance.get("targets") or {},
            "deficits": balance.get("deficits") or {},
        })

    deduped = []
    seen = set()
    for issue in issues:
        key = json.dumps(issue, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)

    report["issues"] = deduped
    report["status"] = "healthy" if not deduped else "error"
    report["mutations_enabled"] = mutate
    report["checked_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _save(STATUS_PATH, report)

    print(json.dumps({
        "status": report.get("status"),
        "issues": report.get("issues"),
        "telegram_health": health,
        "hardening_actions": hardening_actions,
        "hardening_failed_actions": hardening_failures,
        "post_audit": {
            "checked": (report.get("post_audit") or {}).get("checked"),
            "passed": (report.get("post_audit") or {}).get("passed"),
            "unresolved": (report.get("post_audit") or {}).get("unresolved"),
            "failed_actions": len((report.get("post_audit") or {}).get("failed_actions") or []),
        },
        "balance": report.get("balance"),
    }, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "healthy" else 3


if __name__ == "__main__":
    raise SystemExit(main())
