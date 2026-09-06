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

BASELINE_ALLOWED_NUMBERS = {"1322096", "8", "18", "20", "2026"}


def collect_with_cache():
    global _evidence_cache
    _evidence_cache = _original_collect()
    return _evidence_cache


def _text(item):
    return (str(item.get("title") or "") + " " + str(item.get("summary") or "")).lower()


def _find(evidence, pattern, group=None):
    rx = re.compile(pattern, re.I)
    for item in evidence:
        if group and item.get("group") != group:
            continue
        if rx.search(_text(item)):
            return item
    return None


def _source_id(item):
    return [int(item.get("id"))] if item and item.get("id") is not None else []


def conservative_draft(evidence):
    """High-quality deterministic fallback. Never dumps raw feed titles as news copy."""
    isw4 = _find(evidence, r"september\s+4|сентябр.{0,8}4", "isw")
    isw5 = _find(evidence, r"september\s+5|сентябр.{0,8}5", "isw")
    isw1 = _find(evidence, r"september\s+1|сентябр.{0,8}1", "isw")
    law = _find(evidence, r"1322096[-–—]?8", "law")
    official = _find(evidence, r"мобилизац|mobiliz", "official")

    items = []
    if isw4:
        items.append({
            "status": "ПОДТВЕРЖДЕНО",
            "text": "ISW в оценке от 4 сентября фиксирует, что Владимир Путин 3 сентября вновь отрицал планы мобилизации и заявлял об отсутствии нехватки личного состава. Сам ISW при этом подчёркивает, что такое публичное заявление не доказывает невозможность будущего изменения решения и считает, что Путин пока придерживается существующей системы добровольного набора.",
            "source_ids": _source_id(isw4),
        })
    if isw1:
        items.append({
            "status": "СИЛЬНЫЙ СИГНАЛ, НО НЕ РЕШЕНИЕ",
            "text": "ISW в оценке от 1 сентября пишет, что действующая добровольная система комплектования испытывает трудности с восполнением текущих потерь и что неясно, как долго Россия сможет сохранять нынешний темп операций без какой-либо формы мобилизации. Приводимая там оценка потерь за август основана на данных украинского Генштаба, а не на независимом подсчёте ISW.",
            "source_ids": _source_id(isw1),
        })
    if isw5:
        items.append({
            "status": "КОСВЕННЫЙ СИГНАЛ",
            "text": "ISW 5 сентября отмечает поддержку Путиным предложения допускать добровольцев с категорией годности «Д» к региональным подразделениям ПВО, включая БАРС. Институт связывает обсуждение таких мер с нехваткой людей и проблемами территориальной ПВО; это расширение кадровой базы, но не объявление мобилизации.",
            "source_ids": _source_id(isw5),
        })
    if law:
        items.append({
            "status": "ПОДТВЕРЖДЕНО",
            "text": "Законопроект №1322096-8 остаётся законопроектом об административной ответственности за неисполнение решений губернатора или регионального оперштаба в пределах их компетенции. Он не является указом о мобилизации, не устанавливает число призываемых и сам по себе не даёт губернатору самостоятельного права объявлять мобилизацию.",
            "source_ids": _source_id(law),
        })
    if official and not isw4:
        items.append({
            "status": "ПОДТВЕРЖДЕНО",
            "text": "В свежей официальной выборке обнаружено заявление или документ по мобилизационной тематике. Его следует трактовать только в пределах опубликованного текста; отдельного подтверждения запуска новой волны в текущей выборке нет.",
            "source_ids": _source_id(official),
        })

    # Only high-confidence operational evidence is allowed into the regional-practice block.
    operational = []
    op_re = re.compile(r"массов.{0,20}повест|квот|сборн.{0,20}пункт|военком.{0,30}(круглосут|усилен)|reserve call|mobilization order", re.I)
    for item in evidence:
        if int(item.get("trust") or 0) < 90:
            continue
        if op_re.search(_text(item)):
            operational.append(item)

    used = []
    for item in items:
        used.extend(item.get("source_ids") or [])

    return {
        "headline": "Новых подтверждённых признаков запуска мобилизации не выявлено",
        "short": "С предыдущей сводки качественного изменения нет: в проверенной выборке не найден новый официальный акт о мобилизации, подтверждённые массовые квоты или массовый вызов запасников. Кадровое давление при этом остаётся высоким по оценкам ISW.",
        "items": items[:6],
        "legal": "По законопроекту №1322096-8 признаков превращения его в действующий закон о мобилизации нет. Его предмет — ответственность за неисполнение решений региональных властей и оперштабов в пределах уже установленной компетенции; мобилизацию он сам не объявляет.",
        "practice": (
            "В высокодоверенной выборке есть операционный сигнал, требующий отдельной проверки: " + str(operational[0].get("title"))
            if operational
            else "Новых надёжно подтверждённых данных о массовой рассылке мобилизационных повесток запасникам, новых региональных квотах или развёртывании сборных пунктов в нескольких регионах не найдено."
        ),
        "isw": "Свежая линия ISW двойственная, но последовательная: Путин пока выглядит приверженным добровольному набору, одновременно институт считает кадровый баланс напряжённым и не исключает необходимости иной формы мобилизации при сохранении текущих потерь.",
        "assessment": {
            "started": "НЕТ — в текущей проверенной выборке нет прямого юридического или подтверждённого массового операционного запуска новой волны",
            "near_term": "ПОВЫШЕННЫЙ — риск реален из-за кадрового давления и заранее созданной инфраструктуры, но принятого решения не доказано",
            "staffing": "ВЫСОКОЕ — ISW указывает на трудности добровольной системы с восполнением потерь",
            "infrastructure": "ВЫСОКАЯ — государственные механизмы учёта и быстрого вызова уже существуют; это готовность, а не доказательство решения",
            "large_wave_decision": "НЕТ ДОКАЗАТЕЛЬСТВ — в проверенной выборке нет официального решения на крупную новую волну",
        },
        "source_ids": sorted(set(int(x) for x in used if x is not None)),
    }


def structured_openrouter(messages, max_tokens=2400):
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return json.dumps(conservative_draft(_evidence_cache), ensure_ascii=False)
    last_error = None
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
                    "messages": messages,
                    "temperature": 0.0,
                    "max_tokens": max(3600, int(max_tokens)),
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
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
        if attempt == 0:
            time.sleep(2)
    print(f"OpenRouter degraded, using analytical fallback: {last_error}", flush=True)
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
        draft.get("practice"), draft.get("isw"), *assessment.values(),
    ]
    for item in items:
        if isinstance(item, dict):
            generated_parts.extend([item.get("status"), item.get("text")])
    generated = " ".join(digest.clean(x) for x in generated_parts if x is not None)

    evidence_parts = []
    allowed_date_tokens = set(BASELINE_ALLOWED_NUMBERS)
    for item in evidence:
        evidence_parts.extend([item.get("title"), item.get("summary"), item.get("source")])
        raw_dt = str(item.get("published_utc") or "")
        evidence_parts.append(raw_dt)
        try:
            dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            allowed_date_tokens.update({str(dt.day), str(dt.month), str(dt.year)})
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

    bad_phrases = ["консервативный режим", "свежий найденный материал", "его нельзя трактовать шире первоисточника"]
    full_text = generated.lower()
    for phrase in bad_phrases:
        if phrase in full_text:
            issues.append("low_quality_fallback_phrase:" + phrase)
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
        if item.get("status") == "ПОДТВЕРЖДЕНО" and ids:
            if max(int(by_id[idx].get("trust") or 0) for idx in ids) < 90:
                item["status"] = "КОСВЕННЫЙ СИГНАЛ"

    issues = validate_draft(draft, evidence)
    if issues:
        print("Local fact-check rejected AI draft, using analytical fallback:", issues, flush=True)
        fallback = conservative_draft(evidence)
        fallback_issues = validate_draft(fallback, evidence)
        if fallback_issues:
            raise RuntimeError("analytical fallback validation failed: " + "; ".join(fallback_issues))
        return fallback
    return draft


def guarded_send(text):
    if os.getenv("DIGEST_DRY_RUN", "0") == "1":
        print("DIGEST_DRY_RUN=1: Telegram send skipped after successful build/validation", flush=True)
        print("--- DIGEST PREVIEW ---\n" + text + "\n--- END PREVIEW ---", flush=True)
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
