"""Live-source dry audit for stable-v12.0. No Telegram calls are made."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import publisher_v12 as publisher
import quality_v12 as quality

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
REPORT_PATH = ROOT / "quality_audit_v12.json"


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    raw = publisher._RAW_COLLECT(copy.deepcopy(state))
    ordered, report = quality.select(
        state, raw, category_map=publisher.core.b.CAT, limit=2,
    )
    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:1800]})

    check("raw_candidates_present", len(raw) > 0, len(raw))
    check("approved_candidates_present", int(report.get("approved_count") or 0) > 0, report.get("approved_count"))
    check("selected_candidates_present", len(ordered) >= 1, len(ordered))
    top = ordered[:2]
    if len(top) == 2:
        groups = [(item.get("_quality_v12") or {}).get("group") for item in top]
        check("top_two_groups_diverse", groups[0] != groups[1], groups)

    for index, item in enumerate(top, 1):
        metadata = item.get("_quality_v12") or {}
        reread = quality.review(item)
        check(f"selected_{index}_approved", metadata.get("approved") is True, metadata)
        check(f"selected_{index}_absolute_threshold", int(metadata.get("score") or 0) >= int(metadata.get("threshold") or 101), metadata)
        check(f"selected_{index}_category_reproducible", reread.get("corrected_category") == item.get("category_key"), (reread, item.get("category_key")))
        check(f"selected_{index}_not_soft_content", quality.hard_reject_reason(str(item.get("title") or ""), str(item.get("source_text") or "")[:1800]) is None, item.get("title"))
        title_ok, title_issues = quality.title_quality(quality.sanitize_title(item.get("title")))
        check(f"selected_{index}_title_quality", title_ok, title_issues)
        check(f"selected_{index}_has_source_media", bool(item.get("image_url") and item.get("image_hash") and item.get("image")), item.get("image_url"))

    suspicious_approved = []
    for item in ordered:
        metadata = item.get("_quality_v12") or {}
        if metadata.get("approved") is not True:
            continue
        reason = quality.hard_reject_reason(str(item.get("title") or ""), str(item.get("source_text") or "")[:1800])
        reread = quality.review(item)
        if reason or reread.get("corrected_category") != item.get("category_key"):
            suspicious_approved.append({
                "title": item.get("title"), "category_key": item.get("category_key"),
                "hard_reason": reason, "reread": quality.compact(reread),
            })
    check("no_suspicious_approved_candidates", not suspicious_approved, suspicious_approved[:10])

    result = {
        "version": "stable-v12.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "live_sources_dry_telegram",
        "raw_candidate_count": len(raw),
        "approved_count": report.get("approved_count"),
        "rejected_count": report.get("rejected_count"),
        "rejected_by_reason": report.get("rejected_by_reason"),
        "balance_before": report.get("balance_before"),
        "selected": report.get("selected"),
        "checks": checks,
        "passed": sum(1 for item in checks if item["ok"]),
        "failed": sum(1 for item in checks if not item["ok"]),
    }
    result["all_pass"] = result["failed"] == 0
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("version", "raw_candidate_count", "approved_count", "rejected_count", "passed", "failed", "all_pass")}, ensure_ascii=False))
    if not result["all_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
