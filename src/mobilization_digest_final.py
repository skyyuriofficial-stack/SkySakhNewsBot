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

    # Prefer specifically sourced legal facts over repetitive raw GARANT page
    # titles.  Legal status, bill text, presidential powers and decree remain
    # separately citeable; three URLs for one bill are not three independent acts.
    have_verified_baseline = any(row.get("legal_role") for row in rows)
    if have_verified_baseline:
        rows = [
            row for row in rows
            if not (
                str(row.get("group") or "") == "law"
                and not row.get("legal_role")
                and any(token in str(row.get("url") or "")
                        for token in ("/414784137/", "/411685333/"))
            )
        ]
    rows.sort(
        key=lambda row: (
            bool(row.get("legal_role")),
            int(row.get("trust") or 0),
            str(row.get("published_utc") or ""),
        ),
        reverse=True,
    )
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


def _legal_role(evidence, role):
    return next(
        (item for item in evidence
         if str(item.get("group") or "") == "law"
         and item.get("legal_role") == role),
        None,
    )


def _civil_society_recent(evidence):
    """Prefer verified-dated first-party posts, not recycled secondary headlines."""
    rows = [
        item for item in evidence
        if item.get("group") == "civil_society"
        and str(item.get("url") or "").startswith("https://t.me/iditelesom_help/")
    ]
    return sorted(
        rows, key=lambda item: str(item.get("published_utc") or ""),
        reverse=True,
    )


def _civil_society_claim(item):
    title = digest.clean(item.get("title"))
    body = digest.clean(item.get("summary"))
    low = (title + " " + body).lower()
    # The Telegram public preview may contain unrelated quoted/adjacent
    # fragments in the article body. Only a headline explicitly identifying
    # a fake summons may be described as a debunking notice.
    if re.search(r"фейков|поддельн", title, re.I):
        return (
            f"По сообщению проекта «Идите лесом»: {title}. "
            "Оценка подлинности повесток принадлежит проекту; "
            "без самостоятельной проверки не считаем её установленным фактом."
        )
    if "запасник" in low and "повестк" in low:
        places = (
            "Ставропольский край, Башкортостан, Марий Эл, "
            "Оренбургская и Саратовская области"
        )
        # Include all five places only when all are present in source evidence.
        regions = (
            "Ставропольск", "Башкортостан", "Марий Эл",
            "Оренбургск", "Саратовск"
        )
        location = (
            f" ({places})"
            if all(token.lower() in low for token in regions)
            else ""
        )
        return (
            "Проект «Идите лесом» сообщил о повестках запасникам "
            f"для уточнения военно-учётных данных{location}. "
            "Сообщение проекта не подтверждает массовый призыв по мобилизации; "
            "достоверность и охват требуют независимой проверки."
        )
    return (
        f"«Идите лесом» сообщило: {title}. "
        "Это сведения правозащитного проекта, не официальный документ "
        "и не независимое подтверждение масштабов явления."
    )


def safe_fallback_draft(evidence):
    """Explain the law and evidence instead of repeating multiple bill titles."""
    evidence = [
        row for row in evidence
        if isinstance(row, dict) and row.get("id") is not None
    ]
    stage = _legal_role(evidence, "first_reading_baseline")
    bill = _legal_role(evidence, "bill_text")
    powers = _legal_role(evidence, "presidential_powers")
    decree = _legal_role(evidence, "regional_framework")
    recent_civil = _civil_society_recent(evidence)
    isw = next(
        (item for item in evidence if item.get("group") == "isw"),
        None,
    )
    law_fallback = next(
        (item for item in evidence if item.get("group") == "law"),
        None,
    )

    def row_ids(*rows):
        return [
            int(row["id"]) for row in rows
            if isinstance(row, dict) and row.get("id") is not None
        ]

    items = []
    source_ids = []
    if stage:
        items.append({
            "status": "ПОДТВЕРЖДЕНО — ЭТАП ЗАКОНОПРОЕКТА",
            "text": (
                "27 октября 2026 года №1322096-8 принят Госдумой в первом "
                "чтении (постановление 177-9 ГД); срок представления поправок — "
                "10 ноября. Эта дата является подтверждённой исторической "
                "вехой, а не автоматическим подтверждением сегодняшней "
                "стадии или вступления нормы в силу."
            ),
            "source_ids": row_ids(stage),
        })
        source_ids.extend(row_ids(stage))
    elif law_fallback:
        items.append({
            "status": "ЮРИДИЧЕСКИЙ ИСТОЧНИК",
            "text": (
                f"По документу «{digest.clean(law_fallback.get('title'))[:110]}» "
                "необходимо отдельно установить текущую стадию рассмотрения."
            ),
            "source_ids": row_ids(law_fallback),
        })
        source_ids.extend(row_ids(law_fallback))

    if recent_civil:
        # One substantive claim and one distinct warning at most; do not
        # confuse statements by the organisation with verified state actions.
        substantive = next(
            (row for row in recent_civil
             if re.search(r"запасник.{0,100}повестк|повестк.{0,120}запасник",
                          _evidence_text(row), re.I)
             and not re.search(r"фейков|поддельн",
                               digest.clean(row.get("title")), re.I)),
            recent_civil[0],
        )
        items.append({
            "status": "СООБЩЕНИЕ ПРАВОЗАЩИТНОГО ПРОЕКТА",
            "text": _civil_society_claim(substantive),
            "source_ids": row_ids(substantive),
        })
        source_ids.extend(row_ids(substantive))
        fake = next(
            (row for row in recent_civil
             if row is not substantive
             and re.search(r"фейков|поддельн",
                           digest.clean(row.get("title")), re.I)),
            None,
        )
        if fake:
            items.append({
                "status": "ПРЕДУПРЕЖДЕНИЕ ИСТОЧНИКА",
                "text": _civil_society_claim(fake),
                "source_ids": row_ids(fake),
            })
            source_ids.extend(row_ids(fake))

    if isw and re.search(
        r"mobiliz|manpower|recruit|force generation|кадров|мобилизац",
        _evidence_text(isw), re.I,
    ):
        items.append({
            "status": "АНАЛИТИЧЕСКИЙ МАТЕРИАЛ",
            "text": (
                f"ISW: «{digest.clean(isw.get('title'))[:105]}». "
                "Аналитическую оценку следует отличать от официального "
                "решения; выводы о новой волне по одному исследованию "
                "не делаются."
            ),
            "source_ids": row_ids(isw),
        })
        source_ids.extend(row_ids(isw))

    # Permanent legal framework cited as legislation, not invented news.
    legal = (
        "По состоянию на 27.10.2026 проект №1322096-8 принят только "
        "в первом чтении; поправки до 10.11.2026. Он предлагает "
        "статью 19.5.5 КоАП РФ об ответственности за неисполнение "
        "решений губернаторов и региональных оперштабов в пределах "
        "их компетенции. Санкции по ПРОЕКТУ: гражданам 3–5 тыс. руб.; "
        "должностным лицам 30–50 тыс. руб. или дисквалификация на "
        "1–3 года; организациям 300 тыс.–1 млн руб. или приостановление "
        "деятельности до 90 суток. Это не вступивший в силу штраф "
        "по новой статье. Статья 4 закона №31-ФЗ закрепляет объявление "
        "общей и частичной мобилизации за Президентом; Указ №757 "
        "от 19.10.2022 описывает полномочия региональных штабов."
        if stage and bill and powers and decree
        else (
            "Актуальная юридическая стадия и точные нормы не подтверждены "
            "доступным первичным документом. Не делаем выводов на основании "
            "одного названия законопроекта."
        )
    )
    source_ids.extend(row_ids(bill, powers, decree))

    if recent_civil:
        practice = (
            "Проверены сообщения «Идите лесом» о повестках, в том числе "
            "для уточнения данных, и отдельные предупреждения о подделках. "
            "Это свидетельства обращений к правозащитному проекту, "
            "а не проверенное количество мобилизованных. Не смешиваем "
            "уточнение воинского учёта, военные сборы, контракт "
            "и призыв по мобилизации."
        )
    else:
        practice = (
            "В доступной выборке недостаточно проверенных новых региональных "
            "данных. Отсутствие сообщений не доказывает отсутствие вызовов "
            "военкоматами; отдельно проверять повестки, сборы и контракты."
        )

    isw_text = (
        "Есть текущий аналитический материал ISW; его наблюдения "
        "не считаются подтверждением указа или мобилизационных квот."
        if isw else
        "Свежего относящегося к мобилизационному комплектованию "
        "анализа ISW в проверенной выборке нет."
    )
    if not items:
        # All normal operation should carry a sourced legal baseline, but keep
        # a minimal source-bound shape rather than fabricate a news item.
        best = next(iter(evidence), None)
        if best:
            items.append({
                "status": "ИСТОЧНИК ТРЕБУЕТ ПРОВЕРКИ",
                "text": f"«{digest.clean(best.get('title'))[:120]}». "
                        "Нельзя делать вывод о запуске мобилизации по заголовку.",
                "source_ids": row_ids(best),
            })
            source_ids.extend(row_ids(best))

    source_ids = list(dict.fromkeys(source_ids))
    return {
        "headline": "Юридический статус и повестки: что подтверждено, а что нет",
        "short": (
            "По текущей выборке не установлено нового решения о запуске "
            "массовой мобилизации. Есть конкретная законодательная "
            "инициатива и сообщения правозащитного проекта, "
            "требующие раздельной оценки."
        ),
        "items": items[:5],
        "legal": legal,
        "practice": practice,
        "isw": isw_text,
        "assessment": {
            "started": (
                "НЕ ПОДТВЕРЖДЕНО — в проверенных материалах нет нового "
                "официального акта о запуске массовой мобилизации"
            ),
            "near_term": (
                "НЕДОСТАТОЧНО ДАННЫХ — отдельные повестки и законопроект "
                "не позволяют количественно оценить вероятность новой волны"
            ),
            "staffing": (
                "НЕ ОЦЕНЕНО — данных о фактическом восполнении потерь "
                "в текущей выборке недостаточно"
            ),
            "infrastructure": (
                "НОРМАТИВНАЯ ОСНОВА ЕСТЬ — Указ №757; текущая "
                "операционная развёрнутость штабов не измерена"
                if decree else
                "НЕДОСТАТОЧНО ДАННЫХ — готовность не измерена"
            ),
            "large_wave_decision": (
                "ПОДТВЕРЖДЕНИЯ НЕТ — законопроект №1322096-8 "
                "сам по себе не объявляет мобилизацию"
            ),
        },
        "source_ids": source_ids[:8],
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

    # Preserve a completed Telegram slot before interpreting push/manual
    # workflow events. A code push is not permission to regenerate and
    # fabricate a fresh last_run timestamp for an already published digest.
    now_local = datetime.now(digest.TZ)
    day = now_local.date().isoformat()
    state = digest.load_state()
    if _already_published(state, day, mode):
        print(f"Digest slot already published: {day} {mode}; no-op", flush=True)
        return False

    event = os.getenv("GITHUB_EVENT_NAME", "").strip()
    if event in {"workflow_dispatch", "push"} or not event:
        return True
    if event == "schedule" and now_local.hour < 8:
        print("Digest schedule check: before 08:00 Sakhalin, nothing is due", flush=True)
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
