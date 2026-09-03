"""Canonical SkySakhNews publisher with autonomous news-director control.

This is the only production entrypoint. The lower modules collect, validate,
format and deliver; this module decides what is actually news, autocorrects the
stream, and keeps the rolling editorial proportions.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence

import media_enforced_runner as media
import news_director as director

VERSION = "stable-v11.0"

media.VERSION = VERSION
media.editorial.VERSION = VERSION
media.editorial.prod.VERSION = VERSION
media.editorial.core.VERSION = VERSION
media.prod.VERSION = VERSION
media.core.VERSION = VERSION
core = media.core
prod = media.prod

DIRECTOR_AI_BUDGET = max(0, int(os.getenv("NEWS_DIRECTOR_AI_BUDGET", "0")))
_DIRECTOR_AI_CALLS = 0
_DIRECTOR_REPORT: Dict[str, Any] = {}
_DIRECTOR_BY_URL: Dict[str, Dict[str, Any]] = {}
_CANDIDATE_BY_URL: Dict[str, Dict[str, Any]] = {}

for key in (
    "director_seen",
    "director_approved",
    "director_rejected",
    "director_reclassified",
    "director_ai_calls",
    "director_ai_fail",
    "director_final_reject",
    "director_pending_retired",
    "director_deterministic_fallback",
):
    core.b.STATS.setdefault(key, 0)


# The deterministic director is authoritative. OpenRouter is an optional veto,
# never a single point of failure that can erase otherwise valid candidates.
_original_apply_ai_review = director._apply_ai_review


def _apply_ai_review_optional(review, ai):
    if ai is None:
        if review.get("needs_ai_review"):
            core.b.STATS["director_deterministic_fallback"] += 1
            review["ai_review_status"] = "unavailable_deterministic_policy"
        return review
    return _original_apply_ai_review(review, ai)


director._apply_ai_review = _apply_ai_review_optional


def _director_ai_review(
    reviews: Sequence[Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    global _DIRECTOR_AI_CALLS
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
                        "Ты независимый главный редактор. "
                        "Не переписывай новости. Верни только валидный JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": director.ai_review_prompt(reviews),
                },
            ],
            max_tokens=1300,
        )
        parsed = core.b.parse_obj(raw)
        return director.normalize_ai_reviews(parsed)
    except Exception as exc:
        core.b.STATS["director_ai_fail"] += 1
        core.b.log(f"news director AI unavailable: {str(exc)[:260]}")
        return {}


_original_collect = core.b.collect


def collect_with_news_director(state):
    global _DIRECTOR_REPORT, _DIRECTOR_BY_URL, _CANDIDATE_BY_URL

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
        ai_reviewer=_director_ai_review,
    )

    _DIRECTOR_REPORT = report
    _DIRECTOR_BY_URL = {
        str(url): director.compact_review(review)
        for url, review in (report.get("by_url") or {}).items()
    }
    _CANDIDATE_BY_URL = {
        str(candidate.get("url") or ""): {
            "title": str(candidate.get("title") or ""),
            "source_text_excerpt": str(candidate.get("source_text") or "")[:1200],
            "source": str(candidate.get("source") or ""),
            "published_at": str(candidate.get("published_at") or ""),
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

    core.b.log(
        "news director: "
        f"seen={report.get('candidate_count', 0)} "
        f"approved={report.get('approved_count', 0)} "
        f"rejected={report.get('rejected_count', 0)} "
        f"second_slot={report.get('scheduled_second_group')}"
    )
    for preview in (report.get("selected_preview") or [])[:4]:
        core.b.log(
            "director slot "
            + str(preview.get("slot"))
            + ": "
            + str(preview.get("category_key"))
            + " / "
            + str(preview.get("seriousness"))
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


def valid_post_with_news_director(candidate):
    metadata = candidate.get("_news_director") or {}
    if metadata.get("approved") is not True:
        core.b.STATS["director_final_reject"] += 1
        return None

    row = _original_valid_post(candidate)
    if not row:
        return None

    # Read the final generated headline/body again. This catches a late rewrite
    # which would move the post out of the approved subject or turn it into soft
    # promotional copy after the source candidate itself had passed.
    final_candidate = dict(candidate)
    final_candidate["title"] = row.get("title_ru") or candidate.get("title")
    final_candidate["source_text"] = " ".join(
        str(value) for value in (row.get("body") or []) if str(value).strip()
    ) or candidate.get("source_text")

    final_review = director.review_candidate(final_candidate)
    if (
        final_review.get("approved") is not True
        or final_review.get("corrected_category") != candidate.get("category_key")
    ):
        core.b.STATS["director_final_reject"] += 1
        core.b.log(
            "news director final reject: "
            + str(candidate.get("title") or "")[:100]
            + " | "
            + str(final_review.get("reason"))
        )
        return None

    compact = director.compact_review(metadata)
    compact["final_title_checked"] = True
    compact["final_category_checked"] = True
    row["news_director"] = compact
    _DIRECTOR_BY_URL[str(candidate.get("url") or "")] = compact
    return row


core.b.valid_post = valid_post_with_news_director


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
            delivery = media._DELIVERY_BY_URL.get(url) or {}
            if delivery.get("message_id") is not None:
                post["telegram_message_id"] = delivery.get("message_id")
            if delivery.get("chat_id") is not None:
                post["telegram_chat_id"] = delivery.get("chat_id")

    report = director.finalize_report(state, _DIRECTOR_REPORT)
    run["version"] = VERSION
    run["news_director"] = report
    run["stats"] = dict(core.b.STATS)
    state["last_run"] = run
    state["news_director_policy"] = {
        "version": director.VERSION,
        "rolling_window": director.ROLLING_WINDOW,
        "targets": dict(director.TARGET_COUNTS),
        "second_slot_by_hour": dict(director.SECOND_SLOT_BY_HOUR),
    }
    state["news_balance"] = report.get("rolling_balance_after") or {}

    _original_save_state(state)


core.b.save_state = save_state_with_news_director


def main():
    media.main()


if __name__ == "__main__":
    main()
