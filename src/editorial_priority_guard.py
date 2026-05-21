# SkySakhNews editorial priority guard.
# Runs after autonomous review and before final guard/publish.
# Purpose: demote routine security summaries such as "air defense intercepted N drones"
# when there are no casualties, no damage and no major disruption.

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

QUEUE_FILE = Path("editorial_queue.json")
SAKH_TZ = timezone(timedelta(hours=11))

SECURITY_CATEGORY = "🇷🇺 РФ / война и безопасность"

ROUTINE_INTERCEPTION_TERMS = [
    "перехвачен", "перехвачены", "перехватила", "уничтожен", "уничтожены",
    "нейтрализован", "нейтрализованы", "сбит", "сбили", "сбито", "сбиты",
    "дежурными средствами пво", "средствами пво", "минобороны", "беспилотник", "беспилотники", "бпла",
]

WEAK_ALERT_TERMS = [
    "план ковер", "режим ковер", "угроза бпла", "опасность бпла",
    "закрыто воздушное пространство", "закрывали воздушное пространство",
    "ограничения на прием и выпуск", "ограничения на приём и выпуск",
]

REAL_IMPACT_TERMS = [
    "погиб", "погибли", "ранен", "ранены", "пострадал", "пострадали", "жертвы",
    "поврежден", "повреждена", "повреждены", "повреждено", "разрушен", "разрушена", "разрушены",
    "попадание", "прилет", "прилёт", "пожар", "сгорел", "эвакуация", "ущерб",
    "без света", "без электроснабжения", "без электричества", "массовое отключение",
    "отключение электроэнергии", "отключение света", "нарушено электроснабжение",
]

CRITICAL_OBJECT_TERMS = [
    "нпз", "азс", "электростанц", "подстанц", "аэропорт", "порт", "завод", "предприятие",
    "многоквартирный дом", "жилой дом", "объект инфраструктуры", "энергообъект",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def norm(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def blob(item: dict) -> str:
    keys = ["title_original", "title_ru", "source_text", "post_text", "edited_post_text", "category", "source"]
    return norm(" ".join(str(item.get(k) or "") for k in keys))


def has_any(text: str, terms: list[str]) -> bool:
    text = norm(text)
    return any(norm(term) in text for term in terms)


def is_routine_security_without_impact(item: dict) -> bool:
    if item.get("category") != SECURITY_CATEGORY:
        return False
    text = blob(item)
    has_routine_signal = has_any(text, ROUTINE_INTERCEPTION_TERMS) or has_any(text, WEAK_ALERT_TERMS)
    has_real_impact = has_any(text, REAL_IMPACT_TERMS) or has_any(text, CRITICAL_OBJECT_TERMS)
    return has_routine_signal and not has_real_impact


def main() -> None:
    if not QUEUE_FILE.exists():
        print("priority-guard: queue file not found")
        return

    queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    changed = 0

    for item in queue.get("items", []) or []:
        if item.get("status") != "approved":
            continue
        if is_routine_security_without_impact(item):
            item["status"] = "hold"
            item["priority_guard_at"] = now_utc()
            item["priority_guard_at_sakhalin"] = now_sakh()
            item.setdefault("editor_notes", []).append(
                "Priority guard: понижен приоритет. Сводка ПВО/режимное уведомление без жертв, ущерба, попаданий или крупного сбоя не публикуется автоматически."
            )
            changed += 1

    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["priority_guard"] = {
        "changed": changed,
        "checked_at": now_utc(),
        "checked_at_sakhalin": now_sakh(),
    }
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"priority-guard: changed={changed}")


if __name__ == "__main__":
    main()
