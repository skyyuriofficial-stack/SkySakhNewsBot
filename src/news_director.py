"""Strict autonomous news director for SkySakhNews.

The director is authoritative for newsworthiness, category autocorrection,
headline correction, repetition limits and the rolling thematic mix requested
for the channel.

Target mix over the last 20 valid publications:
- Sakhalin/local: 30% (6)
- Russia politics/laws: 20% (4)
- Russia economy/money: 20% (4)
- incidents/security: 15% (3)
- world/geopolitics/world about Russia: 10% (2)
- IT/AI/connectivity: 5% (1)
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import editorial_policy as policy

VERSION = "director-v2.1"
ROLLING_WINDOW = 20
TARGET_COUNTS: Dict[str, int] = {
    "local": 6,
    "ru_pol": 4,
    "ru_eco": 4,
    "ru_safety": 3,
    "world": 2,
    "it": 1,
}
TARGET_SHARES = {
    group: count / ROLLING_WINDOW for group, count in TARGET_COUNTS.items()
}

CATEGORY_GROUP = dict(policy.CATEGORY_GROUP)

MIN_SCORE = {
    "local": 68,
    "ru_pol": 75,
    "ru_eco": 74,
    "ru_safety": 76,
    "world": 78,
    "it": 78,
}

EVENT_BASE = {
    "earthquake": 94,
    "violent_crime": 90,
    "fatal_incident": 91,
    "military_security": 89,
    "major_emergency": 85,
    "missing_person": 78,
    "air_quality_hazard": 81,
    "public_service_disruption": 76,
    "major_infrastructure": 78,
    "severe_weather": 80,
    "ordinary_weather": 57,
    "fraud": 61,
    "traffic_enforcement": 43,
    "routine_crime": 55,
    "political_decision": 82,
    "political_statement": 64,
    "macro_economy": 78,
    "corporate_forecast": 68,
    "geopolitical_event": 82,
    "major_it": 80,
    "general": 48,
}

SUBTYPE_CAPS = {
    "fraud": 2,
    "traffic_enforcement": 0,
    "ordinary_weather": 1,
    "routine_crime": 1,
    "corporate_forecast": 1,
    "political_statement": 1,
    "major_infrastructure": 3,
}

URGENT_EVENTS = {
    "earthquake", "violent_crime", "fatal_incident", "military_security",
    "major_emergency", "severe_weather", "air_quality_hazard",
}

SOURCE_QUALITY = {
    "reuters": 6,
    "associated press": 6,
    "ap news": 6,
    "bbc": 5,
    "guardian": 5,
    "interfax": 5,
    "tass": 5,
    "тасс": 5,
    "sakhalinmedia": 4,
    "astv": 4,
    "sakh.online": 4,
    "sakh online": 4,
}

PUBLIC_SCALE = (
    "жителей", "населени", "тысяч человек", "муниципальн", "область",
    "регион", "несколько районов", "весь город", "всей страны",
)
MULTIPLE_VICTIMS = (
    "два человека", "три человека", "несколько человек", "массов", "десятки",
    "свыше 100", "более 100", "пятеро", "шестеро",
)
UNCERTAIN = (
    "предположительно", "по неподтвержденным данным", "по неподтверждённым данным",
    "возможно", "якобы", "по слухам",
)
PRESS_RELEASE_TONE = (
    "самые технологически продвинутые", "уникальный проект", "успешно реализован",
    "лидер рынка", "инновационное решение", "новый уровень комфорта",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    return policy.norm(value)


def _has(text: str, markers: Sequence[str]) -> bool:
    return policy.has_any(text, markers)


def group_for_category(category_key: Optional[str]) -> Optional[str]:
    return CATEGORY_GROUP.get(str(category_key or ""))


def _source_quality(source: str) -> int:
    low = _norm(source)
    return max(
        (score for marker, score in SOURCE_QUALITY.items() if marker in low),
        default=0,
    )


def _number_density(text: str) -> int:
    values = re.findall(r"\d+(?:[,.]\d+)?", text or "")
    return min(4, len(set(values)))


def _score_candidate(
    candidate: Mapping[str, Any],
    classification: policy.Classification,
) -> Tuple[int, List[str]]:
    title = policy.strip_source_suffix(candidate.get("title"))
    lead = _clean(candidate.get("source_text"))[:1800]
    combined = f"{title} {lead}"
    event = classification.event_type
    score = EVENT_BASE.get(event, 45)
    reasons = [f"event:{event}:{score}"]

    source_bonus = _source_quality(_clean(candidate.get("source")))
    if source_bonus:
        score += source_bonus
        reasons.append(f"source:+{source_bonus}")

    facts_bonus = _number_density(combined)
    if facts_bonus:
        score += facts_bonus
        reasons.append(f"concrete_facts:+{facts_bonus}")

    if _has(combined, PUBLIC_SCALE):
        score += 5
        reasons.append("public_scale:+5")
    if _has(combined, MULTIPLE_VICTIMS):
        score += 5
        reasons.append("multiple_people:+5")

    money = policy.parse_ruble_amount(combined)
    if event == "fraud":
        if money >= 10_000_000:
            score += 18
            reasons.append("fraud_10m_plus:+18")
        elif money >= 1_000_000:
            score += 13
            reasons.append("fraud_1m_plus:+13")
        elif money >= 500_000:
            score += 9
            reasons.append("fraud_500k_plus:+9")
        elif money >= 100_000:
            score += 5
            reasons.append("fraud_100k_plus:+5")
        elif money:
            score -= 4
            reasons.append("minor_fraud:-4")

    if event == "routine_crime" and money and money < 100_000:
        score -= 8
        reasons.append("minor_property_crime:-8")

    if _has(title, policy.CLICKBAIT):
        score -= 14
        reasons.append("clickbait:-14")
    if _has(combined, UNCERTAIN):
        score -= 5
        reasons.append("uncertain:-5")
    if _has(combined, PRESS_RELEASE_TONE):
        score -= 10
        reasons.append("press_release_tone:-10")

    # Hard upper bounds prevent routine filler from becoming '93/100' merely
    # because a long article contains official words, numbers and place names.
    caps = {
        "traffic_enforcement": 55,
        "ordinary_weather": 65,
        "routine_crime": 66,
        "political_statement": 72,
        "corporate_forecast": 78,
        "general": 58,
    }
    if event in caps:
        score = min(score, caps[event])
        reasons.append(f"event_cap:{caps[event]}")

    return max(0, min(100, int(score))), reasons


def review_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    classification = policy.classify(candidate)
    original_category = str(candidate.get("category_key") or "")
    original_title = policy.strip_source_suffix(candidate.get("title"))

    if classification.hard_reject_reason:
        return {
            "approved": False,
            "hard_reject": True,
            "reason": classification.hard_reject_reason,
            "original_category": original_category,
            "corrected_category": classification.category_key,
            "group": classification.group,
            "event_type": classification.event_type,
            "subtype": classification.event_type,
            "seriousness": 0,
            "threshold": 100,
            "risks": [classification.hard_reject_reason],
            "policy": classification.to_dict(),
            "title_original": original_title,
            "title_corrected": original_title,
            "title_corrections": [],
            "needs_ai_review": False,
        }

    corrected_title, corrections = policy.autocorrect_title(candidate, classification)
    title_issues = policy.title_quality_issues(corrected_title)
    if title_issues and classification.event_type not in {"traffic_enforcement"}:
        return {
            "approved": False,
            "hard_reject": True,
            "reason": "unsafe_or_malformed_headline",
            "original_category": original_category,
            "corrected_category": classification.category_key,
            "group": classification.group,
            "event_type": classification.event_type,
            "subtype": classification.event_type,
            "seriousness": 0,
            "threshold": 100,
            "risks": title_issues,
            "policy": classification.to_dict(),
            "title_original": original_title,
            "title_corrected": corrected_title,
            "title_corrections": corrections,
            "needs_ai_review": False,
        }

    category_key = classification.category_key
    group = classification.group
    if not category_key or not group:
        return {
            "approved": False,
            "hard_reject": True,
            "reason": "no_valid_news_stream",
            "original_category": original_category,
            "corrected_category": None,
            "group": None,
            "event_type": classification.event_type,
            "subtype": classification.event_type,
            "seriousness": 0,
            "threshold": 100,
            "risks": ["no_valid_news_stream"],
            "policy": classification.to_dict(),
            "title_original": original_title,
            "title_corrected": corrected_title,
            "title_corrections": corrections,
            "needs_ai_review": False,
        }

    score, score_reasons = _score_candidate(candidate, classification)
    threshold = MIN_SCORE[group]
    event = classification.event_type
    risks: List[str] = []

    if original_category != category_key:
        risks.append(f"category_corrected:{original_category or '-'}->{category_key}")
    if corrections:
        risks.extend(corrections)
    if event in {"fraud", "routine_crime", "traffic_enforcement", "ordinary_weather", "corporate_forecast", "political_statement"}:
        risks.append("low_value_or_repetitive_event_type")
    if score < threshold + 5:
        risks.append("near_threshold")

    reason = "approved" if score >= threshold else "importance_below_threshold"
    if event == "traffic_enforcement":
        reason = "routine_traffic_statistics"
    if event == "routine_crime" and score < threshold:
        reason = "minor_or_routine_crime"
    if event == "ordinary_weather" and score < threshold:
        reason = "ordinary_weather_not_release_worthy"
    if event == "political_statement" and score < threshold:
        reason = "statement_without_material_decision"

    return {
        "approved": score >= threshold,
        "hard_reject": False,
        "reason": reason,
        "original_category": original_category,
        "corrected_category": category_key,
        "group": group,
        "event_type": event,
        "subtype": event,
        "seriousness": score,
        "threshold": threshold,
        "risks": risks,
        "score_reasons": score_reasons,
        "policy": classification.to_dict(),
        "title_original": original_title,
        "title_corrected": corrected_title,
        "title_corrections": corrections,
        "needs_ai_review": False,
    }


def _post_review(post: Mapping[str, Any]) -> Dict[str, Any]:
    stored = post.get("news_director")
    if isinstance(stored, dict) and stored.get("version") == VERSION:
        return dict(stored)
    candidate = {
        "title": post.get("title"),
        "source_text": post.get("source_text_excerpt") or post.get("source_text") or "",
        "source": post.get("source"),
        "url": post.get("url"),
        "category_key": post.get("category_key"),
        "score": 0,
    }
    review = review_candidate(candidate)
    review["retrospective"] = True
    return review


def _scaled_targets(length: int) -> Dict[str, float]:
    n = max(0, min(ROLLING_WINDOW, int(length)))
    return {group: share * n for group, share in TARGET_SHARES.items()}


def _distribution_error(counts: Mapping[str, int], length: int) -> float:
    targets = _scaled_targets(length)
    return sum(abs(float(counts.get(group, 0)) - targets[group]) for group in TARGET_COUNTS)


def balance_snapshot(state: Mapping[str, Any], *, window: int = ROLLING_WINDOW) -> Dict[str, Any]:
    posts = [
        post for post in (state.get("last_posts") or [])
        if isinstance(post, dict) and not post.get("auto_deleted")
    ][-window:]
    sequence: List[str] = []
    category_sequence: List[str] = []
    source_sequence: List[str] = []
    subtype_counts: Counter[str] = Counter()
    anomalies: List[Dict[str, Any]] = []

    for post in posts:
        review = _post_review(post)
        if not review.get("approved"):
            anomalies.append({
                "title": _clean(post.get("title"))[:180],
                "category_key": post.get("category_key"),
                "reason": review.get("reason"),
                "corrected_category": review.get("corrected_category"),
            })
            continue
        group = review.get("group") or group_for_category(
            review.get("corrected_category") or post.get("category_key")
        )
        if not group:
            continue
        sequence.append(str(group))
        category_sequence.append(str(review.get("corrected_category") or post.get("category_key") or ""))
        source_sequence.append(_norm(post.get("source")))
        subtype_counts[str(review.get("event_type") or review.get("subtype") or "general")] += 1

    sequence = sequence[-window:]
    category_sequence = category_sequence[-window:]
    source_sequence = source_sequence[-window:]
    counts = Counter(sequence)
    full_targets = dict(TARGET_COUNTS)
    scaled = _scaled_targets(len(sequence))

    return {
        "window": window,
        "targets": full_targets,
        "target_percent": {
            group: round(100 * count / window, 1) for group, count in full_targets.items()
        },
        "counts": {group: counts.get(group, 0) for group in full_targets},
        "scaled_targets": {group: round(value, 2) for group, value in scaled.items()},
        "deficits": {
            group: round(scaled[group] - counts.get(group, 0), 2) for group in full_targets
        },
        "distribution_error": round(_distribution_error(counts, len(sequence)), 3),
        "subtype_counts": dict(subtype_counts),
        "sequence": sequence,
        "category_sequence": category_sequence,
        "source_sequence": source_sequence,
        "retrospective_anomalies": anomalies[-20:],
        "valid_posts_counted": len(sequence),
    }


def _candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    return str(candidate.get("url") or candidate.get("title_hash") or f"candidate-{index}")


def ai_review_prompt(reviews: Sequence[Mapping[str, Any]]) -> str:
    # Kept for API compatibility. The deterministic director is authoritative;
    # OpenRouter is not required to release a Russian-language article.
    items = []
    for review in reviews[:8]:
        candidate = review["_candidate"]
        items.append({
            "id": review["id"],
            "title": candidate.get("title"),
            "source": candidate.get("source"),
            "category": review.get("corrected_category"),
            "score": review.get("seriousness"),
        })
    return (
        "Проверь неоднозначные кандидаты. Верни только JSON "
        '{"reviews":[{"id":"...","newsworthy":true,"importance":0,'
        '"corrected_category":"sakh|sakh_chp|sakh_quake|world_ru|ru_security|'
        'ru_incident|ru_pol|ru_eco|geo|it|null","reason":"..."}]}.\n'
        + json.dumps({"items": items}, ensure_ascii=False)
    )


def normalize_ai_reviews(value: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("reviews"), list):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    allowed = set(CATEGORY_GROUP)
    for row in value["reviews"][:12]:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        category = row.get("corrected_category")
        if category not in allowed:
            category = None
        try:
            importance = int(row.get("importance") or 0)
        except (TypeError, ValueError):
            importance = 0
        result[str(row["id"])] = {
            "newsworthy": row.get("newsworthy") is True,
            "importance": max(0, min(100, importance)),
            "corrected_category": category,
            "reason": _clean(row.get("reason"))[:220],
        }
    return result


def _apply_ai_review(review: Dict[str, Any], ai: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    # AI may veto a borderline item, but can never revive a deterministic reject
    # or move it to another thematic group.
    if review.get("hard_reject") or not review.get("approved") or ai is None:
        return review
    review["ai_review"] = dict(ai)
    if not ai.get("newsworthy") or int(ai.get("importance") or 0) < 70:
        review["approved"] = False
        review["reason"] = "independent_editor_veto"
        return review
    suggested = ai.get("corrected_category")
    if suggested and group_for_category(suggested) == review.get("group"):
        review["corrected_category"] = suggested
    return review


def _projected_mix(
    balance: Mapping[str, Any],
    selected_groups: Sequence[str],
    next_group: str,
) -> Tuple[float, Dict[str, int], int]:
    sequence = list(balance.get("sequence") or [])
    sequence.extend(selected_groups)
    sequence.append(next_group)
    sequence = sequence[-ROLLING_WINDOW:]
    counts = Counter(sequence)
    return _distribution_error(counts, len(sequence)), dict(counts), len(sequence)


def _utility(
    candidate: Mapping[str, Any],
    review: Mapping[str, Any],
    balance: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
) -> float:
    group = str(review.get("group") or "")
    selected_groups = [str((item.get("_news_director") or {}).get("group") or "") for item in selected]
    before_counts = Counter(list(balance.get("sequence") or []) + selected_groups)
    before_length = min(ROLLING_WINDOW, len(balance.get("sequence") or []) + len(selected_groups))
    before_error = _distribution_error(before_counts, before_length)
    after_error, _, _ = _projected_mix(balance, selected_groups, group)
    mix_gain = before_error - after_error

    utility = float(review.get("seriousness") or 0) + 18.0 * mix_gain

    if selected:
        selected_sources = {_norm(item.get("source")) for item in selected}
        selected_subtypes = {
            str((item.get("_news_director") or {}).get("event_type") or "") for item in selected
        }
        selected_categories = {
            str(item.get("category_key") or "") for item in selected
        }
        current_sequence = (
            list(balance.get("sequence") or []) + selected_groups
        )[-ROLLING_WINDOW:]
        current_counts = Counter(current_sequence)
        current_target = _scaled_targets(len(current_sequence)).get(group, 0.0)
        group_under_target = current_counts.get(group, 0) < current_target

        if _norm(candidate.get("source")) in selected_sources:
            utility -= 18
        if group in selected_groups and not group_under_target:
            utility -= 16
        if (
            str(review.get("event_type") or "") in selected_subtypes
            and not (
                group_under_target
                and str(candidate.get("category_key") or "") not in selected_categories
            )
        ):
            utility -= 14

    recent_sources = list(balance.get("source_sequence") or [])[-4:]
    if recent_sources and _norm(candidate.get("source")) == recent_sources[-1]:
        utility -= 7
    if candidate.get("_pending_delivery"):
        utility += 6
    return utility


def _apply_repetition_cap(
    review: Dict[str, Any],
    balance: Mapping[str, Any],
) -> Dict[str, Any]:
    event = str(review.get("event_type") or "")
    cap = SUBTYPE_CAPS.get(event)
    if cap is None or not review.get("approved"):
        return review
    recent = int((balance.get("subtype_counts") or {}).get(event, 0))
    if recent >= cap and event not in URGENT_EVENTS:
        review["approved"] = False
        review["reason"] = "event_quota_exhausted"
        review.setdefault("risks", []).append(f"event_cap:{event}:{recent}/{cap}")
    return review


def direct_candidates(
    state: Mapping[str, Any],
    candidates: Sequence[Dict[str, Any]],
    *,
    category_map: Mapping[str, Tuple[str, str]],
    now: Optional[datetime] = None,
    ai_reviewer: Optional[
        Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Mapping[str, Any]]]
    ] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    balance = balance_snapshot(state)
    reviews: List[Dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        review = review_candidate(candidate)
        review["id"] = _candidate_id(candidate, index)
        review["_candidate"] = candidate
        reviews.append(review)

    ambiguous = [
        review for review in reviews
        if review.get("approved") and review.get("needs_ai_review")
    ][:8]
    ai_results: Mapping[str, Mapping[str, Any]] = {}
    if ambiguous and ai_reviewer is not None:
        try:
            ai_results = ai_reviewer(ambiguous) or {}
        except Exception:
            ai_results = {}

    approved: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    by_url: Dict[str, Dict[str, Any]] = {}

    for review in reviews:
        review = _apply_ai_review(review, ai_results.get(review["id"]))
        review = _apply_repetition_cap(review, balance)
        candidate = review.pop("_candidate")
        review["version"] = VERSION
        category_key = review.get("corrected_category")

        if review.get("approved") and category_key in category_map:
            old_category = str(candidate.get("category_key") or "")
            old_title = policy.strip_source_suffix(candidate.get("title"))
            new_title = str(review.get("title_corrected") or old_title)

            if old_category != category_key:
                candidate["_news_director_reclass"] = (old_category, category_key)
                candidate["category_key"] = category_key
                candidate["category"], candidate["footer"] = category_map[category_key]
                candidate["_editorial_prechecked"] = False
                if candidate.get("topic_cluster"):
                    candidate["topic_cluster"] = category_key + ":" + str(candidate["topic_cluster"]).split(":", 1)[-1]

            if new_title and new_title != old_title:
                candidate["title_original"] = old_title
                candidate["title"] = new_title
                candidate["title_hash"] = hashlib.sha1(policy.norm(new_title).encode("utf-8")).hexdigest()
                candidate["_editorial_prechecked"] = False
                review["title_changed"] = True
            else:
                candidate["title"] = old_title
                review["title_changed"] = False

            candidate["_news_director"] = review
            approved.append(candidate)
        else:
            review["approved"] = False
            candidate["_news_director"] = review
            rejected.append(candidate)

        by_url[str(candidate.get("url") or review["id"])] = dict(review)

    # Greedy two-slot optimizer: significance remains dominant, while the
    # rolling 30/20/20/15/10/5 mix and source/topic diversity correct the feed.
    selected: List[Dict[str, Any]] = []
    remaining = list(approved)
    while remaining and len(selected) < 2:
        candidate_pool = list(remaining)
        if selected:
            first_group = str(
                (selected[0].get("_news_director") or {}).get("group") or ""
            )
            group_diverse = [
                item for item in remaining
                if str((item.get("_news_director") or {}).get("group") or "")
                != first_group
            ]
            if group_diverse:
                candidate_pool = group_diverse

            selected_sources = {
                _norm(item.get("source")) for item in selected
            }
            source_diverse = [
                item for item in candidate_pool
                if _norm(item.get("source")) not in selected_sources
            ]
            if source_diverse:
                candidate_pool = source_diverse

        scored = [
            (
                _utility(item, item.get("_news_director") or {}, balance, selected),
                int((item.get("_news_director") or {}).get("seriousness") or 0),
                item,
            )
            for item in candidate_pool
        ]
        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        chosen = scored[0][2]
        review = chosen["_news_director"]
        review["selection_utility"] = round(scored[0][0], 3)
        review["slot"] = len(selected) + 1
        selected.append(chosen)
        remaining.remove(chosen)

    # Backups are ordered by the same utility after the selected contract. The
    # lower publisher can skip a failed item and still preserve the target mix.
    backup_scored = [
        (
            _utility(item, item.get("_news_director") or {}, balance, selected),
            int((item.get("_news_director") or {}).get("seriousness") or 0),
            item,
        )
        for item in remaining
    ]
    backup_scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
    ordered = selected + [item for _, _, item in backup_scored]

    for position, item in enumerate(ordered):
        review = item["_news_director"]
        if position >= len(selected):
            review["slot"] = "backup"
            review["selection_utility"] = round(
                next(value[0] for value in backup_scored if value[2] is item), 3
            )
        item["_news_director_order"] = position

    rejected_by_reason = Counter(
        str((item.get("_news_director") or {}).get("reason") or "unknown")
        for item in rejected
    )

    projected_groups = [
        str((item.get("_news_director") or {}).get("group") or "")
        for item in selected
    ]
    after_error, after_counts, after_length = (
        _projected_mix(balance, projected_groups[:-1], projected_groups[-1])
        if projected_groups else (
            float(balance.get("distribution_error") or 0),
            dict(balance.get("counts") or {}),
            int(balance.get("valid_posts_counted") or 0),
        )
    )

    report = {
        "version": VERSION,
        "policy_version": policy.VERSION,
        "mix_policy": "rolling_20_target_optimizer",
        "rolling_balance_before": balance,
        "candidate_count": len(candidates),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "rejected_by_reason": dict(rejected_by_reason),
        "ai_review_requested": len(ambiguous),
        "ai_review_received": len(ai_results),
        "selected_groups": projected_groups,
        "projected_distribution_error": round(after_error, 3),
        "projected_counts": after_counts,
        "projected_length": after_length,
        "selected_preview": [
            {
                "slot": (item.get("_news_director") or {}).get("slot"),
                "title": _clean(item.get("title"))[:180],
                "category_key": item.get("category_key"),
                "group": (item.get("_news_director") or {}).get("group"),
                "event_type": (item.get("_news_director") or {}).get("event_type"),
                "seriousness": (item.get("_news_director") or {}).get("seriousness"),
                "utility": (item.get("_news_director") or {}).get("selection_utility"),
            }
            for item in ordered[:10]
        ],
        "by_url": by_url,
    }
    return ordered, report


def validate_final(candidate: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
    contract = policy.final_contract(candidate, row)
    review = review_candidate({
        **dict(candidate),
        "title": row.get("title_ru") or candidate.get("title"),
        "source_text": " ".join(
            _clean(value) for value in (row.get("body") or []) if _clean(value)
        ) or candidate.get("source_text"),
        "category_key": candidate.get("category_key"),
    })
    if review.get("corrected_category") != candidate.get("category_key"):
        contract["issues"].append(
            f"director_final_category:{review.get('corrected_category')}->{candidate.get('category_key')}"
        )
    if not review.get("approved"):
        contract["issues"].append("director_final_reject:" + str(review.get("reason")))
    contract["approved"] = not contract["issues"]
    contract["director_review"] = compact_review(review)
    return contract


def compact_review(review: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "version": review.get("version") or VERSION,
        "approved": bool(review.get("approved")),
        "reason": review.get("reason"),
        "original_category": review.get("original_category"),
        "corrected_category": review.get("corrected_category"),
        "group": review.get("group"),
        "event_type": review.get("event_type") or review.get("subtype"),
        "subtype": review.get("event_type") or review.get("subtype"),
        "seriousness": int(review.get("seriousness") or 0),
        "threshold": int(review.get("threshold") or 0),
        "selection_utility": review.get("selection_utility"),
        "slot": review.get("slot"),
        "risks": [str(value)[:180] for value in (review.get("risks") or [])[:10]],
        "title_original": review.get("title_original"),
        "title_corrected": review.get("title_corrected"),
        "title_corrections": list(review.get("title_corrections") or [])[:8],
        "title_changed": bool(review.get("title_changed")),
        "ai_review": review.get("ai_review"),
    }


def finalize_report(state: Mapping[str, Any], report: Mapping[str, Any]) -> Dict[str, Any]:
    result = {key: value for key, value in report.items() if key != "by_url"}
    result["rolling_balance_after"] = balance_snapshot(state)
    return result
