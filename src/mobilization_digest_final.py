from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import requests

import mobilization_digest as digest
import mobilization_digest_runner as runner
import mobilization_sources


def _quality_row(row):
    if not isinstance(row, dict):
        return False
    group = str(row.get("group") or "")
    trust = int(row.get("trust") or 0)
    # Generic Russian media discovered through broad Google queries is not
    # strong enough for this high-stakes digest. Keep only strong named outlets.
    if group == "ru_media" and trust < 85:
        return False
    return mobilization_sources.is_relevant(row)


def robust_collect():
    rows = []
    try:
        rows.extend(row for row in runner._original_collect() if _quality_row(row))
    except Exception as exc:
        print(f"primary Google News collection failed: {exc}", flush=True)

    try:
        rows.extend(row for row in mobilization_sources.collect_fallback() if _quality_row(row))
    except Exception as exc:
        print(f"direct-source collection error: {exc}", flush=True)

    seen = set()
    unique = []
    for row in rows:
        if not _quality_row(row):
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


def robust_parse_json(text):
    if isinstance(text, dict):
        return text
    raw = str(text or "").strip()
    candidates = [raw]

    fenced = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    fenced = re.sub(r"\s*```$", "", fenced)
    if fenced != raw:
        candidates.append(fenced.strip())

    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1].strip())

    tried = set()
    for candidate in candidates:
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        for variant in (
            candidate,
            re.sub(r",\s*([}\]])", r"\1", candidate),
        ):
            try:
                value = json.loads(variant)
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
        try:
            value = ast.literal_eval(candidate)
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    raise ValueError("AI response is not a valid JSON object")


def _evidence_text(item):
    return (
        digest.clean(item.get("title"))
        + " "
        + digest.clean(item.get("summary"))
    ).lower()


def safe_fallback_draft(evidence):
    """Deterministic, evidence-bound fallback used only when the AI route is unusable."""
    ranked = sorted(
        [x for x in evidence if isinstance(x, dict) and x.get("id") is not None],
        key=lambda x: (int(x.get("trust") or 0), str(x.get("published_utc") or "")),
        reverse=True,
    )
    selected = [x for x in ranked if int(x.get("trust") or 0) >= 90][:4] or ranked[:4]

    items = []
    used_ids = []
    for source in selected:
        idx = int(source["id"])
        group = str(source.get("group") or "")
        title = digest.clean(source.get("title"))
        name = digest.clean(source.get("source")) or group
        status = "ПОДТВЕРЖДЕНО" if group in {"official", "law"} else "КОСВЕННЫЙ СИГНАЛ"
        items.append(
            {
                "status": status,
                "text": (
                    f"{name}: «{title}». "
                    "Материал учитывается только в пределах заголовка и доступного описания; "
                    "сам по себе он не подтверждает запуск новой волны мобилизации."
                ),
                "source_ids": [idx],
            }
        )
        used_ids.append(idx)

    law = next((x for x in ranked if str(x.get("group") or "") == "law"), None)
    isw = next((x for x in ranked if str(x.get("group") or "") == "isw"), None)

    operational_rx = re.compile(
        r"массов.{0,20}повест|квот|сборн.{0,20}пункт|"
        r"военком.{0,30}(круглосут|усилен)|reserve call|mobilization order",
        re.I,
    )
    operational = next(
        (
            x
            for x in ranked
            if int(x.get("trust") or 0) >= 90 and operational_rx.search(_evidence_text(x))
        ),
        None,
    )

    legal_text = (
        f"В доказательной выборке есть юридический материал: «{digest.clean(law.get('title'))}». "
        "Резервная логика не делает выводов сверх его заголовка и доступного описания."
        if law
        else "Существенного юридического изменения, прямо подтверждающего запуск новой волны, в доказательной выборке не выявлено."
    )
    practice_text = (
        f"Есть высокодоверенный операционный материал: «{digest.clean(operational.get('title'))}». "
        "Он требует трактовки строго в пределах первоисточника."
        if operational
        else "Надёжно подтверждённых данных о массовом вызове запасников, новых региональных квотах или развёртывании сборных пунктов в текущей выборке не выявлено."
    )
    isw_text = (
        f"В доказательной выборке есть оценка ISW: «{digest.clean(isw.get('title'))}». "
        "Это аналитический источник, а не официальный акт."
        if isw
        else "Новых данных ISW в доказательной выборке нет."
    )

    has_analytical_signal = any(
        str(x.get("group") or "") in {"isw", "reuters", "ap", "bbc"} for x in ranked
    )
    return {
        "headline": "Прямого подтверждения запуска новой волны в проверенной выборке нет",
        "short": (
            "В текущей проверенной выборке прямого подтверждения запуска новой волны мобилизации не выявлено. "
            "Ниже приведены только высокодоверенные материалы без расширительного толкования."
        ),
        "items": items[:6],
        "legal": legal_text,
        "practice": practice_text,
        "isw": isw_text,
        "assessment": {
            "started": "НЕТ — в текущей доказательной выборке нет прямого юридического или подтверждённого массового операционного запуска",
            "near_term": (
                "УМЕРЕННЫЙ — прямого решения в выборке нет; аналитические сигналы сами по себе не доказывают запуск"
                if has_analytical_signal
                else "НИЗКИЙ — прямого решения и сильных аналитических сигналов в текущей выборке нет"
            ),
            "staffing": "УМЕРЕННОЕ — доказательной базы для более категоричной оценки в текущей выборке недостаточно",
            "infrastructure": "СРЕДНЯЯ — текущая выборка не содержит достаточного набора подтверждённых операционных признаков для более высокой оценки",
            "large_wave_decision": "НЕТ ДОКАЗАТЕЛЬСТВ — в текущей проверенной выборке нет официального решения о крупной новой волне",
        },
        "source_ids": sorted(set(used_ids)),
    }


def fast_editor(messages, max_tokens=2400):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return json.dumps(safe_fallback_draft(runner._evidence_cache), ensure_ascii=False)

    last_error = None
    request_messages = list(messages)
    for attempt in range(2):
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
                    "messages": request_messages,
                    "temperature": 0.0,
                    "max_tokens": max(3200, int(max_tokens)),
                    "response_format": {"type": "json_object"},
                },
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            message = ((payload.get("choices") or [{}])[0].get("message") or {})
            text = message.get("content")
            if isinstance(text, list):
                text = "".join(
                    str(part.get("text") or "")
                    for part in text
                    if isinstance(part, dict)
                )
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("AI route returned no JSON content")
            parsed = robust_parse_json(text)
            return json.dumps(parsed, ensure_ascii=False)
        except Exception as exc:
            last_error = exc
            print(f"AI editor attempt {attempt + 1} failed: {exc}", flush=True)
            if attempt == 0:
                request_messages = list(messages) + [
                    {
                        "role": "user",
                        "content": (
                            "Предыдущая попытка не дала валидный JSON. "
                            "Повтори ответ строго как один корректный JSON-объект без markdown, комментариев и текста вне JSON."
                        ),
                    }
                ]

    print(
        f"AI editor degraded; using evidence-bound deterministic fallback: {last_error}",
        flush=True,
    )
    return json.dumps(safe_fallback_draft(runner._evidence_cache), ensure_ascii=False)


def resolved_mode():
    forced = os.getenv("DIGEST_MODE", "").strip().lower()
    if forced in {"morning", "evening"}:
        return forced

    scheduled = os.getenv("DIGEST_SCHEDULE", "").strip()
    if scheduled in {
        "0,30 0,1,21,22,23 * * *",
        "0 2,3,4,5,6,7 * * *",
    }:
        return "morning"
    if scheduled == "0,30 8,9,10,11 * * *":
        return "evening"

    return "morning" if datetime.now(digest.TZ).hour < 19 else "evening"


def _slot_record(state, day, mode):
    slots = state.get("slots") or {}
    day_slots = slots.get(day) or {}
    record = day_slots.get(mode)
    return record if isinstance(record, dict) else {}


def _legacy_slot_ok(state, day, mode):
    return bool(
        state.get("status") == "ok"
        and state.get("mode") == mode
        and str(state.get("last_run_sakhalin") or "").startswith(day)
        and state.get("telegram_message_id")
    )


def _already_published(state, day, mode):
    slot = _slot_record(state, day, mode)
    if slot.get("status") == "ok" and slot.get("telegram_message_id"):
        return True
    return _legacy_slot_ok(state, day, mode)


def _should_execute(mode):
    if os.getenv("DIGEST_DRY_RUN", "0") == "1":
        return True
    event = os.getenv("GITHUB_EVENT_NAME", "").strip()
    if event in {"workflow_dispatch", "push"} or not event:
        return True

    now_local = datetime.now(digest.TZ)
    if event == "schedule" and now_local.hour < 8:
        print("Digest schedule check: before 08:00 Sakhalin, nothing is due", flush=True)
        return False

    day = now_local.date().isoformat()
    state = digest.load_state()
    if _already_published(state, day, mode):
        print(f"Digest schedule check: {day} {mode} already published", flush=True)
        return False
    return True


def _migrate_legacy_success(state):
    if not (
        state.get("status") == "ok"
        and state.get("telegram_message_id")
        and state.get("mode") in {"morning", "evening"}
    ):
        return
    stamp = str(state.get("last_run_sakhalin") or "")
    if len(stamp) < 10:
        return
    day = stamp[:10]
    mode = state.get("mode")
    slots = state.setdefault("slots", {})
    day_slots = slots.setdefault(day, {})
    day_slots.setdefault(
        mode,
        {
            "status": "ok",
            "published_at_sakhalin": stamp,
            "telegram_message_id": state.get("telegram_message_id"),
            "headline": state.get("headline"),
            "evidence_count": state.get("evidence_count"),
            "evidence_hash": state.get("evidence_hash"),
            "source_ids": state.get("source_ids") or [],
            "migrated_from_legacy": True,
        },
    )


def _prune_slots(state, keep_days=21):
    slots = state.get("slots")
    if not isinstance(slots, dict):
        return
    for day in sorted(slots)[:-keep_days]:
        slots.pop(day, None)


def _record_success(mode, evidence, draft, telegram_result):
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now(digest.TZ)
    evidence_hash = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    state = digest.load_state()
    _migrate_legacy_success(state)

    state.update(
        {
            "version": "mobilization-digest-v1.3",
            "last_run_utc": now_utc.isoformat(timespec="seconds"),
            "last_run_sakhalin": now_local.isoformat(timespec="seconds"),
            "mode": mode,
            "status": "ok",
            "dry_run": os.getenv("DIGEST_DRY_RUN", "0") == "1",
            "telegram_message_id": telegram_result.get("message_id"),
            "evidence_count": len(evidence),
            "evidence_hash": evidence_hash,
            "headline": digest.clean(draft.get("headline")),
            "source_ids": draft.get("source_ids") or [],
            "last_attempt": {
                "status": "ok",
                "mode": mode,
                "at_utc": now_utc.isoformat(timespec="seconds"),
                "at_sakhalin": now_local.isoformat(timespec="seconds"),
            },
        }
    )

    if telegram_result.get("message_id"):
        slots = state.setdefault("slots", {})
        day_slots = slots.setdefault(now_local.date().isoformat(), {})
        day_slots[mode] = {
            "status": "ok",
            "published_at_utc": now_utc.isoformat(timespec="seconds"),
            "published_at_sakhalin": now_local.isoformat(timespec="seconds"),
            "telegram_message_id": telegram_result.get("message_id"),
            "headline": digest.clean(draft.get("headline")),
            "evidence_count": len(evidence),
            "evidence_hash": evidence_hash,
            "source_ids": draft.get("source_ids") or [],
        }

    _prune_slots(state)
    digest.save_state(state)
    return state


def _record_failure(mode, exc):
    try:
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now(digest.TZ)
        state = digest.load_state()
        _migrate_legacy_success(state)
        state["version"] = "mobilization-digest-v1.3"
        state["last_attempt"] = {
            "status": "error",
            "mode": mode,
            "at_utc": now_utc.isoformat(timespec="seconds"),
            "at_sakhalin": now_local.isoformat(timespec="seconds"),
            "error": str(exc)[:1200],
        }
        _prune_slots(state)
        digest.save_state(state)
    except Exception as state_exc:
        print(f"failed to persist digest failure state: {state_exc}", flush=True)


digest.collect_evidence = robust_collect
digest.parse_json = robust_parse_json
digest.openrouter = fast_editor
digest.mode_now = resolved_mode
runner.conservative_draft = safe_fallback_draft


def main():
    mode = resolved_mode()
    if not _should_execute(mode):
        return 0

    evidence = digest.collect_evidence()
    if not evidence:
        raise RuntimeError("no relevant evidence from primary or direct sources; fail closed")

    print("Relevant evidence:", flush=True)
    for item in evidence[:16]:
        print(
            f"  [{item.get('id')}] {item.get('group')} trust={item.get('trust')} | {digest.clean(item.get('title'))[:160]}",
            flush=True,
        )

    draft = digest.parse_json(
        digest.openrouter(
            [
                {
                    "role": "system",
                    "content": "Ты доказательно-ориентированный редактор. Не используй знания вне предоставленного массива источников. Не заполняй объём ради объёма. Возвращай только JSON.",
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
        fallback = safe_fallback_draft(evidence)
        fallback_issues = digest.validate_draft(fallback, evidence)
        if fallback_issues:
            raise RuntimeError(
                "final digest validation failed: "
                + "; ".join(final_issues)
                + " | fallback failed: "
                + "; ".join(fallback_issues)
            )
        print(
            "AI draft failed final validation; publishing evidence-bound deterministic fallback",
            flush=True,
        )
        draft = fallback

    message = digest.format_message(draft, evidence, mode)
    result = digest.send_telegram(message)
    telegram_result = result.get("result") or {}

    state = _record_success(mode, evidence, draft, telegram_result)
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    active_mode = resolved_mode()
    try:
        raise SystemExit(main())
    except Exception as exc:
        _record_failure(active_mode, exc)
        print(f"mobilization digest failed: {exc}", flush=True)
        raise
