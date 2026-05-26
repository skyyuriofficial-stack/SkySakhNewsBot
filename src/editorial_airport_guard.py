# Guard for routine Russian airport operational notices.
# Blocks repeated airport posts and prevents them from being published as geopolitics.

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

QUEUE_FILE = Path("editorial_queue.json")
STATE_FILE = Path("state.json")
SAKH_TZ = timezone(timedelta(hours=11))

CATEGORY_INCIDENTS = "🇷🇺 РФ / происшествия"
CATEGORY_GEOPOLITICS = "🧭 Геополитика"

AIRPORT_TERMS = [
    "аэропорт", "аэродром", "рейс", "рейсы", "самолет", "самолеты", "самолёт", "самолёты",
    "прием и выпуск", "приём и выпуск", "воздушное пространство", "росавиац", "псков",
]

ROUTINE_TERMS = [
    "ограничения", "ограничили", "ввели", "введены", "сняли", "сняты", "временно",
    "приостанов", "возобнов", "не принимает", "не выпускает", "закрыт", "закрыли",
]

MAJOR_IMPACT_TERMS = [
    "погиб", "погибли", "пострадал", "пострадали", "поврежден", "повреждены", "пожар",
    "ущерб", "эвакуац", "десятки рейсов", "сотни пассажиров", "тысячи пассажиров",
    "массовая задержка", "массовые задержки", "аварийная посадка", "экстренная посадка",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def has_any(text: str, terms) -> bool:
    text = norm(text)
    return any(norm(term) in text for term in terms)


def item_text(item: Dict) -> str:
    body = " ".join(str(x) for x in (item.get("body") or []))
    keys = ["title_original", "title_ru", "source_text", "post_text", "edited_post_text", "category", "source"]
    return norm(" ".join(str(item.get(k) or "") for k in keys) + " " + body)


def is_airport_item(item: Dict) -> bool:
    return has_any(item_text(item), AIRPORT_TERMS)


def airport_topic_key_from_text(text: str) -> str:
    text = norm(text)
    if "псков" in text:
        return "airport:pskov"
    return "airport:generic"


def is_routine_without_major_impact(item: Dict) -> bool:
    text = item_text(item)
    return is_airport_item(item) and has_any(text, ROUTINE_TERMS) and not has_any(text, MAJOR_IMPACT_TERMS)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def save_queue(queue: Dict) -> None:
    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def recent_airport_keys(state: Dict) -> set:
    keys = set()
    for post in (state.get("last_posts", []) or [])[-8:]:
        text = norm(" ".join(str(post.get(k) or "") for k in ["title", "caption_plain", "category", "source"]))
        if has_any(text, AIRPORT_TERMS):
            keys.add(airport_topic_key_from_text(text))
    return keys


def main() -> None:
    queue = load_json(QUEUE_FILE, {"version": 1, "items": []})
    state = load_json(STATE_FILE, {})
    seen_keys = recent_airport_keys(state)
    checked = changed = 0

    for item in queue.get("items", []) or []:
        if item.get("status") != "approved":
            continue
        if not is_airport_item(item):
            continue
        checked += 1
        text = item_text(item)
        key = airport_topic_key_from_text(text)
        if item.get("category") == CATEGORY_GEOPOLITICS:
            item["category"] = CATEGORY_INCIDENTS
            item.setdefault("editor_notes", []).append("Airport guard: аэропортовое сообщение РФ не публикуется как геополитика.")
        if key in seen_keys:
            item["status"] = "hold"
            item["airport_guard_at"] = now_utc()
            item.setdefault("editor_notes", []).append("Airport guard: повтор той же аэропортовой темы в коротком окне, публикация остановлена.")
            changed += 1
            continue
        if is_routine_without_major_impact(item):
            item["status"] = "hold"
            item["airport_guard_at"] = now_utc()
            item.setdefault("editor_notes", []).append("Airport guard: рутинное аэропортовое ограничение без крупного последствия, публикация остановлена.")
            changed += 1
            seen_keys.add(key)
            continue
        seen_keys.add(key)

    queue["airport_guard"] = {
        "version": 1,
        "checked": checked,
        "changed": changed,
        "checked_at": now_utc(),
        "checked_at_sakhalin": now_sakh(),
    }
    save_queue(queue)
    print(f"airport-guard-v1: checked={checked}, changed={changed}")


if __name__ == "__main__":
    main()
