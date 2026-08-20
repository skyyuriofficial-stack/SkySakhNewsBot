"""Canonical production runner with mandatory editorial verification gate."""

import os

import editorial_gate as gate
import category_reconciler as reconciler
import production as prod

VERSION = "stable-v10.1"
prod.VERSION = VERSION
prod.core.VERSION = VERSION
core = prod.core

gate.RUSSIA = gate.RUSSIA + ("russia", "russian", "moscow", "kremlin", "putin", "lavrov")
gate.FOREIGN = gate.FOREIGN + ("reuters", "bbc", "guardian", "associated press", " ap ")

AI_AUDIT_BUDGET = max(0, int(os.getenv("EDITORIAL_AUDIT_AI_BUDGET", "4")))
_AI_AUDIT_CALLS = 0
AUDIT_BY_URL = {}

for _key in (
    "editorial_prechecked", "editorial_gate_checked", "editorial_gate_pass",
    "editorial_gate_reject", "editorial_gate_fallback", "editorial_gate_ai_calls",
    "editorial_gate_ai_fail", "editorial_title_reject", "editorial_category_reject",
    "editorial_meaning_reject", "editorial_reclassified", "editorial_offtopic_reject",
):
    core.b.STATS.setdefault(_key, 0)


def _independent_ai_review(candidate, row):
    global _AI_AUDIT_CALLS
    if _AI_AUDIT_CALLS >= AI_AUDIT_BUDGET:
        return None
    _AI_AUDIT_CALLS += 1
    core.b.STATS["editorial_gate_ai_calls"] = _AI_AUDIT_CALLS
    try:
        raw = core.b.openrouter([
            {"role": "system", "content": "Ты независимый выпускающий редактор и фактчекер. Не переписывай материал. Проверяй максимально строго. Только JSON."},
            {"role": "user", "content": gate.ai_review_prompt(candidate, row)},
        ], max_tokens=500)
        verdict = gate.normalize_ai_verdict(core.b.parse_obj(raw))
        if verdict is None:
            raise ValueError("invalid editorial verdict")
        return verdict
    except Exception as ex:
        core.b.STATS["editorial_gate_ai_fail"] += 1
        core.b.log(f"editorial AI review unavailable: {str(ex)[:240]}")
        return None


def _compact_audit(review, candidate=None):
    out = {
        "approved": bool(review.get("approved")),
        "title_matches_source": int(review.get("title_matches_source") or 0),
        "category_matches_story": int(review.get("category_matches_story") or 0),
        "facts_supported": bool(review.get("facts_supported")),
        "meaning_changed": bool(review.get("meaning_changed")),
        "mode": review.get("mode"),
        "issues": [str(x)[:160] for x in (review.get("issues") or [])[:8]],
    }
    if candidate and candidate.get("_editorial_reclass"):
        out["reclassified_from"], out["reclassified_to"] = candidate["_editorial_reclass"]
    return out


def _record_reject(review):
    core.b.STATS["editorial_gate_reject"] += 1
    issues = [str(x) for x in (review.get("issues") or [])]
    if int(review.get("title_matches_source") or 0) < 90 or any("title_" in x for x in issues):
        core.b.STATS["editorial_title_reject"] += 1
    if int(review.get("category_matches_story") or 0) < 90 or any(
        "category" in x or "mislabeled" in x or "foreign_story" in x for x in issues
    ):
        core.b.STATS["editorial_category_reject"] += 1
    if review.get("meaning_changed") or any("modality" in x for x in issues):
        core.b.STATS["editorial_meaning_reject"] += 1


def _review(candidate, row):
    det = gate.deterministic_review(candidate, row)
    hard = [x for x in det.get("issues", []) if not str(x).startswith("title_category_weak:")]
    if hard or int(det.get("category_matches_story") or 0) < 70:
        det["approved"] = False
        return det
    if not det.get("requires_ai_review"):
        det["approved"] = (
            bool(det.get("approved"))
            and int(det.get("title_matches_source") or 0) >= 90
            and int(det.get("category_matches_story") or 0) >= 90
            and det.get("facts_supported") is True
            and det.get("meaning_changed") is False
        )
        return det
    merged = gate.merge_reviews(det, _independent_ai_review(candidate, row))
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
        core.b.log(f"editorial category reconcile -> off-topic: {candidate.get('title','')[:90]}")
        return False
    if suggested not in core.b.CAT:
        core.b.log(f"editorial category reconcile unknown {suggested}: {candidate.get('title','')[:90]}")
        return False
    if suggested != old:
        candidate["_editorial_reclass"] = (old, suggested)
        candidate["category_key"] = suggested
        candidate["category"], candidate["footer"] = core.b.CAT[suggested]
        if candidate.get("topic_cluster"):
            candidate["topic_cluster"] = suggested + ":" + str(candidate["topic_cluster"]).split(":", 1)[-1]
        core.b.STATS["editorial_reclassified"] += 1
        core.b.log(f"editorial reclassify {old or '-'} -> {suggested}: {candidate.get('title','')[:90]}")
    return True


def _source_precheck(candidate):
    row = {"title_ru": prod._display_title(candidate), "body": [], "editorial_mode": "extractive_fallback"}
    review = gate.deterministic_review(candidate, row)
    bad = (
        int(review.get("category_matches_story") or 0) < 90
        or review.get("meaning_changed")
        or any(str(x).startswith((
            "category_", "weather_mislabeled", "world_ru_without", "foreign_story",
            "title_foreign_focus",
        )) for x in (review.get("issues") or []))
    )
    if bad:
        review["approved"] = False
        _record_reject(review)
        AUDIT_BY_URL[candidate.get("url")] = _compact_audit(review, candidate)
        core.b.log("editorial pre-gate reject: " + candidate.get("title", "")[:90] + " | " + "; ".join(review.get("issues", [])[:5]))
        return False
    candidate["_editorial_prechecked"] = True
    return True


_original_collect = core.b.collect


def collect_reconciled(state):
    raw = _original_collect(state)
    out = []
    for candidate in raw:
        core.b.STATS["editorial_prechecked"] += 1
        if not _reconcile_category(candidate):
            continue
        if not _source_precheck(candidate):
            continue
        out.append(candidate)
    core.b.STATS["candidates"] = len(out)
    return out


core.b.collect = collect_reconciled

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
    core.b.log("editorial gate reject: " + candidate.get("title", "")[:90] + " | " + "; ".join(str(x) for x in (review.get("issues") or [])[:5]))

    fallback = prod._extractive_fallback(candidate)
    if fallback:
        fb = _review(candidate, fallback)
        if fb.get("approved"):
            core.b.STATS["editorial_gate_fallback"] += 1
            core.b.STATS["editorial_gate_pass"] += 1
            fallback["editorial_gate"] = _compact_audit(fb, candidate)
            AUDIT_BY_URL[candidate.get("url")] = fallback["editorial_gate"]
            core.b.log(f"editorial gate -> extractive fallback: {candidate.get('title','')[:90]}")
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
