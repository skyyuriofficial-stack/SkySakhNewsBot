# Minimum release policy for SkySakhNews.
# Runs after strict review/priority guard and before final guard/publish.
# Purpose: prevent long silent periods when the strict editor approved 0 items.
# It promotes exactly one reserve item only if it is still newsworthy and safe.

import html
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

QUEUE_FILE = Path("editorial_queue.json")
STATE_FILE = Path("state.json")
SAKH_TZ = timezone(timedelta(hours=11))

APPROVE_LIMIT = 1
MAX_AGE_HOURS = 36

FOOTERS = {
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 РФ / война и безопасность": "РФ | ВОЙНА И БЕЗОПАСНОСТЬ",
    "🇷🇺 РФ / экономика": "РФ | ЭКОНОМИКА",
    "🇷🇺 РФ / законы и политика": "РФ | ЗАКОНЫ И ПОЛИТИКА",
    "🧭 Геополитика": "ГЕОПОЛИТИКА",
    "🌐 Мировые IT": "МИРОВЫЕ IT",
    "🎮 Игры / индустрия": "ИГРОВАЯ ИНДУСТРИЯ",
    "📍 Сахалин": "САХАЛИН",
}

TRUSTED_SOURCES = [
    "interfax", "bbc", "guardian", "reuters", "ap news", "associated press",
    "the verge", "ars technica", "eurogamer", "pc gamer",
]

HARD_REJECT_TERMS = [
    "скид", "распродаж", "coupon", "discount", "deal", "sale", "amazon", "walmart", "woot",
    "download", "drivers", "драйвер", "power bank", "free shipping", "promocode", "промокод",
    "обучающая/колоночная", "товарная", "товарный", "партнерский", "партнёрский",
    "туториал", "гайд", "личный опыт", "как я", "как сделать", "как управлять",
    "финальный стоп: approved-пост не русифицирован", "низкой значимости",
]

STRONG_TERMS = [
    "заэс", "аэс", "миниров", "ранен", "ранены", "погиб", "поврежден", "повреждена", "повреждены",
    "пожар", "разруш", "ущерб", "атака", "удар", "обстрел", "отключ", "электроэнерг",
    "санкц", "ставк", "цб", "инфляц", "нефть", "газ", "спг", "китай", "сша", "иран", "израил",
    "openai", "google", "microsoft", "apple", "anthropic", "nvidia", "уязвим", "cve",
]

WAR_TERMS = ["заэс", "аэс", "бпла", "дрон", "атака", "удар", "обстрел", "миниров", "пво", "всу", "ранен", "погиб", "поврежден"]
ECON_TERMS = ["эконом", "банк", "кредит", "ставк", "цб", "инфляц", "нефть", "газ", "спг", "рубл", "экспорт", "импорт", "зерн"]
POLITICS_TERMS = ["госдума", "закон", "сенат", "правительство", "переговор", "визит", "саммит", "мид", "путин", "си цзиньпин"]
IT_TERMS = ["openai", "google", "microsoft", "apple", "anthropic", "nvidia", "уязвим", "cve", "ии", "нейросет"]
GEOPOLITICS_TERMS = ["иран", "израил", "сша", "нато", "ес", "китай", "тайван", "газа", "оон"]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def clean(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("INTERFAX.RU -", " ").replace("Москва.", " ")
    return re.sub(r"\s+", " ", text).strip()


def esc(value: str) -> str:
    return html.escape(str(value or ""), quote=False)


def attr(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def blob(item: Dict) -> str:
    keys = ["title_original", "title_ru", "source_text", "post_text", "edited_post_text", "url", "source", "category", "category_hint"]
    return norm(" ".join(str(item.get(k) or "") for k in keys))


def notes_blob(item: Dict) -> str:
    return norm(" ".join(str(x) for x in item.get("editor_notes", []) or []))


def has_any(text: str, terms: List[str]) -> bool:
    text = norm(text)
    return any(norm(t) in text for t in terms)


def cyrillic_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return 0.0
    cyr = re.findall(r"[А-Яа-яЁё]", text or "")
    return len(cyr) / max(1, len(letters))


def age_hours(item: Dict) -> float:
    raw = item.get("published_at") or item.get("created_at")
    if not raw:
        return 9999.0
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
    except Exception:
        return 9999.0


def split_sentences(text: str) -> List[str]:
    text = clean(text)
    text = re.sub(r"\bМосква\.\s*\d+\s+[а-яА-Я]+\.\s*", "", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    seen = set()
    for part in parts:
        part = clean(part)
        if len(part) < 45:
            continue
        low = norm(part)
        if any(x in low for x in ["читать далее", "subscribe", "sign in", "реклама", "подпис"]):
            continue
        key = re.sub(r"\W+", "", low)[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(part[:360])
        if len(out) >= 2:
            break
    return out


def infer_category(item: Dict) -> str:
    text = blob(item)
    if has_any(text, WAR_TERMS):
        return "🇷🇺 РФ / война и безопасность"
    if has_any(text, ECON_TERMS):
        return "🇷🇺 РФ / экономика"
    if has_any(text, IT_TERMS):
        return "🌐 Мировые IT"
    if has_any(text, GEOPOLITICS_TERMS):
        return "🧭 Геополитика"
    if has_any(text, POLITICS_TERMS):
        return "🇷🇺 РФ / законы и политика"
    return item.get("category") or item.get("category_hint") or "🧭 Геополитика"


def make_post(category: str, title: str, body: List[str], url: str, source: str) -> str:
    footer = FOOTERS.get(category, category)
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source or 'Источник')}</a>"


def safe_candidate(item: Dict) -> bool:
    text = blob(item)
    notes = notes_blob(item)
    source = norm(item.get("source"))
    if item.get("status") not in {"hold", "rejected"}:
        return False
    if age_hours(item) > MAX_AGE_HOURS:
        return False
    if has_any(text + " " + notes, HARD_REJECT_TERMS):
        return False
    if not any(src in source for src in TRUSTED_SOURCES):
        return False
    if not has_any(text, STRONG_TERMS):
        return False
    if cyrillic_ratio(text) < 0.35:
        # Do not auto-release mostly English drafts without a real translator.
        return False
    return True


def rank_item(item: Dict) -> int:
    text = blob(item)
    category = infer_category(item)
    score = 0
    score += {
        "🌍 Мир о России": 900,
        "🇷🇺 РФ / война и безопасность": 850,
        "🧭 Геополитика": 800,
        "🇷🇺 РФ / экономика": 720,
        "🇷🇺 РФ / законы и политика": 650,
        "🌐 Мировые IT": 520,
        "🎮 Игры / индустрия": 120,
    }.get(category, 300)
    for term in STRONG_TERMS:
        if norm(term) in text:
            score += 15
    score -= int(age_hours(item) * 4)
    return score


def promote(item: Dict) -> None:
    category = infer_category(item)
    title = clean(item.get("title_ru") or item.get("title_original") or "")
    body = split_sentences(item.get("source_text") or "")
    if not body:
        body = [clean(x) for x in (item.get("body") or []) if clean(x)][:2]
    if not body:
        raise RuntimeError("reserve item has no usable body")
    post_text = make_post(category, title, body[:2], item.get("url") or "", item.get("source") or "Источник")
    if cyrillic_ratio(post_text) < 0.45:
        raise RuntimeError("reserve item post text is not Russian enough")

    item["status"] = "approved"
    item["category"] = category
    item["title_ru"] = title
    item["body"] = body[:2]
    item["post_text"] = post_text
    item["edited_post_text"] = post_text
    item["reviewed_at"] = now_utc()
    item["reviewed_by"] = "minimum-release-policy"
    item["minimum_release"] = True
    item.setdefault("editor_notes", []).append(
        "Minimum release policy: строгий редактор не нашёл approved, поэтому выбран один безопасный резервный материал, чтобы лента не молчала."
    )


def main() -> None:
    queue = load_json(QUEUE_FILE, {"version": 1, "items": []})
    items = queue.get("items", []) or []
    approved_now = [x for x in items if x.get("status") == "approved"]
    if approved_now:
        print(f"minimum-release: skipped, approved already exists={len(approved_now)}")
        return

    candidates = [x for x in items if safe_candidate(x)]
    candidates.sort(key=rank_item, reverse=True)
    promoted = 0
    errors = []
    for item in candidates:
        try:
            promote(item)
            promoted = 1
            break
        except Exception as exc:
            errors.append(f"{item.get('title_ru') or item.get('title_original')}: {exc}")
            continue

    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["minimum_release"] = {
        "checked_at": now_utc(),
        "checked_at_sakhalin": now_sakh(),
        "candidates": len(candidates),
        "promoted": promoted,
        "errors": errors[-5:],
    }
    save_json(QUEUE_FILE, queue)
    print(f"minimum-release: candidates={len(candidates)}, promoted={promoted}")


if __name__ == "__main__":
    main()
