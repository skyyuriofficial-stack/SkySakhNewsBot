# Minimum release policy for SkySakhNews.
# Conservative fallback: publish at most one reserve item only when strict review produced 0 approved items.
# Uses the same owner-defined stream priorities as editorial_review.

import html
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List

from category_policy import resolve_final_category_from_item, stream_priority

QUEUE_FILE = Path("editorial_queue.json")
SAKH_TZ = timezone(timedelta(hours=11))
MAX_AGE_HOURS = 30

FOOTERS = {
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 РФ / война и безопасность": "РФ | ВОЙНА И БЕЗОПАСНОСТЬ",
    "🇷🇺 РФ / происшествия": "РФ | ПРОИСШЕСТВИЯ",
    "🇷🇺 РФ / экономика": "РФ | ЭКОНОМИКА",
    "🇷🇺 РФ / законы и политика": "РФ | ЗАКОНЫ И ПОЛИТИКА",
    "🧭 Геополитика": "ГЕОПОЛИТИКА",
    "🌐 Мировые IT": "МИРОВЫЕ IT",
    "🎮 Игры / индустрия": "ИГРОВАЯ ИНДУСТРИЯ",
    "📍 Сахалин": "САХАЛИН",
}

TRUSTED_SOURCES = ["interfax", "bbc", "guardian", "reuters", "ap news", "associated press", "the verge", "ars technica"]
HARD_REJECT_TERMS = [
    "скид", "распродаж", "coupon", "discount", "deal", "sale", "amazon", "walmart", "woot", "download", "drivers",
    "драйвер", "power bank", "free shipping", "promocode", "промокод", "товарная", "товарный", "партнерский",
    "туториал", "гайд", "личный опыт", "как я", "как сделать", "как управлять", "обучающая/колоночная",
    "финальный стоп", "низкой значимости", "материал устарел",
]
WEAK_DENIAL_TERMS = [
    "не рассматривается", "не планируется", "не обсуждается", "не стоит на повестке", "пока не рассматривается",
    "пока не планируется", "не ожидается", "не стал комментировать", "отказался комментировать",
    "готовы к сотрудничеству", "заявил о готовности", "выразил готовность", "призвал к", "рассчитывает на",
]
STRONG_TERMS = [
    "заэс", "аэс", "миниров", "ранен", "ранены", "погиб", "погибли", "поврежден", "повреждена", "повреждены",
    "пожар", "разруш", "ущерб", "атака", "удар", "обстрел", "отключ", "электроэнерг", "санкц", "ставк", "цб",
    "инфляц", "нефть", "газ", "спг", "китай", "сша", "иран", "израил", "openai", "google", "microsoft", "apple",
    "anthropic", "nvidia", "уязвим", "cve", "лавина", "спасатели", "без воды", "gta", "rockstar", "witcher"
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def clean(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\bINTERFAX\.RU\s*-\s*", "", text)
    text = re.sub(r"\bМосква\.\s*\d+\s+[а-яА-Я]+\.\s*", "", text)
    return re.sub(r"\s+", " ", text).strip(" -—")


def esc(value: str) -> str:
    return html.escape(str(value or ""), quote=False)


def attr(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def text_blob(item: Dict) -> str:
    keys = ["title_original", "title_ru", "source_text", "body", "url", "source"]
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
    return len(re.findall(r"[А-Яа-яЁё]", text or "")) / max(1, len(letters))


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


def remove_repeated_halves(sentence: str) -> str:
    s = clean(sentence)
    words = s.split()
    if len(words) < 10:
        return s
    for n in range(min(28, len(words) // 2), 5, -1):
        if " ".join(words[:n]).lower() == " ".join(words[n:2*n]).lower():
            return clean(" ".join(words[:n] + words[2*n:]))
    return s


def split_sentences(text: str) -> List[str]:
    text = clean(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out, seen = [], set()
    for part in parts:
        part = remove_repeated_halves(part)
        if len(part) < 55:
            continue
        low = norm(part)
        if any(x in low for x in ["читать далее", "subscribe", "sign in", "реклама", "подпис", "известия"]):
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
    return resolve_final_category_from_item(item)


def make_post(category: str, title: str, body: List[str], url: str, source: str) -> str:
    footer = FOOTERS.get(category, category)
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body) + f"\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source or 'Источник')}</a>"


def safe_candidate(item: Dict) -> bool:
    text = text_blob(item)
    notes = notes_blob(item)
    source = norm(item.get("source"))
    status = item.get("status")
    if status == "rejected" and not has_any(notes, ["в резерве", "ниже текущих приоритетов"]):
        return False
    if status not in {"hold", "rejected"}:
        return False
    if age_hours(item) > MAX_AGE_HOURS:
        return False
    if has_any(text + " " + notes, HARD_REJECT_TERMS):
        return False
    if has_any(text, WEAK_DENIAL_TERMS):
        return False
    if not any(src in source for src in TRUSTED_SOURCES):
        return False
    if not has_any(text, STRONG_TERMS):
        return False
    if cyrillic_ratio(text) < 0.45:
        return False
    return True


def rank_item(item: Dict) -> int:
    text = text_blob(item)
    category = infer_category(item)
    score = stream_priority(category)
    for term in STRONG_TERMS:
        if norm(term) in text:
            score += 15
    score -= int(age_hours(item) * 5)
    return score


def promote(item: Dict) -> None:
    category = infer_category(item)
    title = clean(item.get("title_ru") or item.get("title_original") or "")
    body = split_sentences(item.get("source_text") or "")
    if not body:
        body = [remove_repeated_halves(clean(x)) for x in (item.get("body") or []) if clean(x)][:2]
    if not body:
        raise RuntimeError("reserve item has no usable body")
    post_text = make_post(category, title, body[:2], item.get("url") or "", item.get("source") or "Источник")
    if cyrillic_ratio(post_text) < 0.55:
        raise RuntimeError("reserve item post text is not Russian enough")
    item["status"] = "approved"
    item["category"] = category
    item["stream_priority"] = stream_priority(category)
    item["score"] = rank_item(item)
    item["title_ru"] = title
    item["body"] = body[:2]
    item["post_text"] = post_text
    item["edited_post_text"] = post_text
    item["reviewed_at"] = now_utc()
    item["reviewed_by"] = "minimum-release-policy-v3-owner-priority"
    item["minimum_release"] = True
    item.setdefault("editor_notes", []).append("Minimum release v3: выбран один безопасный резервный материал по owner priority map.")


def main() -> None:
    queue = load_json(QUEUE_FILE, {"version": 1, "items": []})
    items = queue.get("items", []) or []
    if any(x.get("status") == "approved" for x in items):
        print("minimum-release: skipped, approved already exists")
        return
    candidates = [x for x in items if safe_candidate(x)]
    candidates.sort(key=rank_item, reverse=True)
    promoted, errors = 0, []
    for item in candidates:
        try:
            promote(item)
            promoted = 1
            break
        except Exception as exc:
            errors.append(f"{item.get('title_ru') or item.get('title_original')}: {exc}")
    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["minimum_release"] = {
        "version": 3,
        "priority_map": {
            "🌍 Мир о России": 1000,
            "📍 Сахалин": 950,
            "🇷🇺 РФ / война и безопасность": 900,
            "🧭 Геополитика": 820,
            "🇷🇺 РФ / происшествия": 780,
            "🇷🇺 РФ / экономика": 760,
            "🇷🇺 РФ / законы и политика": 700,
            "🌐 Мировые IT": 650,
            "🎮 Игры / индустрия": 600,
        },
        "checked_at": now_utc(),
        "checked_at_sakhalin": now_sakh(),
        "candidates": len(candidates),
        "promoted": promoted,
        "errors": errors[-5:]
    }
    save_json(QUEUE_FILE, queue)
    print(f"minimum-release-v3-owner-priority: candidates={len(candidates)}, promoted={promoted}")


if __name__ == "__main__":
    main()
