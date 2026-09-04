"""Canonical strict publisher for SkySakhNews stable-v12.0."""

from __future__ import annotations

import copy
from typing import Any, Dict

import editorial_gate as semantic_gate
import publisher as legacy
import quality_v12 as quality

VERSION = "stable-v12.0"

legacy.VERSION = VERSION
legacy.media.VERSION = VERSION
legacy.media.editorial.VERSION = VERSION
legacy.media.editorial.prod.VERSION = VERSION
legacy.media.editorial.core.VERSION = VERSION
legacy.prod.VERSION = VERSION
legacy.core.VERSION = VERSION
core = legacy.core
media = legacy.media

_RAW_COLLECT = getattr(legacy, "_original_collect", core.b.collect)
_VALID_POST = getattr(legacy, "_original_valid_post", core.b.valid_post)
_SAVE_STATE = getattr(legacy, "_original_save_state", core.b.save_state)

_REPORT: Dict[str, Any] = {}
_DECISIONS: Dict[str, Dict[str, Any]] = {}
_FINAL_ROWS: Dict[str, Dict[str, Any]] = {}
_SOURCE_ROWS: Dict[str, Dict[str, Any]] = {}

for key in (
    "quality_v12_seen", "quality_v12_approved", "quality_v12_rejected",
    "quality_v12_reclassified", "quality_v12_final_rejected",
    "quality_v12_title_repaired",
):
    core.b.STATS.setdefault(key, 0)


def collect_strict(state):
    global _REPORT, _DECISIONS, _SOURCE_ROWS
    raw = _RAW_COLLECT(state)
    ordered, report = quality.select(
        state,
        raw,
        category_map=core.b.CAT,
        limit=int(getattr(core.b, "POSTS_PER_RUN", 2) or 2),
    )
    _REPORT = report
    _DECISIONS = {
        str(url): copy.deepcopy(value)
        for url, value in (report.get("by_url") or {}).items()
    }
    _SOURCE_ROWS = {
        str(candidate.get("url") or ""): {
            "source_title": quality.sanitize_title(candidate.get("title")),
            "source_text_excerpt": str(candidate.get("source_text") or "")[:4000],
            "source": candidate.get("source"),
        }
        for candidate in ordered if candidate.get("url")
    }
    core.b.STATS["quality_v12_seen"] = int(report.get("candidate_count") or 0)
    core.b.STATS["quality_v12_approved"] = int(report.get("approved_count") or 0)
    core.b.STATS["quality_v12_rejected"] = int(report.get("rejected_count") or 0)
    core.b.STATS["quality_v12_reclassified"] = sum(
        1 for candidate in ordered if candidate.get("_quality_v12_reclass")
    )
    core.b.log(
        "quality-v12: "
        f"seen={report.get('candidate_count', 0)} "
        f"approved={report.get('approved_count', 0)} "
        f"rejected={report.get('rejected_count', 0)}"
    )
    for item in (report.get("selected") or [])[:6]:
        core.b.log(
            "quality-v12 slot " + str(item.get("slot")) + ": "
            + str(item.get("category_key")) + "/" + str(item.get("score"))
            + " | " + str(item.get("title") or "")[:110]
        )
    return ordered


core.b.collect = collect_strict
core.b.ordered = lambda candidates: sorted(
    candidates,
    key=lambda candidate: int(candidate.get("_quality_v12_order", 10000)),
)


def _is_russian_source(candidate: Dict[str, Any]) -> bool:
    return quality.is_russian_text(
        str(candidate.get("title") or "") + " "
        + str(candidate.get("source_text") or "")[:1600]
    )


def _rerun_semantic_gate(candidate, row):
    verdict = semantic_gate.deterministic_review(candidate, row)
    return (
        verdict.get("approved") is True
        and int(verdict.get("title_matches_source") or 0) >= 90
        and int(verdict.get("category_matches_story") or 0) >= 90
        and verdict.get("facts_supported") is True
        and verdict.get("meaning_changed") is False
    ), verdict


def valid_post_strict(candidate):
    decision = candidate.get("_quality_v12") or {}
    if decision.get("approved") is not True:
        core.b.STATS["quality_v12_final_rejected"] += 1
        return None

    candidate["_editorial_prechecked"] = False
    row = _VALID_POST(candidate)
    if not row:
        return None

    original_title = str(row.get("title_ru") or candidate.get("title") or "")
    final_title = (
        quality.sanitize_title(candidate.get("title"))
        if _is_russian_source(candidate)
        else quality.sanitize_title(original_title)
    )
    if final_title != original_title:
        core.b.STATS["quality_v12_title_repaired"] += 1
    row["title_ru"] = final_title
    row["category"] = candidate.get("category")
    row["footer"] = candidate.get("footer")

    semantic_ok, semantic = _rerun_semantic_gate(candidate, row)
    final_body = " ".join(
        str(value).strip() for value in (row.get("body") or []) if str(value).strip()
    )
    final_review = quality.review(
        candidate,
        title_override=final_title,
        body_override=(str(candidate.get("source_text") or "") + " " + final_body),
    )
    required_category = str(candidate.get("category_key") or "")
    final_ok = (
        semantic_ok
        and final_review.get("approved") is True
        and final_review.get("corrected_category") == required_category
        and int(final_review.get("score") or 0) >= int(final_review.get("threshold") or 100)
    )
    if not final_ok:
        core.b.STATS["quality_v12_final_rejected"] += 1
        core.b.log(
            "quality-v12 final reject: " + str(candidate.get("title") or "")[:100]
            + " | category=" + str(final_review.get("corrected_category"))
            + " expected=" + required_category
            + " reason=" + str(final_review.get("reason"))
            + " semantic=" + str(semantic.get("issues") or [])[:240]
        )
        return None

    compact = quality.compact(final_review)
    compact.update({
        "approved": True,
        "prepublication_checked": True,
        "final_title_checked": True,
        "final_category_checked": True,
        "semantic_gate_rechecked": True,
    })
    row["quality_v12"] = compact
    candidate["_quality_v12"] = compact
    candidate["_final_row_v12"] = copy.deepcopy(row)
    _DECISIONS[str(candidate.get("url") or "")] = compact
    _FINAL_ROWS[str(candidate.get("url") or "")] = copy.deepcopy(row)
    return row


core.b.valid_post = valid_post_strict


def save_state_strict(state):
    run = state.get("last_run") or {}
    published = int(run.get("published") or 0)
    posts = (state.get("last_posts") or [])[-published:] if published else []
    for post in posts:
        url = str(post.get("url") or "")
        decision = _DECISIONS.get(url)
        if decision:
            post["quality_v12"] = copy.deepcopy(decision)
        source = _SOURCE_ROWS.get(url) or {}
        if source:
            post["source_title"] = source.get("source_title")
            post["source_text_excerpt"] = source.get("source_text_excerpt")
        row = _FINAL_ROWS.get(url) or {}
        if row:
            post["title"] = row.get("title_ru") or post.get("title")
            post["final_body"] = list(row.get("body") or [])
            post["final_footer"] = row.get("footer")

    report = {key: value for key, value in _REPORT.items() if key != "by_url"}
    report["balance_after"] = quality.balance(state)
    run["version"] = VERSION
    run["quality_v12"] = report
    run["stats"] = dict(core.b.STATS)
    state["last_run"] = run
    state["quality_policy"] = {
        "version": quality.VERSION,
        "rolling_window": quality.ROLLING_WINDOW,
        "targets": dict(quality.TARGET_COUNTS),
        "percentages": {
            group: round(count * 100 / quality.ROLLING_WINDOW)
            for group, count in quality.TARGET_COUNTS.items()
        },
        "fail_closed": True,
        "post_publish_audit": True,
    }
    state["news_balance"] = report["balance_after"]
    _SAVE_STATE(state)


core.b.save_state = save_state_strict


def main():
    legacy.media.main()


if __name__ == "__main__":
    main()
