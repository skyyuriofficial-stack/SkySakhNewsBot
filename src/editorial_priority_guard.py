# Priority guard for SkySakhNews.
# Runs after review/scope guard and before final guard/publish.
# Handles: routine security notices, routine airport notices, repeated airport topics.

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

QUEUE_FILE = Path("editorial_queue.json")
STATE_FILE = Path("state.json")
SAKH_TZ = timezone(timedelta(hours=11))
SECURITY = "🇷🇺 РФ / война и безопасность"
INCIDENTS = "🇷🇺 РФ / происшествия"
GEO = "🧭 Геополитика"

ROUTINE_SECURITY = ["перехвачен", "перехвачены", "уничтожен", "уничтожены", "сбит", "сбито", "сбиты", "беспилотник", "беспилотники", "бпла", "режим ковер", "угроза бпла", "ограничения на прием и выпуск", "ограничения на приём и выпуск"]
AIRPORT = ["аэропорт", "аэродром", "рейс", "рейсы", "самолет", "самолеты", "самолёт", "самолёты", "прием и выпуск", "приём и выпуск", "воздушное пространство", "росавиац", "псков"]
ROUTINE_AIRPORT = ["ограничения", "ограничили", "ввели", "введены", "сняли", "сняты", "временно", "приостанов", "возобнов", "не принимает", "не выпускает", "закрыт", "закрыли"]
REAL_IMPACT = ["погиб", "погибли", "ранен", "ранены", "пострадал", "пострадали", "жертвы", "поврежден", "повреждена", "повреждены", "разрушен", "разрушена", "разрушены", "пожар", "ущерб", "эвакуац", "без света", "без электричества", "массовое отключение", "десятки рейсов", "сотни пассажиров", "тысячи пассажиров", "массовая задержка", "массовые задержки", "аварийная посадка", "экстренная посадка"]
CRITICAL_OBJECTS = ["нпз", "азс", "электростанц", "подстанц", "порт", "завод", "предприятие", "многоквартирный дом", "жилой дом", "энергообъект"]


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh():
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def norm(v):
    return re.sub(r"\s+", " ", str(v or "").lower().replace("ё", "е")).strip()


def has(text, terms):
    text = norm(text)
    return any(norm(t) in text for t in terms)


def item_text(item):
    keys = ["title_original", "title_ru", "source_text", "post_text", "edited_post_text", "category", "source"]
    body = " ".join(str(x) for x in (item.get("body") or []))
    return norm(" ".join(str(item.get(k) or "") for k in keys) + " " + body)


def airport_key(text):
    text = norm(text)
    return "airport:pskov" if "псков" in text else "airport:generic"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def recent_airports(state):
    out = set()
    for post in (state.get("last_posts", []) or [])[-8:]:
        text = norm(" ".join(str(post.get(k) or "") for k in ["title", "caption_plain", "category", "source"]))
        if has(text, AIRPORT):
            out.add(airport_key(text))
    return out


def main():
    if not QUEUE_FILE.exists():
        print("priority-guard: queue file not found")
        return
    queue = load(QUEUE_FILE, {"version": 1, "items": []})
    state = load(STATE_FILE, {})
    seen_airports = recent_airports(state)
    changed = airport_changed = security_changed = 0

    for item in queue.get("items", []) or []:
        if item.get("status") != "approved":
            continue
        text = item_text(item)

        if has(text, AIRPORT):
            if item.get("category") == GEO:
                item["category"] = INCIDENTS
                item.setdefault("editor_notes", []).append("Priority guard: аэропортовое сообщение РФ переклассифицировано из геополитики в происшествия.")
            key = airport_key(text)
            routine_airport = has(text, ROUTINE_AIRPORT) and not has(text, REAL_IMPACT)
            if key in seen_airports or routine_airport:
                item["status"] = "hold"
                item["priority_guard_at"] = now_utc()
                item["priority_guard_at_sakhalin"] = now_sakh()
                item.setdefault("editor_notes", []).append("Priority guard: аэропортовое ограничение без крупного последствия или повтор той же аэропортовой темы; публикация остановлена.")
                airport_changed += 1
                changed += 1
                seen_airports.add(key)
                continue
            seen_airports.add(key)

        if item.get("category") == SECURITY and not has(text, AIRPORT):
            if has(text, ROUTINE_SECURITY) and not (has(text, REAL_IMPACT) or has(text, CRITICAL_OBJECTS)):
                item["status"] = "hold"
                item["priority_guard_at"] = now_utc()
                item["priority_guard_at_sakhalin"] = now_sakh()
                item.setdefault("editor_notes", []).append("Priority guard: сводка ПВО/режимное уведомление без жертв, ущерба, попаданий или крупного сбоя не публикуется автоматически.")
                security_changed += 1
                changed += 1

    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["priority_guard"] = {"version": 3, "changed": changed, "airport_changed": airport_changed, "security_changed": security_changed, "checked_at": now_utc(), "checked_at_sakhalin": now_sakh()}
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"priority-guard-v3: changed={changed}, airport_changed={airport_changed}, security_changed={security_changed}")


if __name__ == "__main__":
    main()
