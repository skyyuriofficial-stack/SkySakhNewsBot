# Editorial scope guard for SkySakhNews.
# Blocks formally valid but channel-irrelevant items before publication.

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List

QUEUE_FILE = Path("editorial_queue.json")
SAKH_TZ = timezone(timedelta(hours=11))

PROTECTED_RELEVANCE_TERMS = [
    "россия", "россий", "рф", "москва", "кремль", "путин", "сахалин", "южно-сахалинск",
    "курил", "санкции против россии", "российская нефть", "российский газ", "российский экспорт",
]

FOREIGN_MACRO_TERMS = [
    "греци", "греческ", "стурнарас", "ецб", "европейский центробанк", "европейскому центробанку",
    "европейский центральный банк", "центробанк греции", "глава цб греции", "денежно-кредитн",
    "монетарн", "процентн", "инфляц", "целевой уровень 2", "ставк", "центробанк",
]

SPECULATIVE_COMMENTARY_TERMS = [
    "не исключил", "не исключает", "может", "могут", "если", "будет необходимо", "потребуется",
    "с осторожностью", "вторичные последствия", "может иметь", "привела к", "приведет к",
]

LOW_VALUE_FOREIGN_COUNTRY_TERMS = [
    "греция", "греческ", "бельгия", "нидерланды", "португалия", "исландия", "мальта",
    "люксембург", "австрия", "словения", "словакия", "хорватия", "кипр",
]

HIGH_IMPACT_FOREIGN_TERMS = [
    "погиб", "погибли", "ранен", "ранены", "жертвы", "теракт", "удар", "обстрел", "ракета",
    "ракетн", "атака", "война", "военн", "переворот", "землетряс", "катастроф", "крушение",
    "санкц", "заблокировал пролив", "закрыл пролив", "закрытие ормузского пролива", "сделка",
    "соглашение", "трамп", "иран", "израил", "сша", "китай", "нато", "оон",
]

HABR_LOW_VALUE_TERMS = [
    "habr", "хабр", "memforge", "загрузочная флешка", "флешка", "планка памяти", "планки памяти",
    "ddr", "elitedesk", "сегодня собирал", "стандартный сценарий", "полчаса", "прошивка", "утилита",
    "самодельн", "личный опыт", "разбираемся", "гайд", "руководство", "как ", "инструкция",
    "почему", "история", "ретро", "ретроспектив", "советские программисты", "советск", "ссср",
    "тетрис", "tetris", "pac-man", "pacman", "nintendo", "nes", "gta", "электроника-60",
    "алексей пажитнов", "пажитнов", "в 1984", "1984", "самых влиятельных видеоигр",
]

HABR_MAJOR_TERMS = [
    "уязвимость", "cve", "утечка данных", "кибератака", "rce", "0-day", "zero-day",
    "openai", "google", "microsoft", "apple", "nvidia", "amd", "intel", "санкции",
    "исправили критическую", "критическая уязвимость", "массовый сбой", "утекли данные",
]

HABR_NEVER_GEOPOLITICS_TERMS = [
    "habr", "хабр", "гта", "gta", "тетрис", "tetris", "игра", "видеоигр", "программист",
]

QUAKE_TERMS = ["землетряс", "сейсм", "магнитуд", "камчатк", "курил", "цунами"]
QUAKE_IMPACT_TERMS = [
    "пострадал", "пострадали", "погиб", "погибли", "разрушен", "разрушены", "поврежден",
    "повреждены", "цунами", "угроза цунами", "эвакуац", "афтершок", "магнитудой 6", "магнитудой 7", "магнитудой 8",
]

TARGET_CATEGORIES = {"🧭 Геополитика", "🇷🇺 РФ / экономика", "🌍 Мир о России"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def has_any(text: str, terms: List[str]) -> bool:
    text = norm(text)
    return any(norm(t) in text for t in terms)


def text_blob(item: Dict) -> str:
    keys = [
        "category", "category_hint", "title_ru", "title_original", "source_text", "summary",
        "post_text", "edited_post_text", "url", "source",
    ]
    body = " ".join(str(x) for x in (item.get("body") or []))
    return norm(" ".join(str(item.get(k) or "") for k in keys) + " " + body)


def title_blob(item: Dict) -> str:
    return norm(" ".join([str(item.get("title_ru") or ""), str(item.get("title_original") or "")]))


def is_habr_item(item: Dict) -> bool:
    text = text_blob(item)
    source = norm(item.get("source") or "")
    return "habr" in source or "habr" in text or "хабр" in text


def magnitude_value(text: str) -> float:
    m = re.search(r"магнитуд[а-я\s]*([0-9]+(?:[,.][0-9]+)?)", norm(text))
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(",", "."))
    except Exception:
        return 0.0


def is_foreign_macro_commentary(item: Dict) -> bool:
    text = text_blob(item)
    title = title_blob(item)
    if has_any(text, PROTECTED_RELEVANCE_TERMS):
        return False
    if has_any(title, ["глава цб греции", "цб греции", "центробанк греции", "ецб", "стурнарас"]):
        return True
    if has_any(text, FOREIGN_MACRO_TERMS) and has_any(text, SPECULATIVE_COMMENTARY_TERMS):
        return True
    return False


def is_low_value_foreign_geopolitics(item: Dict) -> bool:
    category = item.get("category") or item.get("category_hint") or ""
    if category not in TARGET_CATEGORIES:
        return False
    text = text_blob(item)
    title = title_blob(item)
    if has_any(text, PROTECTED_RELEVANCE_TERMS):
        return False
    if has_any(title, LOW_VALUE_FOREIGN_COUNTRY_TERMS) and not has_any(text, HIGH_IMPACT_FOREIGN_TERMS):
        return True
    return False


def is_low_value_habr_post(item: Dict) -> bool:
    if not is_habr_item(item):
        return False
    text = text_blob(item)
    category = item.get("category") or item.get("category_hint") or ""
    # Habr must never be published as geopolitics. It is either a major IT/security item or not a channel news item.
    if category == "🧭 Геополитика":
        return True
    if has_any(text, HABR_LOW_VALUE_TERMS):
        return True
    # Habr is allowed only for hard current IT/security/industry news, not evergreen essays.
    if not has_any(text, HABR_MAJOR_TERMS):
        return True
    return False


def is_minor_quake_without_impact(item: Dict) -> bool:
    text = text_blob(item)
    if not has_any(text, QUAKE_TERMS):
        return False
    if has_any(text, QUAKE_IMPACT_TERMS):
        return False
    mag = magnitude_value(text)
    if mag and mag >= 6.0:
        return False
    return True


def reject_reason(item: Dict) -> str | None:
    if is_foreign_macro_commentary(item):
        return "Scope guard: отклонено как нерелевантная иностранная макро/ЕЦБ-аналитика без прямого влияния на РФ/Сахалин или крупного события."
    if is_low_value_foreign_geopolitics(item):
        return "Scope guard: отклонено как низкоприоритетная зарубежная геополитика/политика вне целевых потоков канала."
    if is_low_value_habr_post(item):
        return "Scope guard: отклонено как Habr-лонгрид/ретро/туториал/не новость канала; Habr допускается только для текущих крупных IT/security событий и никогда не как геополитика."
    if is_minor_quake_without_impact(item):
        return "Scope guard: отклонено как слабое землетрясение без ущерба, пострадавших, угрозы цунами или магнитуды 6+."
    return None


def load_queue() -> Dict:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8")) if QUEUE_FILE.exists() else {"version": 1, "items": []}
    except Exception:
        return {"version": 1, "items": []}


def save_queue(queue: Dict) -> None:
    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    queue = load_queue()
    checked = rejected = 0
    for item in queue.get("items", []) or []:
        if item.get("status") not in {"approved", "hold", "pending"}:
            continue
        checked += 1
        reason = reject_reason(item)
        if reason:
            item["status"] = "rejected"
            item["reviewed_at"] = now_utc()
            item["reviewed_by"] = "editorial-scope-guard-v3"
            item.setdefault("editor_notes", []).append(reason)
            rejected += 1
    queue["scope_guard"] = {
        "version": 3,
        "checked": checked,
        "rejected": rejected,
        "checked_at": now_utc(),
        "checked_at_sakhalin": now_sakh(),
        "policy": "block foreign ECB/Greece macro commentary, low-value Habr/retro/essay posts, minor quakes without impact, and weak foreign geopolitics",
    }
    save_queue(queue)
    print(f"editorial-scope-guard-v3: checked={checked}, rejected={rejected}")


if __name__ == "__main__":
    main()
