from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import requests

import mobilization_digest as digest
import mobilization_digest_runner as runner
import mobilization_sources


def robust_collect():
    rows = []
    try:
        rows.extend(runner._original_collect())
    except Exception as exc:
        print(f"primary Google News collection failed: {exc}", flush=True)
    if len(rows) < 8:
        print(f"primary evidence count={len(rows)}; adding direct-source fallback", flush=True)
        try:
            rows.extend(mobilization_sources.collect_fallback())
        except Exception as exc:
            print(f"direct-source fallback error: {exc}", flush=True)

    seen = set()
    unique = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        title = digest.clean(row.get("title"))
        if not title:
            continue
        marker = url or title.lower()
        if marker in seen:
            continue
        seen.add(marker)
        item = dict(row)
        item.pop("id", None)
        unique.append(item)

    unique.sort(
        key=lambda x: (int(x.get("trust") or 0), str(x.get("published_utc") or "")),
        reverse=True,
    )
    unique = unique[:digest.MAX_EVIDENCE]
    for idx, item in enumerate(unique, start=1):
        item["id"] = idx
    runner._evidence_cache = unique
    return unique


def fast_editor(messages, max_tokens=2400):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return json.dumps(runner.conservative_draft(runner._evidence_cache), ensure_ascii=False)
    try:
        response = requests.post(
            digest.OPENROUTER_URL,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "HTTP-Referer": "https://t.me/SkySakhNews",
                "X-OpenRouter-Title": "SkySakhNews Mobilization Digest",
            },
            json={
                "model": digest.MODEL,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": max(3200, int(max_tokens)),
                "response_format": {"type": "json_object"},
            },
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()
        message = ((payload.get("choices") or [{}])[0].get("message") or {})
        text = message.get("content")
        if isinstance(text, str) and "{" in text and "}" in text:
            return text.strip()
        raise RuntimeError("AI route returned no JSON content")
    except Exception as exc:
        print(f"AI editor degraded; using evidence-only conservative fallback: {exc}", flush=True)
        return json.dumps(runner.conservative_draft(runner._evidence_cache), ensure_ascii=False)


digest.collect_evidence = robust_collect
digest.openrouter = fast_editor


def main():
    mode = digest.mode_now()
    evidence = digest.collect_evidence()
    if not evidence:
        raise RuntimeError("no evidence from either primary or direct sources; fail closed")

    draft = digest.parse_json(
        digest.openrouter(
            [
                {
                    "role": "system",
                    "content": "Ты доказательно-ориентированный редактор. Не используй знания вне предоставленного массива источников. Возвращай только JSON.",
                },
                {"role": "user", "content": digest.draft_prompt(evidence, mode)},
            ]
        )
    )
    issues = digest.validate_draft(draft, evidence)
    if issues:
        print("draft validation issues:", issues, flush=True)
    draft = digest.verify_draft(draft, evidence)

    final_issues = digest.validate_draft(draft, evidence)
    if final_issues:
        raise RuntimeError("final digest validation failed: " + "; ".join(final_issues))

    message = digest.format_message(draft, evidence, mode)
    result = digest.send_telegram(message)
    telegram_result = result.get("result") or {}

    state = digest.load_state()
    state.update(
        {
            "version": "mobilization-digest-v1.1",
            "last_run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_run_sakhalin": datetime.now(digest.TZ).isoformat(timespec="seconds"),
            "mode": mode,
            "status": "ok",
            "dry_run": os.getenv("DIGEST_DRY_RUN", "0") == "1",
            "telegram_message_id": telegram_result.get("message_id"),
            "evidence_count": len(evidence),
            "evidence_hash": hashlib.sha256(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "headline": digest.clean(draft.get("headline")),
            "source_ids": draft.get("source_ids") or [],
        }
    )
    digest.save_state(state)
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
