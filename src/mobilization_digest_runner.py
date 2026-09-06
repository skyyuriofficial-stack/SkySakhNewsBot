from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

import requests

import mobilization_digest as digest

_original_collect = digest.collect_evidence
_original_validate = digest.validate_draft
_evidence_cache = []


def collect_with_cache():
    global _evidence_cache
    _evidence_cache = _original_collect()
    return _evidence_cache


def conservative_draft(evidence):
    preferred = [
        item for item in evidence
        if item.get("group") in {"official", "law", "isw", "reuters", "ap", "bbc"}
    ]
    if not preferred:
        preferred = list(evidence)
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
        "headline": "Мобилизационные сигналы: консервативная сводка по найденным источникам",
        "short": "Автоматический редактор перешёл в консервативный режим: публикуются только сведения, прямо присутствующие в свежей доказательной выборке.",
        "items": items,
        "legal": (f"Найден правовой материал: {law.get('title')}" if law else "В свежей выборке нет нового подтверждённого правового акта, прямо объявляющего новую волну мобилизации."),
        "practice": (f"Есть материал о практике: {practice_rows[0].get('title')}. Требуется оценивать его строго в пределах первоисточника." if practice_rows else "В свежей выборке нет надёжно подтверждённого массового операционного сигнала по военкоматам или запасникам."),
        "isw": (f"Свежий найденный материал ISW: {isw.get('title')}" if isw else "Новых данных ISW в доказательной выборке нет."),
        "assessment": {
            "started": "НЕЯСНО — консервативный режим не делает вывод о запуске без прямого официального подтверждения",
            "near_term": "НЕЯСНО — требуется содержательная оценка подтверждённых источников",
            "staffing": "НЕЯСНО — требуется содержательная оценка подтверждённых источников",
            "infrastructure": "НЕЯСНО — требуется содержательная оценка подтверждённых источников",
            "large_wave_decision": "НЕТ ДОКАЗАТЕЛЬСТВ — в текущей доказательной выборке не найден прямой официальный акт о крупной новой волне",
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


def date_aware_validate(draft, evidence):
    issues = _original_validate(draft, evidence)
    date_numbers = set()
    for item in evidence:
        date_numbers.update(re.findall(r"\b\d+(?:[,.]\d+)?\b", str(item.get("published_utc") or "")))
    now = datetime.now(digest.TZ)
    date_numbers.update({str(now.day), str(now.month), str(now.year)})
    fixed = []
    for issue in issues:
        if not str(issue).startswith("invented_numbers:"):
            fixed.append(issue)
            continue
        raw = str(issue).split(":", 1)[1]
        values = {part for part in raw.split(",") if part}
        unsupported = values - date_numbers
        if unsupported:
            fixed.append("invented_numbers:" + ",".join(sorted(unsupported)))
    return fixed


def local_factcheck(draft, evidence):
    by_id = {int(x.get("id")): x for x in evidence}
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
    issues = date_aware_validate(draft, evidence)
    if issues:
        print("Local fact-check rejected AI draft, using conservative fallback:", issues, flush=True)
        return conservative_draft(evidence)
    return draft


digest.collect_evidence = collect_with_cache
digest.openrouter = structured_openrouter
digest.validate_draft = date_aware_validate
digest.verify_draft = local_factcheck


if __name__ == "__main__":
    raise SystemExit(digest.main())
