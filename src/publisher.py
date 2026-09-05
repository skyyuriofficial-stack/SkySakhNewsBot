"""Canonical SkySakhNews publisher with a self-correcting editorial contract."""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence

import media_enforced_runner as media
import news_director as director
import publication_auditor

VERSION = "stable-v12.1"

media.VERSION = VERSION
media.editorial.VERSION = VERSION
media.editorial.prod.VERSION = VERSION
media.editorial.core.VERSION = VERSION
media.prod.VERSION = VERSION
media.core.VERSION = VERSION
core = media.core
prod = media.prod

DIRECTOR_AI_BUDGET = max(0, int(os.getenv("NEWS_DIRECTOR_AI_BUDGET", "0")))
POST_AUDIT_AUTOCORRECT = os.getenv("POST_AUDIT_AUTOCORRECT", "1") == "1"

_DIRECTOR_AI_CALLS = 0
_DIRECTOR_REPORT: Dict[str, Any] = {}
_DIRECTOR_BY_URL: Dict[str, Dict[str, Any]] = {}
_CANDIDATE_BY_URL: Dict[str, Dict[str, Any]] = {}
_ROW_BY_URL: Dict[str, Dict[str, Any]] = {}
_CAPTION_BY_URL: Dict[str, str] = {}
_CONTRACT_BY_URL: Dict[str, Dict[str, Any]] = {}

for key in (
    "director_seen",
    "director_approved",
    "director_rejected",
    "director_reclassified",
    "director_title_corrected",
    "director_ai_calls",
    "director_ai_fail",
    "director_final_checked",
    "director_final_autocorrected",
    "director_final_reject",
    "director_pending_retired",
    "publication_contract_blocked",
    "post_audit_checked",
    "post_audit_anomalies",
    "post_audit_corrected",
    "post_audit_deleted",
):
    core.b.STATS.setdefault(key, 0)


def _director_ai_review(
    reviews: Sequence[Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    global _DIRECTOR_AI_CALLS
    if DIRECTOR_AI_BUDGET <= 0:
        return {}
    if _DIRECTOR_AI_CALLS >= DIRECTOR_AI_BUDGET:
        return {}
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        return {}

    _DIRECTOR_AI_CALLS += 1
    core.b.STATS["director_ai_calls"] = _DIRECTOR_AI_CALLS
    try:
        raw = core.b.openrouter(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты независимый выпускающий редактор. Не переписывай новости. "
                        "Верни только валидный JSON."
                    ),
                },
                {"role": "user", "content": director.ai_review_prompt(reviews)},
            ],
            max_tokens=1000,
        )
        return director.normalize_ai_reviews(core.b.parse_obj(raw))
    except Exception as exc:
        core.b.STATS["director_ai_fail"] += 1
        core.b.log(f"news director AI unavailable: {str(exc)[:260]}")
        return {}


_original_collect = core.b.collect


def _audit_existing_posts(state: Dict[str, Any]) -> None:
    try:
        report = publication_auditor.audit_recent_posts(
            state,
            category_map=core.b.CAT,
            render_caption=core.b.caption,
            mutate=POST_AUDIT_AUTOCORRECT,
        )
        core.b.STATS["post_audit_checked"] = int(report.get("checked") or 0)
        core.b.STATS["post_audit_anomalies"] = len(report.get("anomalies") or [])
        core.b.STATS["post_audit_corrected"] = len(report.get("corrected") or [])
        core.b.STATS["post_audit_deleted"] = len(report.get("deleted") or [])
    except Exception as exc:
        core.b.log(f"post-publication audit failed safely: {str(exc)[:260]}")


def collect_with_news_director(state):
    global _DIRECTOR_REPORT, _DIRECTOR_BY_URL, _CANDIDATE_BY_URL

    _audit_existing_posts(state)
    candidates = _original_collect(state)
    pending_before = {
        str(candidate.get("url") or "")
        for candidate in candidates
        if candidate.get("_pending_delivery")
    }

    ordered, report = director.direct_candidates(
        state,
        candidates,
        category_map=core.b.CAT,
        now=datetime.now(core.b.TZ),
        ai_reviewer=_director_ai_review if DIRECTOR_AI_BUDGET > 0 else None,
    )

    _DIRECTOR_REPORT = report
    _DIRECTOR_BY_URL = {
        str(url): director.compact_review(review)
        for url, review in (report.get("by_url") or {}).items()
    }
    _CANDIDATE_BY_URL = {
        str(candidate.get("url") or ""): {
            "title": str(candidate.get("title") or ""),
            "title_original": str(candidate.get("title_original") or ""),
            "source_text_excerpt": str(candidate.get("source_text") or "")[:2600],
            "source": str(candidate.get("source") or ""),
            "published_at": str(candidate.get("published_at") or ""),
            "category_key": str(candidate.get("category_key") or ""),
        }
        for candidate in ordered
        if candidate.get("url")
    }

    core.b.STATS["director_seen"] = int(report.get("candidate_count") or 0)
    core.b.STATS["director_approved"] = int(report.get("approved_count") or 0)
    core.b.STATS["director_rejected"] = int(report.get("rejected_count") or 0)
    core.b.STATS["director_reclassified"] = sum(
        1 for candidate in ordered if candidate.get("_news_director_reclass")
    )
    core.b.STATS["director_title_corrected"] = sum(
        1 for candidate in ordered if (candidate.get("_news_director") or {}).get("title_changed")
    )

    approved_urls = {str(candidate.get("url") or "") for candidate in ordered}
    for url in pending_before:
        metadata = (report.get("by_url") or {}).get(url) or {}
        reclassified = any(
            str(candidate.get("url") or "") == url
            and candidate.get("_news_director_reclass")
            for candidate in ordered
        )
        if url not in approved_urls or reclassified:
            old = media._PENDING_EXISTING.pop(url, None)
            if old:
                retired = copy.deepcopy(old)
                retired["expired_at"] = datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                )
                retired["expired_reason"] = (
                    "news_director_reclassified"
                    if reclassified
                    else "news_director_rejected"
                )
                retired["news_director"] = director.compact_review(metadata)
                media._EXPIRED_THIS_RUN.append(retired)
                core.b.STATS["director_pending_retired"] += 1

    balance = report.get("rolling_balance_before") or {}
    core.b.log(
        "news director v2: "
        f"seen={report.get('candidate_count', 0)} "
        f"approved={report.get('approved_count', 0)} "
        f"rejected={report.get('rejected_count', 0)} "
        f"mix_error={balance.get('distribution_error')}"
    )
    for preview in (report.get("selected_preview") or [])[:6]:
        core.b.log(
            "director slot "
            + str(preview.get("slot"))
            + ": "
            + str(preview.get("category_key"))
            + " / "
            + str(preview.get("event_type"))
            + " / score="
            + str(preview.get("seriousness"))
            + " / utility="
            + str(preview.get("utility"))
            + " | "
            + str(preview.get("title") or "")[:100]
        )

    return ordered


core.b.collect = collect_with_news_director


def ordered_by_news_director(candidates):
    return sorted(
        candidates,
        key=lambda candidate: int(candidate.get("_news_director_order", 10_000)),
    )


core.b.ordered = ordered_by_news_director


_original_valid_post = core.b.valid_post


def _refresh_editorial_gate(candidate, row):
    try:
        review = media.editorial._review(candidate, row)
    except Exception:
        return None
    if not review or review.get("approved") is not True:
        return None
    row["editorial_gate"] = media.editorial._compact_audit(review, candidate)
    media.editorial.AUDIT_BY_URL[str(candidate.get("url") or "")] = copy.deepcopy(
        row["editorial_gate"]
    )
    return row


def _attempt_final_autocorrection(candidate, row):
    metadata = candidate.get("_news_director") or {}
    source_title = str(metadata.get("title_corrected") or candidate.get("title") or "")
    generated_title = str(row.get("title_ru") or "")

    # Critical invariant: a foreign source title may never overwrite an already
    # Russian translated headline. If neither candidate is Russian, fail closed.
    if director.policy.headline_is_russian(generated_title):
        corrected_title = generated_title
    elif director.policy.headline_is_russian(source_title):
        corrected_title = source_title
    else:
        contract = director.validate_final(candidate, row)
        return None, contract, None

    title_repaired = copy.deepcopy(row)
    title_repaired["title_ru"] = corrected_title
    title_repaired = _refresh_editorial_gate(candidate, title_repaired) or title_repaired
    contract = director.validate_final(candidate, title_repaired)
    if contract.get("approved"):
        core.b.STATS["director_final_autocorrected"] += 1
        return title_repaired, contract, "corrected_title"

    # Extractive rebuild is valid only for a Russian source.
    if gate_is_russian_source(candidate):
        fallback = prod._extractive_fallback(candidate)
        if fallback:
            fallback["title_ru"] = corrected_title
            fallback = _refresh_editorial_gate(candidate, fallback) or fallback
            contract = director.validate_final(candidate, fallback)
            if contract.get("approved"):
                core.b.STATS["director_final_autocorrected"] += 1
                return fallback, contract, "safe_extractive_rebuild"

    return None, contract, None


def gate_is_russian_source(candidate):
    return media.editorial.gate.is_russian_text(
        str(candidate.get("title") or "")
        + " "
        + str(candidate.get("source_text") or "")
    )


def valid_post_with_news_director(candidate):
    metadata = candidate.get("_news_director") or {}
    if metadata.get("approved") is not True:
        core.b.STATS["director_final_reject"] += 1
        return None

    row = _original_valid_post(candidate)
    if not row:
        return None

    core.b.STATS["director_final_checked"] += 1
    contract = director.validate_final(candidate, row)
    correction_mode = None

    if not contract.get("approved"):
        repaired, contract, correction_mode = _attempt_final_autocorrection(candidate, row)
        if repaired is None:
            core.b.STATS["director_final_reject"] += 1
            core.b.STATS["publication_contract_blocked"] += 1
            core.b.log(
                "publication contract reject: "
                + str(candidate.get("title") or "")[:100]
                + " | "
                + "; ".join(str(issue) for issue in contract.get("issues", [])[:8])
            )
            return None
        row = repaired

    compact = director.compact_review(metadata)
    compact["final_title_checked"] = True
    compact["final_category_checked"] = True
    compact["final_autocorrection"] = correction_mode
    row["news_director"] = compact
    row["publication_contract"] = contract

    url = str(candidate.get("url") or "")
    _DIRECTOR_BY_URL[url] = compact
    _ROW_BY_URL[url] = copy.deepcopy(row)
    _CONTRACT_BY_URL[url] = copy.deepcopy(contract)
    candidate["_final_row"] = copy.deepcopy(row)
    candidate["_publication_contract"] = copy.deepcopy(contract)
    return row


core.b.valid_post = valid_post_with_news_director


_original_send_photo = core.b.send_photo


def send_photo_with_contract(candidate, caption):
    contract = candidate.get("_publication_contract") or {}
    if contract.get("approved") is not True:
        core.b.STATS["publication_contract_blocked"] += 1
        raise RuntimeError("publication_contract_missing_or_failed")
    url = str(candidate.get("url") or "")
    _CAPTION_BY_URL[url] = str(caption or "")
    return _original_send_photo(candidate, caption)


core.b.send_photo = send_photo_with_contract


_original_delivery_success = media._delivery_success


def delivery_success_with_message_id(candidate, result, mode):
    value = _original_delivery_success(candidate, result, mode)
    record = media._DELIVERY_BY_URL.setdefault(str(candidate.get("url") or ""), {})
    payload = result.get("result") if isinstance(result, dict) else None
    if isinstance(payload, dict):
        if payload.get("message_id") is not None:
            record["message_id"] = payload.get("message_id")
        chat = payload.get("chat")
        if isinstance(chat, dict) and chat.get("id") is not None:
            record["chat_id"] = chat.get("id")
    return value


media._delivery_success = delivery_success_with_message_id


_original_save_state = core.b.save_state


def save_state_with_news_director(state):
    run = state.get("last_run") or {}
    published = int(run.get("published") or 0)

    if published:
        for post in (state.get("last_posts") or [])[-published:]:
            url = str(post.get("url") or "")
            metadata = _DIRECTOR_BY_URL.get(url)
            if metadata:
                post["news_director"] = copy.deepcopy(metadata)
            source = _CANDIDATE_BY_URL.get(url) or {}
            if source:
                post["source_text_excerpt"] = source.get("source_text_excerpt", "")
                post["title_original"] = source.get("title_original") or None
                post["footer"] = core.b.CAT.get(post.get("category_key"), ("", ""))[1]
            if url in _ROW_BY_URL:
                post["published_row"] = copy.deepcopy(_ROW_BY_URL[url])
            if url in _CAPTION_BY_URL:
                post["published_caption"] = _CAPTION_BY_URL[url]
            if url in _CONTRACT_BY_URL:
                post["publication_contract"] = copy.deepcopy(_CONTRACT_BY_URL[url])
            post["publisher_version"] = VERSION

            delivery = media._DELIVERY_BY_URL.get(url) or {}
            if delivery.get("message_id") is not None:
                post["telegram_message_id"] = delivery.get("message_id")
            if delivery.get("chat_id") is not None:
                post["telegram_chat_id"] = delivery.get("chat_id")

    report = director.finalize_report(state, _DIRECTOR_REPORT)
    run["version"] = VERSION
    run["news_director"] = report
    run["post_publication_audit"] = state.get("post_publication_audit") or {}
    run["stats"] = dict(core.b.STATS)
    state["last_run"] = run
    state["news_director_policy"] = {
        "version": director.VERSION,
        "policy_version": director.policy.VERSION,
        "rolling_window": director.ROLLING_WINDOW,
        "targets": dict(director.TARGET_COUNTS),
        "target_percent": {
            group: round(100 * count / director.ROLLING_WINDOW, 1)
            for group, count in director.TARGET_COUNTS.items()
        },
        "selection": "quality_plus_rolling_mix_optimizer",
    }
    state["news_balance"] = report.get("rolling_balance_after") or {}

    _original_save_state(state)


core.b.save_state = save_state_with_news_director


def main():
    media.main()


if __name__ == "__main__":
    main()
