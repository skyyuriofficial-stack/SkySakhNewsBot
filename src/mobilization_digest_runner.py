from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

import requests

import mobilization_digest as digest

_original_collect = digest.collect_evidence
_original_send = digest.send_telegram
_evidence_cache = []


def collect_with_cache():
    global _evidence_cache
    _evidence_cache = _original_collect()
    return _evidence_cache


def conservative_draft(evidence):
    preferred = [
        item for item in evidence
        if item.get("group") in {"official", "law", "isw", "reuters", "ap", "bbc"}
    ] or list(evidence)
    chosen = preferred[:4]
    items = []
    for item in chosen:
        status = "ПОДТВЕРЖДЕНО" if item.get("group") in {"official", "law"} else "КОСВЕННЫЙ СИГНАЛ"
        items.append({
            "status": status,
            "text": f"{item.get('source')}: {item.get('title')}",
            "source_ids": [item.get("id")],
        })
    law = next((x for x in evidence if x.get("group") == "law"), None)
    isw = next((x for x in evidence if x.get("group") == "isw"), None)
    practice_rows = [
        x for x in evidence
        if re.search(r"повест|военком|квот|сборн|reserv", (str(x.get("title")) + " " + str(x.get("summary"))).lower())
    ]
    return {
        "headline": "Мобилизационные сигналы: сводка по подтверждённой выборке",
        "short": "Редактор перешёл в консервативный режим: в сводку включены только сведения, прямо присутствующие в свежей доказательной выборке.",
        "items": items,
        "legal": (f"Найден свежий правовой материал: {law.get('title')}" if law else "В свежей выборке нет нового подтверждённого правового акта, прямо объявляющего новую волну мобилизации."),
        "practice": (f"Есть свежий материал о практике: {practice_rows[0].get('title')}. Его нельзя трактовать шире первоисточника." if practice_rows else "В свежей выборке нет надёжно подтверждённого массового операционного сигнала по военкоматам или запасникам."),
        "isw": (f"Свежий найденный материал ISW: {isw.get('title')}" if isw else "Новых данных ISW в доказательной выборке нет."),
        "assessment": {
            "started": "НЕЯСНО — без прямого официального подтверждения вывод о запуске не делается",
            "near_term": "НЕЯСНО — недостаточно подтверждённых данных для численной оценки",
            "staffing": "НЕЯСНО — недостаточно подтверждённых данных для численной оценки",
            "infrastructure": "НЕЯСНО — недостаточно подтверждённых данных для численной оценки",
            "large_wave_decision": "НЕТ ДОКАЗАТЕЛЬСТВ — в текущей выборке не найден прямой официальный акт о крупной новой волне",
        },
        "source_ids": [item.get("id") for item in chosen],
    }


def structured_openrouter(messages, max_tokens=2400):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return json.dumps(conservative_draft(_evidence_cache), ensure_ascii=False)
    last_error = None
    for attempt in range(3):
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
                    "max_tokens": max(3600, int(max_tokens)),
                    "response_format": {"type": "json_object"},
                },
                timeout=75,
            )
            if response.status_code >= 400:
                last_error = RuntimeError(response.text[:700])
            else:
                payload = response.json()
                message = ((payload.get("choices") or [{}])[0].get("message") or {})
                text = message.get("content")
                if isinstance(text, str) and "{" in text and "}" in text:
                    return text.strip()
                last_error = RuntimeError("OpenRouter returned no JSON content")
        except Exception as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2.0 * (attempt + 1))
    print(f"OpenRouter degraded, using conservative fallback: {last_error}", flush=True)
    return json.dumps(conservative_draft(_evidence_cache), ensure_ascii=False)


def _canon_number(value):
    raw = str(value).replace(",", ".")
    try:
        number = float(raw)
    except Exception:
        return raw
    if number.is_integer():
        return str(int(number))
    return ("%.8f" % number).rstrip("0").rstrip(".")


def validate_draft(draft, evidence):
    issues = []
    valid_ids = {int(item.get("id")) for item in evidence if item.get("id") is not None}
    items = draft.get("items")
    if not isinstance(items, list) or not items or len(items) > 6:
        issues.append("items_invalid")
        items = []

    used_ids = set()
    for item in items:
        if not isinstance(item, dict):
            issues.append("item_not_object")
            continue
        ids = item.get("source_ids")
        if not isinstance(ids, list) or not ids:
            issues.append("item_without_source")
            continue
        for raw in ids:
            try:
                idx = int(raw)
            except Exception:
                issues.append("bad_source_id")
                continue
            if idx not in valid_ids:
                issues.append("unknown_source_id")
            else:
                used_ids.add(idx)

    for raw in draft.get("source_ids") or []:
        try:
            idx = int(raw)
        except Exception:
            issues.append("bad_top_source_id")
            continue
        if idx not in valid_ids:
            issues.append("unknown_top_source_id")
        else:
            used_ids.add(idx)
    if not used_ids:
        issues.append("no_sources_used")

    assessment = draft.get("assessment") or {}
    generated_parts = [
        draft.get("headline"), draft.get("short"), draft.get("legal"),
        draft.get("practice"), draft.get("isw"),
        *assessment.values(),
    ]
    for item in items:
        if isinstance(item, dict):
            generated_parts.extend([item.get("status"), item.get("text")])
    generated = " ".join(digest.clean(x) for x in generated_parts if x is not None)

    evidence_parts = []
    allowed_date_tokens = set()
    for item in evidence:
        evidence_parts.extend([item.get("title"), item.get("summary")])
        raw_dt = str(item.get("published_utc") or "")
        evidence_parts.append(raw_dt)
        try:
            dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            allowed_date_tokens.update({
                str(dt.day), str(dt.month), str(dt.year),
                f"{dt.day}.{dt.month}", f"{dt.day}.{dt.month:02d}",
            })
        except Exception:
            pass
    now = datetime.now(digest.TZ)
    allowed_date_tokens.update({str(now.day), str(now.month), str(now.year)})
    evidence_text = " ".join(digest.clean(x) for x in evidence_parts if x is not None)

    generated_numbers = {_canon_number(x) for x in re.findall(r"\b\d+(?:[,.]\d+)?\b", generated)}
    source_numbers = {_canon_number(x) for x in re.findall(r"\b\d+(?:[,.]\d+)?\b", evidence_text)}
    source_numbers |= {_canon_number(x) for x in allowed_date_tokens}
    invented = sorted(generated_numbers - source_numbers)
    if invented:
        issues.append("invented_numbers:" + ",".join(invented))
    return issues


def local_factcheck(draft, evidence):
    by_id = {int(x.get("id")): x for x in evidence if x.get("id") is not None}
    for item in draft.get("items") or []:
        ids = []
        for raw in item.get("source_ids") or []:
            try:
                idx = int(raw)
            except Exception:
                continue
            if idx in by_id:
                ids.append(idx)
        if item.get("status") == "ПОДТВЕРЖДЕНО":
            if not ids or max(int(by_id[idx].get("trust") or 0) for idx in ids) < 90:
                item["status"] = "КОСВЕННЫЙ СИГНАЛ"

    assessment = draft.get("assessment") or {}
    if str(assessment.get("started") or "").strip().startswith("ДА"):
        used = []
        for item in draft.get("items") or []:
            used.extend(item.get("source_ids") or [])
        direct = False
        for raw in used:
            try:
                src = by_id[int(raw)]
            except Exception:
                continue
            text = (str(src.get("title")) + " " + str(src.get("summary"))).lower()
            if src.get("group") in {"official", "law"} and re.search(r"мобилизац|mobiliz", text) and re.search(r"указ|объяв|decree|announc|начал", text):
                direct = True
                break
        if not direct:
            assessment["started"] = "НЕЯСНО — прямого официального подтверждения запуска в использованных источниках нет"
            draft["assessment"] = assessment

    issues = validate_draft(draft, evidence)
    if issues:
        print("Local fact-check rejected AI draft, using conservative fallback:", issues, flush=True)
        fallback = conservative_draft(evidence)
        fallback_issues = validate_draft(fallback, evidence)
        if fallback_issues:
            raise RuntimeError("conservative fallback validation failed: " + "; ".join(fallback_issues))
        return fallback
    return draft


def guarded_send(text):
    if os.getenv("DIGEST_DRY_RUN", "0") == "1":
        print("DIGEST_DRY_RUN=1: Telegram send skipped after successful build/validation", flush=True)
        return {"ok": True, "result": {"message_id": None, "chat": {"id": None}}}

    state = digest.load_state()
    today = datetime.now(digest.TZ).date().isoformat()
    mode = digest.mode_now()
    previous_time = str(state.get("last_run_sakhalin") or "")
    if state.get("status") == "ok" and state.get("mode") == mode and previous_time.startswith(today) and state.get("telegram_message_id"):
        print(f"Duplicate {mode} digest suppressed; existing message_id={state.get('telegram_message_id')}", flush=True)
        return {"ok": True, "result": {"message_id": state.get("telegram_message_id"), "chat": {"id": None}}}
    return _original_send(text)


digest.collect_evidence = collect_with_cache
digest.openrouter = structured_openrouter
digest.validate_draft = validate_draft
digest.verify_draft = local_factcheck
digest.send_telegram = guarded_send


if __name__ == "__main__":
    raise SystemExit(digest.main())
