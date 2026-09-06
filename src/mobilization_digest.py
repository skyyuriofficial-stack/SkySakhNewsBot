from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List

import feedparser
import requests

TZ = timezone(timedelta(hours=11))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL") or "openrouter/free"
STATE_PATH = Path("mobilization_digest_state.json")
MAX_EVIDENCE = 42

QUERIES = [
    ("official", "site:kremlin.ru мобилизация резервисты военкомат Путин when:3d", "ru", "RU"),
    ("law", "site:publication.pravo.gov.ru мобилизация военная служба резервисты when:7d", "ru", "RU"),
    ("law", "1322096-8 губернатор оперштаб законопроект when:7d", "ru", "RU"),
    ("isw", "site:understandingwar.org Russia mobilization reservists Putin September 2026 when:4d", "en", "US"),
    ("reuters", "site:reuters.com Russia mobilization reservists Putin September 2026 when:4d", "en", "US"),
    ("ap", "site:apnews.com Russia mobilization reservists Putin September 2026 when:4d", "en", "US"),
    ("bbc", "site:bbc.com Russia mobilization reservists Putin September 2026 when:4d", "en", "US"),
    ("ru_media", "мобилизация резервисты военкоматы повестки регионы Россия сентябрь 2026 when:3d", "ru", "RU"),
    ("ru_media", "БАРС ПВО категория Д добровольцы резервисты сентябрь 2026 when:7d", "ru", "RU"),
]

TRUST_MARKERS = {
    "official": 100,
    "law": 100,
    "isw": 96,
    "reuters": 95,
    "ap": 94,
    "bbc": 91,
    "ru_media": 72,
}


def clean(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def gnews(query: str, lang: str, country: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote_plus(query)
        + f"&hl={lang}&gl={country}&ceid={country}:{lang}"
    )


def parse_dt(entry: Dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def source_name(entry: Dict[str, Any], fallback: str) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        title = clean(source.get("title"))
        if title:
            return title
    return fallback


def collect_evidence() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for group, query, lang, country in QUERIES:
        try:
            feed = feedparser.parse(gnews(query, lang, country))
        except Exception as exc:
            print(f"feed error {group}: {exc}", flush=True)
            continue
        for entry in feed.entries[:12]:
            title = clean(entry.get("title"))
            summary = clean(entry.get("summary") or entry.get("description"))
            url = clean(entry.get("link"))
            if not title or not url:
                continue
            dt = parse_dt(entry)
            if dt and now - dt > timedelta(days=8):
                continue
            marker = re.sub(r"\W+", " ", title.lower()).strip()
            if marker in seen:
                continue
            seen.add(marker)
            rows.append(
                {
                    "group": group,
                    "trust": TRUST_MARKERS[group],
                    "source": source_name(entry, group),
                    "title": title,
                    "summary": summary[:700],
                    "url": url,
                    "published_utc": dt.isoformat() if dt else None,
                }
            )
    rows.sort(
        key=lambda x: (
            int(x.get("trust") or 0),
            str(x.get("published_utc") or ""),
        ),
        reverse=True,
    )
    for idx, row in enumerate(rows[:MAX_EVIDENCE], start=1):
        row["id"] = idx
    return rows[:MAX_EVIDENCE]


def openrouter(messages: List[Dict[str, str]], max_tokens: int = 2400) -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/SkySakhNews",
            "X-OpenRouter-Title": "SkySakhNews Mobilization Digest",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": 0.01,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text[:1000])
    return response.json()["choices"][0]["message"]["content"].strip()


def parse_json(text: str) -> Dict[str, Any]:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON object not found")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON root is not object")
    return value


def mode_now() -> str:
    forced = os.getenv("DIGEST_MODE", "").strip().lower()
    if forced in {"morning", "evening"}:
        return forced
    return "morning" if datetime.now(TZ).hour < 13 else "evening"


def draft_prompt(evidence: List[Dict[str, Any]], mode: str) -> str:
    now_sakh = datetime.now(TZ).isoformat(timespec="minutes")
    compact = [
        {
            "id": item["id"],
            "group": item["group"],
            "trust": item["trust"],
            "source": item["source"],
            "title": item["title"],
            "summary": item["summary"],
            "published_utc": item["published_utc"],
        }
        for item in evidence
    ]
    return f"""
Ты выпускающий редактор SkySakhNews. Сделай {('УТРЕННЮЮ' if mode == 'morning' else 'ВЕЧЕРНЮЮ')} сводку о риске новой волны мобилизации в РФ.
Текущее время Сахалина: {now_sakh}.

КРИТИЧЕСКОЕ ПРАВИЛО: используй ТОЛЬКО факты из массива EVIDENCE ниже. Нельзя добавлять знания из памяти модели, предполагаемые законы, цифры, даты, цитаты или события, которых нет в EVIDENCE. Заголовок источника сам по себе подтверждает только то, что прямо в нём сказано. Перепечатки одного сообщения не являются независимыми подтверждениями.

Разделяй уровень сигнала строго:
- ПОДТВЕРЖДЕНО — официальный акт/официальное заявление либо хорошо подтверждённый факт;
- СИЛЬНЫЙ СИГНАЛ, НО НЕ РЕШЕНИЕ — существенный кадровый/операционный признак без решения о мобилизации;
- КОСВЕННЫЙ СИГНАЛ;
- НЕПОДТВЕРЖДЕНО/СЛУХ;
- ОПРОВЕРГНУТО.

Не называй обычный призыв граждан, не пребывающих в запасе, военные сборы или добровольный контракт новой мобилизацией. Не утверждай, что новая волна началась, без прямого юридического/операционного подтверждения в EVIDENCE. Особо проверь наличие в EVIDENCE данных о: новом указе/законе; массовых повестках запасникам; региональных квотах; сборных пунктах; кадровом дефиците; БАРС/ПВО; законопроекте 1322096-8; оценках ISW; заявлениях Кремля; мирных переговорах только если они меняют кадровый спрос.

Верни ТОЛЬКО JSON следующего вида:
{{
  "headline": "короткий заголовок без сенсационности",
  "short": "1-2 предложения: что реально изменилось",
  "items": [
    {{"status":"ПОДТВЕРЖДЕНО|СИЛЬНЫЙ СИГНАЛ, НО НЕ РЕШЕНИЕ|КОСВЕННЫЙ СИГНАЛ|НЕПОДТВЕРЖДЕНО/СЛУХ|ОПРОВЕРГНУТО", "text":"1-2 предложения", "source_ids":[1]}}
  ],
  "legal": "кратко только если есть значимое юридическое изменение; иначе 'Без существенных изменений.'",
  "practice": "кратко о подтвержденной практике военкоматов/регионов; если надежных данных нет, так и скажи",
  "isw": "кратко о свежей оценке ISW, только если есть соответствующий источник; иначе 'Новых данных ISW в доказательной выборке нет.'",
  "assessment": {{
    "started": "ДА|НЕТ|НЕЯСНО — короткое обоснование",
    "near_term": "НИЗКИЙ|УМЕРЕННЫЙ|ПОВЫШЕННЫЙ|ВЫСОКИЙ — короткое обоснование",
    "staffing": "НИЗКОЕ|УМЕРЕННОЕ|ВЫСОКОЕ — короткое обоснование",
    "infrastructure": "НИЗКАЯ|СРЕДНЯЯ|ВЫСОКАЯ — короткое обоснование",
    "large_wave_decision": "ЕСТЬ ДОКАЗАТЕЛЬСТВА|НЕТ ДОКАЗАТЕЛЬСТВ|НЕЯСНО — короткое обоснование"
  }},
  "source_ids": [1,2,3]
}}

Не более 6 items. Предпочитай official/law/ISW/Reuters/AP/BBC. Если существенных новых подтвержденных данных нет — short должен прямо это сказать, а items должны быть короткими, без искусственного раздувания.

EVIDENCE:
{json.dumps(compact, ensure_ascii=False)}
""".strip()


def validate_draft(draft: Dict[str, Any], evidence: List[Dict[str, Any]]) -> List[str]:
    issues: List[str] = []
    valid_ids = {int(item["id"]) for item in evidence}
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
    top_ids = draft.get("source_ids") or []
    for raw in top_ids:
        try:
            idx = int(raw)
            if idx not in valid_ids:
                issues.append("unknown_top_source_id")
            else:
                used_ids.add(idx)
        except Exception:
            issues.append("bad_top_source_id")

    generated = " ".join(
        clean(value)
        for value in [
            draft.get("headline"),
            draft.get("short"),
            draft.get("legal"),
            draft.get("practice"),
            draft.get("isw"),
            json.dumps(draft.get("assessment") or {}, ensure_ascii=False),
            *[json.dumps(item, ensure_ascii=False) for item in items],
        ]
    )
    evidence_text = " ".join(item["title"] + " " + item["summary"] for item in evidence)
    generated_numbers = set(re.findall(r"\b\d+(?:[,.]\d+)?\b", generated))
    source_numbers = set(re.findall(r"\b\d+(?:[,.]\d+)?\b", evidence_text))
    now = datetime.now(TZ)
    source_numbers |= {str(now.day), str(now.month), str(now.year)}
    invented = generated_numbers - source_numbers
    if invented:
        issues.append("invented_numbers:" + ",".join(sorted(invented)))
    if not used_ids:
        issues.append("no_sources_used")
    return issues


def verify_draft(draft: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    prompt = f"""
Ты независимый фактчекер. Проверь проект Telegram-сводки ТОЛЬКО против EVIDENCE. Любой факт, которого нет в EVIDENCE, является ошибкой. Особо строго проверь утверждения о запуске мобилизации, массовых повестках, квотах, законах, конкретных числах людей и выводы о неизбежности после выборов. Если проект можно безопасно исправить, верни corrected с полностью исправленным JSON той же структуры. Верни только JSON:
{{"approved":true,"issues":[],"corrected":null}}
или
{{"approved":false,"issues":["..."],"corrected":{{...полный исправленный проект...}}}}

DRAFT:
{json.dumps(draft, ensure_ascii=False)}

EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)}
""".strip()
    result = parse_json(
        openrouter(
            [
                {"role": "system", "content": "Ты строгий фактчекер. Не добавляй внешних знаний. Возвращай только JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2600,
        )
    )
    if result.get("approved") is True:
        return draft
    corrected = result.get("corrected")
    if isinstance(corrected, dict):
        return corrected
    raise RuntimeError("fact checker rejected draft without correction: " + str(result.get("issues"))[:700])


def format_message(draft: Dict[str, Any], evidence: List[Dict[str, Any]], mode: str) -> str:
    by_id = {int(item["id"]): item for item in evidence}
    label = "УТРЕННЯЯ" if mode == "morning" else "ВЕЧЕРНЯЯ"
    parts = [
        f"🇷🇺 <b>МОБИЛИЗАЦИЯ РФ — {label} СВОДКА</b>",
        "",
        f"<b>{html.escape(clean(draft.get('headline')))}</b>",
        html.escape(clean(draft.get("short"))),
    ]
    for item in (draft.get("items") or [])[:6]:
        status = html.escape(clean(item.get("status")))
        text = html.escape(clean(item.get("text")))
        parts += ["", f"<b>{status}</b> — {text}"]

    parts += ["", "<b>Юридические изменения</b>", html.escape(clean(draft.get("legal")))]
    parts += ["", "<b>Военкоматы и регионы</b>", html.escape(clean(draft.get("practice")))]
    parts += ["", "<b>ISW / сильные источники</b>", html.escape(clean(draft.get("isw")))]

    assessment = draft.get("assessment") or {}
    parts += [
        "",
        "<b>Текущая оценка</b>",
        "🟢/🔴 Запуск новой волны: " + html.escape(clean(assessment.get("started"))),
        "🟡 Риск в ближайшие месяцы: " + html.escape(clean(assessment.get("near_term"))),
        "🟠 Кадровое давление: " + html.escape(clean(assessment.get("staffing"))),
        "🟠 Инфраструктурная готовность: " + html.escape(clean(assessment.get("infrastructure"))),
        "🔎 Решение о крупной волне: " + html.escape(clean(assessment.get("large_wave_decision"))),
    ]

    source_ids = []
    for raw in draft.get("source_ids") or []:
        try:
            idx = int(raw)
        except Exception:
            continue
        if idx in by_id and idx not in source_ids:
            source_ids.append(idx)
    if len(source_ids) < 3:
        for item in draft.get("items") or []:
            for raw in item.get("source_ids") or []:
                try:
                    idx = int(raw)
                except Exception:
                    continue
                if idx in by_id and idx not in source_ids:
                    source_ids.append(idx)
                if len(source_ids) >= 5:
                    break
            if len(source_ids) >= 5:
                break
    parts += ["", "<b>Источники</b>"]
    for idx in source_ids[:5]:
        source = by_id[idx]
        url = html.escape(source["url"], quote=True)
        name = html.escape(clean(source["source"]))
        title = html.escape(clean(source["title"])[:120])
        parts.append(f"• <a href=\"{url}\">{name}: {title}</a>")

    message = "\n".join(parts).strip()
    if len(message) > 4000:
        # Preserve the assessment and sources; first shrink item prose.
        short_items = draft.copy()
        short_items["items"] = [
            {**item, "text": clean(item.get("text"))[:220]}
            for item in (draft.get("items") or [])[:4]
        ]
        return format_message(short_items, evidence, mode) if len(short_items["items"]) < len(draft.get("items") or []) else message[:3990]
    return message


def send_telegram(text: str) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not channel:
        raise RuntimeError("Telegram secrets are missing")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": channel,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=45,
    )
    if response.status_code >= 400:
        raise RuntimeError("Telegram HTTP error: " + response.text[:900])
    payload = response.json()
    if payload.get("ok") is not True:
        raise RuntimeError("Telegram API error: " + str(payload)[:900])
    return payload


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    mode = mode_now()
    evidence = collect_evidence()
    if len(evidence) < 6:
        raise RuntimeError(f"insufficient evidence: {len(evidence)} items")

    draft = parse_json(
        openrouter(
            [
                {"role": "system", "content": "Ты доказательно-ориентированный редактор. Не используй знания вне предоставленного массива источников. Возвращай только JSON."},
                {"role": "user", "content": draft_prompt(evidence, mode)},
            ]
        )
    )
    issues = validate_draft(draft, evidence)
    if issues:
        print("draft structural issues:", issues, flush=True)
        draft = verify_draft(draft, evidence)
    else:
        draft = verify_draft(draft, evidence)

    final_issues = validate_draft(draft, evidence)
    if final_issues:
        raise RuntimeError("final digest validation failed: " + "; ".join(final_issues))

    message = format_message(draft, evidence, mode)
    result = send_telegram(message)
    telegram_result = result.get("result") or {}

    state = load_state()
    state.update(
        {
            "version": "mobilization-digest-v1",
            "last_run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_run_sakhalin": datetime.now(TZ).isoformat(timespec="seconds"),
            "mode": mode,
            "status": "ok",
            "telegram_message_id": telegram_result.get("message_id"),
            "evidence_count": len(evidence),
            "evidence_hash": hashlib.sha256(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "headline": clean(draft.get("headline")),
            "source_ids": draft.get("source_ids") or [],
        }
    )
    save_state(state)
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"mobilization digest failed: {exc}", file=sys.stderr, flush=True)
        raise
