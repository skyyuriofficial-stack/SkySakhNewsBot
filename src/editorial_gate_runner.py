"""Canonical SkySakhNews production runner with mandatory editorial verification."""

from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, Optional

import category_reconciler as reconciler
import editorial_gate as gate
import production as prod

VERSION = "stable-v10.2"
prod.VERSION = VERSION
prod.core.VERSION = VERSION
core = prod.core

AI_AUDIT_BUDGET = max(0, int(os.getenv("EDITORIAL_AUDIT_AI_BUDGET", "2")))
_AI_AUDIT_CALLS = 0
AUDIT_BY_URL: Dict[str, Dict[str, Any]] = {}

for key in (
    "editorial_prechecked",
    "editorial_gate_checked",
    "editorial_gate_pass",
    "editorial_gate_reject",
    "editorial_gate_fallback",
    "editorial_gate_ai_calls",
    "editorial_gate_ai_fail",
    "editorial_title_reject",
    "editorial_category_reject",
    "editorial_meaning_reject",
    "editorial_reclassified",
    "editorial_offtopic_reject",
    "openrouter_empty_content",
    "openrouter_model_fallback",
    "openrouter_attempts",
    "openrouter_retries",
    "openrouter_invalid_json",
    "openrouter_success",
    "openrouter_circuit_open",
):
    core.b.STATS.setdefault(key, 0)


def _message_text(message: Any) -> Optional[str]:
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    pieces.append(text.strip())
            elif isinstance(item, str) and item.strip():
                pieces.append(item.strip())
        if pieces:
            return "\n".join(pieces)
    return None


_OPENROUTER_CIRCUIT_OPEN = False
_OPENROUTER_CIRCUIT_REASON = ""


def _openrouter_model_plan():
    "Build a bounded plan without silently switching to a paid model."
    raw_primary = os.getenv("OPENROUTER_MODEL", "").strip()
    raw_fallbacks = os.getenv("OPENROUTER_FALLBACK_MODELS", "").strip()
    configured = [
        value.strip()
        for value in (raw_primary + "," + raw_fallbacks).split(",")
        if value.strip()
    ]
    try:
        max_attempts = int(os.getenv("OPENROUTER_MAX_ATTEMPTS", "3"))
    except ValueError:
        max_attempts = 3
    max_attempts = max(1, min(6, max_attempts))

    plan = []
    for model in configured:
        if model not in plan:
            plan.append(model)
    if not plan:
        plan.append("openrouter/free")

    # Repeated calls to openrouter/free are intentional: every request can be
    # routed to a different currently available free model.
    while len(plan) < max_attempts:
        plan.append("openrouter/free")
    return plan[:max_attempts]


def _retry_delay_seconds(response, attempt):
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, min(15.0, float(retry_after)))
        except (TypeError, ValueError):
            pass

    try:
        base = float(os.getenv("OPENROUTER_RETRY_BASE_SECONDS", "1.0"))
    except ValueError:
        base = 1.0
    base = max(0.0, min(5.0, base))
    jitter = 0.0 if base == 0 else random.uniform(0.0, min(0.35, base / 2))
    return min(12.0, base * (2 ** attempt) + jitter)


def _is_json_object(text):
    try:
        return isinstance(core.b.parse_obj(text), dict)
    except Exception:
        return False


def resilient_openrouter(messages, max_tokens=1100):
    global _OPENROUTER_CIRCUIT_OPEN, _OPENROUTER_CIRCUIT_REASON

    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    if _OPENROUTER_CIRCUIT_OPEN:
        raise RuntimeError(
            "OpenRouter circuit is open for this run: "
            + (_OPENROUTER_CIRCUIT_REASON or "previous attempts failed")
        )

    plan = _openrouter_model_plan()
    errors = []

    for attempt, model in enumerate(plan):
        core.b.STATS["openrouter_attempts"] += 1
        response = None
        stop_immediately = False

        try:
            response = core.b.requests.post(
                core.b.OPENROUTER_URL,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://t.me/SkySakhNews",
                    "X-OpenRouter-Title": "SkySakhNews",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                    "provider": {
                        "require_parameters": True,
                        "allow_fallbacks": True,
                    },
                },
                timeout=90,
            )

            if response.status_code >= 400:
                detail = (response.text or "")[:300]
                errors.append(f"{model}: HTTP {response.status_code}: {detail}")
                if response.status_code in {401, 403}:
                    stop_immediately = True
            else:
                payload = response.json()
                if not isinstance(payload, dict):
                    errors.append(f"{model}: response is not an object")
                elif payload.get("error"):
                    errors.append(f"{model}: API error: {str(payload.get('error'))[:300]}")
                else:
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        errors.append(f"{model}: missing choices")
                    else:
                        first = choices[0] if isinstance(choices[0], dict) else {}
                        text = _message_text(first.get("message"))
                        if not text:
                            alternative = first.get("text")
                            if isinstance(alternative, str) and alternative.strip():
                                text = alternative.strip()

                        if not text:
                            core.b.STATS["openrouter_empty_content"] += 1
                            errors.append(f"{model}: empty message content")
                        elif not _is_json_object(text):
                            core.b.STATS["openrouter_invalid_json"] += 1
                            errors.append(f"{model}: invalid JSON object")
                        else:
                            used_model = str(payload.get("model") or model)
                            core.b.STATS["openrouter_success"] += 1
                            if attempt > 0:
                                core.b.STATS["openrouter_model_fallback"] += 1
                            core.b.log(
                                "OpenRouter JSON accepted: "
                                f"{used_model} (attempt {attempt + 1}/{len(plan)})"
                            )
                            return text
        except Exception as exc:
            errors.append(
                f"{model}: {type(exc).__name__}: {str(exc)[:300]}"
            )

        if stop_immediately:
            break
        if attempt + 1 < len(plan):
            core.b.STATS["openrouter_retries"] += 1
            delay = _retry_delay_seconds(response, attempt)
            if delay > 0:
                time.sleep(delay)

    _OPENROUTER_CIRCUIT_OPEN = True
    _OPENROUTER_CIRCUIT_REASON = " | ".join(errors[-4:]) or "unknown failure"
    core.b.STATS["openrouter_circuit_open"] = 1
    raise RuntimeError("OpenRouter failed: " + _OPENROUTER_CIRCUIT_REASON)


core.b.openrouter = resilient_openrouter


def _independent_ai_review(candidate, row):
    global _AI_AUDIT_CALLS
    if _AI_AUDIT_CALLS >= AI_AUDIT_BUDGET:
        return None

    _AI_AUDIT_CALLS += 1
    core.b.STATS["editorial_gate_ai_calls"] = _AI_AUDIT_CALLS
    try:
        raw = core.b.openrouter(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты независимый выпускающий редактор и фактчекер. "
                        "Не переписывай материал. Проверяй максимально строго. Только JSON."
                    ),
                },
                {"role": "user", "content": gate.ai_review_prompt(candidate, row)},
            ],
            max_tokens=500,
        )
        verdict = gate.normalize_ai_verdict(core.b.parse_obj(raw))
        if verdict is None:
            raise ValueError("invalid editorial verdict")
        return verdict
    except Exception as exc:
        core.b.STATS["editorial_gate_ai_fail"] += 1
        core.b.log(f"editorial AI review unavailable: {str(exc)[:240]}")
        return None


def _compact_audit(review, candidate=None):
    result = {
        "approved": bool(review.get("approved")),
        "title_matches_source": int(review.get("title_matches_source") or 0),
        "category_matches_story": int(review.get("category_matches_story") or 0),
        "facts_supported": bool(review.get("facts_supported")),
        "meaning_changed": bool(review.get("meaning_changed")),
        "mode": review.get("mode"),
        "issues": [str(value)[:180] for value in (review.get("issues") or [])[:10]],
    }
    if candidate and candidate.get("_editorial_reclass"):
        result["reclassified_from"], result["reclassified_to"] = candidate["_editorial_reclass"]
    return result


def _record_reject(review):
    core.b.STATS["editorial_gate_reject"] += 1
    issues = [str(value) for value in (review.get("issues") or [])]
    if (
        int(review.get("title_matches_source") or 0) < 90
        or any("title_" in value or "headline_" in value for value in issues)
    ):
        core.b.STATS["editorial_title_reject"] += 1
    if (
        int(review.get("category_matches_story") or 0) < 90
        or any(
            "category" in value
            or "mislabeled" in value
            or "foreign_story" in value
            for value in issues
        )
    ):
        core.b.STATS["editorial_category_reject"] += 1
    if review.get("meaning_changed") or any("modality" in value for value in issues):
        core.b.STATS["editorial_meaning_reject"] += 1


def _review(candidate, row):
    deterministic = gate.deterministic_review(candidate, row)
    hard = [
        issue
        for issue in deterministic.get("issues", [])
        if not str(issue).startswith("title_category_weak:")
    ]
    if hard or int(deterministic.get("category_matches_story") or 0) < 70:
        deterministic["approved"] = False
        return deterministic

    deterministic_pass = (
        bool(deterministic.get("approved"))
        and int(deterministic.get("title_matches_source") or 0) >= 90
        and int(deterministic.get("category_matches_story") or 0) >= 90
        and deterministic.get("facts_supported") is True
        and deterministic.get("meaning_changed") is False
    )

    # An exact Russian extract contains no LLM paraphrase to audit. If every
    # deterministic invariant already passes, an external model adds latency
    # and failure risk without adding factual protection.
    if (
        row.get("editorial_mode") == "extractive_fallback"
        and deterministic.get("source_is_russian") is True
        and deterministic_pass
    ):
        deterministic["approved"] = True
        deterministic["requires_ai_review"] = False
        deterministic["mode"] = "deterministic+extractive"
        return deterministic

    if not deterministic.get("requires_ai_review"):
        deterministic["approved"] = deterministic_pass
        return deterministic

    merged = gate.merge_reviews(deterministic, _independent_ai_review(candidate, row))
    merged["approved"] = (
        bool(merged.get("approved"))
        and int(merged.get("title_matches_source") or 0) >= 90
        and int(merged.get("category_matches_story") or 0) >= 90
        and merged.get("facts_supported") is True
        and merged.get("meaning_changed") is False
    )
    return merged


def _reconcile_category(candidate):
    old = str(candidate.get("category_key") or "")
    suggested = reconciler.suggest_category(candidate)

    if suggested is None:
        core.b.STATS["editorial_offtopic_reject"] += 1
        core.b.log("editorial category reconcile -> off-topic: " + candidate.get("title", "")[:90])
        return False

    if suggested not in core.b.CAT:
        core.b.log(f"editorial category reconcile unknown {suggested}: " + candidate.get("title", "")[:90])
        return False

    if suggested != old:
        candidate["_editorial_reclass"] = (old, suggested)
        candidate["category_key"] = suggested
        candidate["category"], candidate["footer"] = core.b.CAT[suggested]
        if candidate.get("topic_cluster"):
            candidate["topic_cluster"] = suggested + ":" + str(candidate["topic_cluster"]).split(":", 1)[-1]
        core.b.STATS["editorial_reclassified"] += 1
        core.b.log(f"editorial reclassify {old or '-'} -> {suggested}: " + candidate.get("title", "")[:90])
    return True


def _source_precheck(candidate):
    row = {
        "title_ru": prod._display_title(candidate),
        "body": [],
        "editorial_mode": "extractive_fallback",
    }
    review = gate.deterministic_review(candidate, row)
    bad = (
        int(review.get("category_matches_story") or 0) < 90
        or review.get("meaning_changed")
        or any(
            str(issue).startswith(("category_", "weather_mislabeled", "world_ru_without", "foreign_story", "headline_"))
            for issue in (review.get("issues") or [])
        )
    )
    if bad:
        review["approved"] = False
        _record_reject(review)
        AUDIT_BY_URL[candidate.get("url")] = _compact_audit(review, candidate)
        core.b.log(
            "editorial pre-gate reject: "
            + candidate.get("title", "")[:90]
            + " | "
            + "; ".join(str(value) for value in review.get("issues", [])[:6])
        )
        return False

    candidate["_editorial_prechecked"] = True
    return True


_original_collect = core.b.collect


def collect_reconciled(state):
    raw = _original_collect(state)
    result = []
    for candidate in raw:
        core.b.STATS["editorial_prechecked"] += 1
        if not _reconcile_category(candidate):
            continue
        if not _source_precheck(candidate):
            continue
        result.append(candidate)
    core.b.STATS["candidates"] = len(result)
    return result


core.b.collect = collect_reconciled


def ordered_semantic(candidates):
    local_keys = {"sakh", "sakh_chp", "sakh_quake"}
    local = [candidate for candidate in candidates if candidate.get("category_key") in local_keys]
    other = [candidate for candidate in candidates if candidate not in local]
    result = []

    if local:
        result.append(local[0])

    for key in ("world_ru", "ru_security", "ru_incident", "ru_pol", "ru_eco", "geo", "it"):
        result.extend(
            candidate
            for candidate in other
            if candidate.get("category_key") == key and candidate not in result
        )

    result.extend(candidate for candidate in local[1:] if candidate not in result)
    result.extend(candidate for candidate in other if candidate not in result)
    return result


core.b.ordered = ordered_semantic


_original_valid_post = core.b.valid_post


def valid_post_with_editorial_gate(candidate):
    core.b.STATS["editorial_gate_checked"] += 1

    if not candidate.get("_editorial_prechecked"):
        if not _reconcile_category(candidate) or not _source_precheck(candidate):
            return None

    row = _original_valid_post(candidate)
    if not row:
        return None

    review = _review(candidate, row)
    if review.get("approved"):
        core.b.STATS["editorial_gate_pass"] += 1
        row["editorial_gate"] = _compact_audit(review, candidate)
        AUDIT_BY_URL[candidate.get("url")] = row["editorial_gate"]
        return row

    _record_reject(review)
    core.b.log(
        "editorial gate reject: "
        + candidate.get("title", "")[:90]
        + " | "
        + "; ".join(str(value) for value in (review.get("issues") or [])[:6])
    )

    fallback = prod._extractive_fallback(candidate)
    if fallback:
        fallback_review = _review(candidate, fallback)
        if fallback_review.get("approved"):
            core.b.STATS["editorial_gate_fallback"] += 1
            core.b.STATS["editorial_gate_pass"] += 1
            fallback["editorial_gate"] = _compact_audit(fallback_review, candidate)
            AUDIT_BY_URL[candidate.get("url")] = fallback["editorial_gate"]
            core.b.log("editorial gate -> extractive fallback: " + candidate.get("title", "")[:90])
            return fallback

    AUDIT_BY_URL[candidate.get("url")] = _compact_audit(review, candidate)
    core.b.STATS["editorial_skip"] += 1
    return None


core.b.valid_post = valid_post_with_editorial_gate


_original_save_state = core.b.save_state


def save_state_with_editorial_audit(state):
    for post in state.get("last_posts", [])[-20:]:
        url = post.get("url")
        if url in AUDIT_BY_URL:
            post["editorial_gate"] = AUDIT_BY_URL[url]

    run = state.get("last_run") or {}
    run["version"] = VERSION
    run["editorial_gate"] = {
        "prechecked": int(core.b.STATS.get("editorial_prechecked", 0)),
        "checked": int(core.b.STATS.get("editorial_gate_checked", 0)),
        "passed": int(core.b.STATS.get("editorial_gate_pass", 0)),
        "rejected": int(core.b.STATS.get("editorial_gate_reject", 0)),
        "reclassified": int(core.b.STATS.get("editorial_reclassified", 0)),
        "offtopic_reject": int(core.b.STATS.get("editorial_offtopic_reject", 0)),
        "fallback": int(core.b.STATS.get("editorial_gate_fallback", 0)),
        "ai_calls": int(core.b.STATS.get("editorial_gate_ai_calls", 0)),
        "ai_fail": int(core.b.STATS.get("editorial_gate_ai_fail", 0)),
        "audited_urls": len(AUDIT_BY_URL),
    }
    run["stats"] = dict(core.b.STATS)
    state["last_run"] = run
    _original_save_state(state)


core.b.save_state = save_state_with_editorial_audit


def main():
    prod.main()


if __name__ == "__main__":
    main()
