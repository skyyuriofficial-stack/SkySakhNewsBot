"""Strict deterministic editorial quality engine for SkySakhNews v12.

The engine does not trust the publisher label or an earlier category. It reads
headline + article lead, determines whether the item is actually newsworthy,
corrects the stream, scores public importance, enforces a rolling editorial mix
and blocks malformed or low-value posts before Telegram.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

VERSION = "quality-v12.0"
ROLLING_WINDOW = 20

# Original editorial proportions requested for the channel.
TARGET_COUNTS: Dict[str, int] = {
    "local": 6,       # 30%
    "ru_pol": 4,      # 20%
    "ru_eco": 4,      # 20%
    "ru_safety": 3,   # 15%
    "world": 2,       # 10% (world_ru + geo)
    "it": 1,          # 5%
}

CATEGORY_GROUP = {
    "sakh": "local", "sakh_chp": "local", "sakh_quake": "local",
    "ru_pol": "ru_pol", "ru_eco": "ru_eco",
    "ru_security": "ru_safety", "ru_incident": "ru_safety",
    "world_ru": "world", "geo": "world", "it": "it",
}

MIN_SCORE = {
    "local": 70, "ru_pol": 76, "ru_eco": 76,
    "ru_safety": 78, "world": 80, "it": 80,
}

LOCAL_MARKERS = (
    "сахалин", "южно-сахалин", "корсаков", "холмск", "долинск", "анив",
    "невельск", "поронайск", "углегорск", "макаров", "томари", "смирных",
    "тымовск", "оха", "ноглики", "северо-курильск", "южно-курильск",
    "курильск", "курил", "итуруп", "кунашир", "шикотан", "парамушир",
    "монерон", "сахалинской области", "сахалинская область",
)
RUSSIA_MARKERS = (
    "росси", "рф", "москв", "кремл", "путин", "госдум", "совфед",
    "правительств", "кабмин", "минфин", "центробанк", "цб рф", "мид рф",
    "росстат", "фнс", "росавиац", "минобороны",
)
FOREIGN_MARKERS = (
    "сша", "америк", "трамп", "канада", "мексик", "иран", "израил",
    "китай", "тайван", "нато", "евросоюз", "британ", "франц", "герман",
    "япон", "корея", "украин", "зеленск", "турц", "сири", "ирак",
    "индия", "пакистан", "армени", "азербайдж", "грузия", "молдов",
    "белорус", "казахстан", "бразил", "венесуэл", "оон", "g7", "g20",
    "usa", "canada", "iran", "israel", "china", "nato", "ukraine",
    "japan", "germany", "france", "britain", "united states",
)
WORLD_MEDIA = ("bbc", "reuters", "associated press", "ap news", "guardian")

HISTORY = (
    "в этот день", "день в истории", "календарь событий", "памятная дата",
    "историческая дата", "годовщина", "лет назад", "в 1945 году",
    "в 1941 году", "история праздника",
)
CEREMONY = (
    "наградили", "награждение", "поздравили", "чествовали", "вручили знак",
    "вручили наград", "торжественная церемония", "почтили память",
    "отметили юбилей", "праздничный концерт", "открыли аллею славы",
)
LIFESTYLE = (
    "гороскоп", "рецепт", "головолом", "тест на внимательность",
    "народные приметы", "церковный праздник", "как выбрать", "лайфхак",
    "что приготовить", "куда поехать", "где отдохнуть", "райское место",
    "по карману", "сентябрьский хит", "санаторий", "дача", "курорт",
    "туристический гид", "мода", "красота", "диета", "огород",
)
ADVERTORIAL = (
    "на правах рекламы", "партнерский материал", "партнёрский материал",
    "спецпроект", "акция действует", "скидка", "успейте купить",
    "подробнее на сайте", "первый офис", "совместное исследование",
)
SERVICE_NOTICE = (
    "чтобы вернуть ему вещи", "чтобы вернуть ей вещи", "вернуть документы",
    "вернуть найденные вещи", "разыскивают владельца", "ищут владельца",
    "если вы знаете где находится", "просьба сообщить информацию по телефону",
    "просьба откликнуться", "найден паспорт", "найдены документы",
)
ROUTINE_TRAFFIC = (
    "пьяных", "без прав", "нарушителей гаи", "нарушений пдд", "рейд гибдд",
    "рейд гаи", "за сутки", "профилактические мероприятия",
)
SOFT_EVENTS = (
    "провел совещание", "провёл совещание", "состоялся форум", "открылся форум",
    "прошел форум", "прошёл форум", "круглый стол", "рабочая встреча",
    "посетил выставку", "принял участие", "обсудили перспективы",
)

QUAKE = ("землетряс", "магнитуд", "эпицентр", "сейсм", "цунами", "толчок")
VIOLENT_CRIME = (
    "убийств", "убил", "зарезал", "ранил", "ножев", "удерживал",
    "лишение свободы", "изнасил", "напал", "стрельб", "взяли под стражу",
    "заключили под стражу", "скончалась", "скончался", "погиб", "погибли",
)
INCIDENT = (
    "дтп", "авари", "пожар", "обруш", "крушен", "утон", "пропал без вести",
    "пострад", "травм", "эвакуац", "опрокинул", "сошел с проезжей части",
    "сошёл с проезжей части", "уголовное дело", "мошенн", "выманил",
    "лишилась денег", "лишился денег", "украл", "краж", "наркотик",
    "задержан", "задержали", "обвинение", "под стражу", "медвед",
)
SECURITY = (
    "бпла", "беспилот", "дрон", "пво", "всу", "ракет", "обстрел",
    "воздушная тревога", "воздушная опасность", "теракт", "террорист",
    "диверс", "минобороны", "перехват", "сбили", "атака на регион",
)
DANGEROUS_WEATHER = (
    "шторм", "ураган", "тайфун", "циклон", "метель", "сильный снег",
    "ливень", "опасное явление", "экстренное предупреждение", "наводнен",
    "подтоп", "дым", "задымлен", "запах гари",
)
ROUTINE_WEATHER = ("прогноз погоды", "погода на неделю", "дожди с похолоданием")
OUTAGE = (
    "без света", "без воды", "без горячей воды", "отключат", "отключили",
    "обесточен", "теплоснабжен", "водоснабжен", "электроснабжен",
)
INFRASTRUCTURE = (
    "ввели в эксплуатацию", "запустили", "открыли центр", "открыл центр",
    "расчетно-информационный центр", "расчётно-информационный центр",
    "газификац", "мост", "дорог", "аэропорт", "больниц", "школ",
    "детский сад", "водородные поезда", "коммунальн",
)
POLITICS = (
    "закон", "законопроект", "указ", "постановлен", "выбор", "госдум",
    "совфед", "правительств", "кабмин", "министр", "губернатор",
    "президент", "путин", "кремл", "мид", "санкц", "решение властей",
)
ECONOMY = (
    "центробанк", "цб рф", "ключевая ставка", "инфляц", "бюджет", "минфин",
    "рубл", "трлн", "млрд", "рынок сбережений", "ввп", "налог", "тариф",
    "зарплат", "безработиц", "инвестиц", "экспорт", "импорт", "втб",
    "сбер", "газпром", "роснефт", "мосбирж", "приватизац",
)
IT = (
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini",
    "искусственный интеллект", "нейросет", "nvidia", "amd", "intel",
    "microsoft", "apple", "google", "android", "ios", "кибератак",
    "утечка данных", "чип", "процессор", "робот", "телемедицин",
    "беспилотник в сельском хозяйстве", "особый правовой режим",
)
DIPLOMACY = (
    "отношени", "переговор", "саммит", "соглашен", "посол", "дипломат",
    "позиция токио", "позиция пекин", "позиция вашингтон", "санкц",
)
FRAUD = (
    "мошенн", "выманил", "перевел мошенникам", "перевела мошенникам",
    "лишилась денег", "лишился денег", "безопасный счет", "безопасный счёт",
    "липов инвести", "подделывать голоса",
)
CLICKBAIT = (
    "шок", "срочно", "ужас", "райское", "хит", "по карману",
    "вы не поверите", "трое пьяных", "пять пьяных", "шесть без прав",
    "16 без прав", "почти 100 нарушителей",
)

GRAMMAR_REPLACEMENTS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bудерживал\s+в\s+сожительницу\b", re.I), "удерживал сожительницу"),
    (re.compile(r"\bудерживал\s+в\s+женщину\b", re.I), "удерживал женщину"),
    (re.compile(r"\s+-\s+(?:SakhalinMedia(?:\.ru)?|Интерфакс|ТАСС)\s*$", re.I), ""),
    (re.compile(r"\s*\|\s*SAKH\.ONLINE\s*$", re.I), ""),
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    text = clean(value).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9%+.-]+", " ", text, flags=re.I).strip()


def tokens(value: Any) -> List[str]:
    return re.findall(r"[a-zа-я0-9]+", norm(value), flags=re.I)


def marker_match(text: str, marker: str) -> bool:
    words = tokens(text)
    wanted = tokens(marker)
    if not words or not wanted:
        return False
    width = len(wanted)
    for start in range(len(words) - width + 1):
        window = words[start:start + width]
        if all(word.startswith(prefix) for word, prefix in zip(window, wanted)):
            return True
    return False


def has(text: str, markers: Sequence[str]) -> bool:
    return any(marker_match(text, marker) for marker in markers)


def source_is_world(source: str) -> bool:
    low = norm(source)
    return any(marker in low for marker in WORLD_MEDIA)


def is_russian_text(value: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", value or "")
    if not letters:
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", value or ""))
    return cyr / len(letters) >= 0.72


def sanitize_title(value: Any) -> str:
    title = clean(value)
    for pattern, replacement in GRAMMAR_REPLACEMENTS:
        title = pattern.sub(replacement, title)
    title = re.sub(r"\s+([,.:;!?])", r"\1", title)
    return re.sub(r"\s{2,}", " ", title).strip(" -–—|")


def title_quality(title: str) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    title = clean(title)
    low = norm(title)
    if len(title) < 24:
        issues.append("title_too_short")
    if len(title) > 190:
        issues.append("title_too_long")
    if has(title, CLICKBAIT):
        issues.append("clickbait_title")
    if re.search(r"\b(удерживал|удерживала|ранил|ранила)\s+в\s+(сожительниц|женщин|мужчин)", low):
        issues.append("malformed_government_case")
    if re.search(r"(?:sakhalinmedia|sakh\.online|интерфакс|тасс)\s*$", low):
        issues.append("publisher_suffix_in_title")
    if title.count("!") > 1 or title.count("?") > 1:
        issues.append("sensational_punctuation")
    return not issues, issues


def hard_reject_reason(title: str, lead: str) -> Optional[str]:
    combined = f"{title} {lead}"
    if has(title, HISTORY):
        return "history_calendar_not_current_news"
    if has(title, CEREMONY):
        return "ceremony_or_congratulation"
    if has(combined, LIFESTYLE):
        return "lifestyle_or_seo"
    if has(combined, ADVERTORIAL):
        return "advertorial"
    if has(combined, SERVICE_NOTICE):
        return "service_notice_not_release_news"
    if has(title, ROUTINE_TRAFFIC) and not has(combined, ("погиб", "пострад", "дтп")):
        return "routine_traffic_statistics"
    if has(title, SOFT_EVENTS) and not has(combined, POLITICS + ECONOMY + INFRASTRUCTURE):
        return "soft_event_without_public_consequence"
    return None


def extract_amount_rubles(text: str) -> Optional[float]:
    low = norm(text)
    matches = re.findall(r"(\d+(?:[.,]\d+)?)\s*(млн|миллион|тыс|тысяч|трлн|млрд)?\s*руб", low)
    multiplier = {"": 1, "тыс": 1_000, "тысяч": 1_000, "млн": 1_000_000,
                  "миллион": 1_000_000, "млрд": 1_000_000_000,
                  "трлн": 1_000_000_000_000}
    best = 0.0
    for raw, unit in matches:
        try:
            best = max(best, float(raw.replace(",", ".")) * multiplier.get(unit, 1))
        except ValueError:
            pass
    return best or None


def classify(title: str, lead: str, source: str, current: str = "") -> Optional[str]:
    title = sanitize_title(title)
    combined = f"{title} {lead}"
    local = has(title, LOCAL_MARKERS) or has(lead[:700], LOCAL_MARKERS)
    foreign = has(title, FOREIGN_MARKERS)
    russia = has(title, RUSSIA_MARKERS) or has(lead[:700], RUSSIA_MARKERS)

    if hard_reject_reason(title, lead):
        return None
    if local:
        if has(combined, QUAKE):
            return "sakh_quake"
        if has(combined, VIOLENT_CRIME + INCIDENT + DANGEROUS_WEATHER):
            return "sakh_chp"
        return "sakh"
    if has(title, IT):
        return "it"
    if foreign:
        if source_is_world(source) and russia:
            return "world_ru"
        return "geo"
    if has(title, SECURITY):
        return "ru_security"
    if has(combined, VIOLENT_CRIME) or has(title, INCIDENT):
        return "ru_incident"
    if has(title, ECONOMY):
        return "ru_eco"
    if has(title, POLITICS):
        return "ru_pol"

    if current == "world_ru" and source_is_world(source) and russia:
        return "world_ru"
    if current == "geo" and has(combined, FOREIGN_MARKERS):
        return "geo"
    if current == "it" and has(combined, IT):
        return "it"
    if current == "ru_security" and has(combined, SECURITY):
        return "ru_security"
    if current == "ru_incident" and has(combined, INCIDENT + VIOLENT_CRIME):
        return "ru_incident"
    if current == "ru_eco" and has(combined, ECONOMY):
        return "ru_eco"
    if current == "ru_pol" and has(combined, POLITICS):
        return "ru_pol"
    return None


def subtype(title: str, lead: str, category: str) -> str:
    combined = f"{title} {lead}"
    if has(combined, VIOLENT_CRIME):
        return "violent_crime"
    if has(combined, ("погиб", "погибли", "скончался", "скончалась")):
        return "fatal_incident"
    if has(combined, FRAUD):
        return "fraud"
    if has(title, ROUTINE_TRAFFIC):
        return "routine_traffic"
    if category == "sakh_quake":
        return "earthquake"
    if has(combined, DANGEROUS_WEATHER):
        return "environmental_hazard"
    if has(title, ROUTINE_WEATHER):
        return "routine_weather"
    if has(combined, OUTAGE):
        return "utility_outage"
    if has(combined, INFRASTRUCTURE):
        return "infrastructure"
    if category == "ru_security":
        return "national_security"
    if category == "ru_incident":
        return "national_incident"
    if category == "ru_pol":
        return "politics_law"
    if category == "ru_eco":
        return "economy"
    if category in {"world_ru", "geo"}:
        return "world_diplomacy"
    if category == "it":
        return "technology"
    return "general_local" if category.startswith("sakh") else "general"


def score(title: str, lead: str, source: str, category: str, event: str) -> Tuple[int, List[str]]:
    combined = f"{title} {lead}"
    points = 52
    reasons = ["base:52"]
    additions = [
        (VIOLENT_CRIME, 35, "violent_crime"),
        (("погиб", "погибли", "скончался", "скончалась"), 28, "fatality"),
        (SECURITY, 28, "security"), (QUAKE, 28, "quake"),
        (DANGEROUS_WEATHER, 22, "environmental_hazard"),
        (OUTAGE, 16, "utility_impact"), (INFRASTRUCTURE, 15, "infrastructure"),
        (POLITICS, 17, "politics"), (ECONOMY, 17, "economy"),
        (DIPLOMACY, 17, "diplomacy"), (IT, 18, "technology"),
    ]
    for markers, add, label in additions:
        if has(combined, markers):
            points += add
            reasons.append(f"{label}:+{add}")
    if has(combined, ("тысяч жителей", "тыс жителей", "20 тысяч", "30 домов", "район", "область")):
        points += 8
        reasons.append("public_scale:+8")
    amount = extract_amount_rubles(combined)
    if event == "fraud":
        if amount is not None and amount >= 500_000:
            points += 15
            reasons.append("material_fraud_loss:+15")
        elif amount is not None and amount < 100_000:
            points -= 14
            reasons.append("minor_individual_loss:-14")
        if has(combined, ("новая схема", "подделывать голоса", "массов", "родителей")):
            points += 12
            reasons.append("public_fraud_pattern:+12")
    if event == "routine_traffic":
        points -= 45
        reasons.append("routine_traffic:-45")
    if event == "routine_weather":
        points -= 18
        reasons.append("routine_weather:-18")
    if has(title, CLICKBAIT):
        points -= 20
        reasons.append("clickbait:-20")
    if has(title, SOFT_EVENTS):
        points -= 22
        reasons.append("soft_event:-22")
    source_low = norm(source)
    source_bonus = 4 if any(x in source_low for x in ("reuters", "associated press", "bbc", "interfax", "tass", "тасс")) else 2 if any(x in source_low for x in ("sakhalinmedia", "astv", "sakh online")) else 0
    points += source_bonus
    if source_bonus:
        reasons.append(f"source:+{source_bonus}")
    return max(0, min(100, int(points))), reasons


def review(candidate: Mapping[str, Any], *, title_override: Optional[str] = None,
           body_override: Optional[str] = None) -> Dict[str, Any]:
    source_title = sanitize_title(candidate.get("title"))
    title = sanitize_title(title_override if title_override is not None else source_title)
    lead = clean(body_override if body_override is not None else candidate.get("source_text"))[:1800]
    source = clean(candidate.get("source"))
    current = str(candidate.get("category_key") or "")
    hard = hard_reject_reason(title, lead)
    title_ok, title_issues = title_quality(title)
    category = classify(title, lead, source, current)
    group = CATEGORY_GROUP.get(category or "")
    event = subtype(title, lead, category or "")
    if hard or not title_ok or category is None or group is None:
        return {
            "version": VERSION, "approved": False, "hard_reject": True,
            "reason": hard or (title_issues[0] if title_issues else "no_safe_category"),
            "original_category": current, "corrected_category": category,
            "group": group, "subtype": event, "score": 0,
            "threshold": MIN_SCORE.get(group or "", 100), "title": title,
            "title_issues": title_issues, "score_reasons": [],
        }
    quality, reasons = score(title, lead, source, category, event)
    threshold = MIN_SCORE[group]
    approved = quality >= threshold
    return {
        "version": VERSION, "approved": approved, "hard_reject": False,
        "reason": "approved" if approved else "quality_below_threshold",
        "original_category": current, "corrected_category": category,
        "group": group, "subtype": event, "score": quality,
        "threshold": threshold, "title": title, "title_issues": title_issues,
        "score_reasons": reasons,
    }


def review_history_post(post: Mapping[str, Any]) -> Dict[str, Any]:
    if post.get("deleted_at") or post.get("post_publish_status") == "deleted":
        return {"approved": False, "reason": "deleted_post"}
    return review({
        "title": post.get("source_title") or post.get("title"),
        "source_text": post.get("source_text_excerpt") or "",
        "source": post.get("source"),
        "category_key": post.get("category_key"),
    })


def balance(state: Mapping[str, Any]) -> Dict[str, Any]:
    posts = [p for p in (state.get("last_posts") or []) if isinstance(p, dict)][-ROLLING_WINDOW:]
    counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    rejected_history: List[Dict[str, Any]] = []
    for post in posts:
        result = review_history_post(post)
        if not result.get("approved"):
            rejected_history.append({"title": clean(post.get("title"))[:180], "reason": result.get("reason")})
            continue
        if result.get("group"):
            counts[result["group"]] += 1
        if result.get("subtype"):
            subtype_counts[result["subtype"]] += 1
    deficits = {k: max(0, v - counts.get(k, 0)) for k, v in TARGET_COUNTS.items()}
    overages = {k: max(0, counts.get(k, 0) - v) for k, v in TARGET_COUNTS.items()}
    return {
        "version": VERSION, "window": ROLLING_WINDOW, "targets": dict(TARGET_COUNTS),
        "percentages": {k: round(v * 100 / ROLLING_WINDOW) for k, v in TARGET_COUNTS.items()},
        "counts": {k: counts.get(k, 0) for k in TARGET_COUNTS},
        "deficits": deficits, "overages": overages,
        "subtype_counts": dict(subtype_counts), "rejected_history": rejected_history[-20:],
    }


def compact(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "version": result.get("version") or VERSION,
        "approved": bool(result.get("approved")), "reason": result.get("reason"),
        "original_category": result.get("original_category"),
        "corrected_category": result.get("corrected_category"),
        "group": result.get("group"), "subtype": result.get("subtype"),
        "score": int(result.get("score") or 0), "threshold": int(result.get("threshold") or 0),
        "priority": int(result.get("priority") or 0), "title": result.get("title"),
        "title_issues": list(result.get("title_issues") or [])[:8],
        "score_reasons": list(result.get("score_reasons") or [])[:12],
    }


def _priority(result: Mapping[str, Any], snapshot: Mapping[str, Any]) -> int:
    group = str(result.get("group") or "")
    target = max(1, TARGET_COUNTS.get(group, 1))
    deficit = int((snapshot.get("deficits") or {}).get(group, 0))
    overage = int((snapshot.get("overages") or {}).get(group, 0))
    return int(result.get("score") or 0) + round(38 * deficit / target) - 18 * overage


def select(state: Mapping[str, Any], candidates: Sequence[Dict[str, Any]],
           category_map: Mapping[str, Tuple[str, str]], limit: int = 2) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    snapshot = balance(state)
    approved: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    by_url: Dict[str, Dict[str, Any]] = {}
    recent_subtypes = snapshot.get("subtype_counts") or {}
    subtype_caps = {"fraud": 2, "routine_weather": 1, "infrastructure": 3, "national_incident": 2}

    for candidate in candidates:
        result = review(candidate)
        event = result.get("subtype")
        cap = subtype_caps.get(event)
        if result.get("approved") and cap is not None and int(recent_subtypes.get(event, 0)) >= cap:
            if event not in {"violent_crime", "fatal_incident", "environmental_hazard", "earthquake"}:
                result["approved"] = False
                result["reason"] = "subtype_quota_exhausted"
        if result.get("approved"):
            category = result["corrected_category"]
            if category not in category_map:
                result["approved"] = False
                result["reason"] = "unknown_category"
            else:
                old = str(candidate.get("category_key") or "")
                if old != category:
                    candidate["_quality_v12_reclass"] = (old, category)
                    candidate["category_key"] = category
                    candidate["category"], candidate["footer"] = category_map[category]
                    candidate["_editorial_prechecked"] = False
                    if candidate.get("topic_cluster"):
                        candidate["topic_cluster"] = category + ":" + str(candidate["topic_cluster"]).split(":", 1)[-1]
                result["priority"] = _priority(result, snapshot)
                candidate["_quality_v12"] = compact(result)
                approved.append(candidate)
        if not result.get("approved"):
            candidate["_quality_v12"] = compact(result)
            rejected.append(candidate)
        by_url[str(candidate.get("url") or candidate.get("title_hash") or len(by_url))] = compact(result)

    approved.sort(key=lambda c: (-int((c.get("_quality_v12") or {}).get("priority") or 0), -int((c.get("_quality_v12") or {}).get("score") or 0), str(c.get("published_at") or "")))
    selected: List[Dict[str, Any]] = []
    used_groups: set[str] = set()
    used_sources: set[str] = set()
    used_clusters: set[str] = set()
    group_order = sorted(TARGET_COUNTS, key=lambda group: (-int((snapshot.get("deficits") or {}).get(group, 0)), int((snapshot.get("counts") or {}).get(group, 0)), -TARGET_COUNTS[group]))
    for group in group_order:
        if len(selected) >= limit:
            break
        pool = [c for c in approved if (c.get("_quality_v12") or {}).get("group") == group]
        if not pool:
            continue
        choice = next((c for c in pool if clean(c.get("source")) not in used_sources), pool[0])
        selected.append(choice)
        used_groups.add(group)
        used_sources.add(clean(choice.get("source")))
        if choice.get("topic_cluster"):
            used_clusters.add(str(choice["topic_cluster"]))
    for candidate in approved:
        if len(selected) >= limit:
            break
        if candidate in selected:
            continue
        metadata = candidate.get("_quality_v12") or {}
        group = str(metadata.get("group") or "")
        cluster = str(candidate.get("topic_cluster") or "")
        source = clean(candidate.get("source"))
        if group in used_groups and any(c for c in approved if c not in selected and (c.get("_quality_v12") or {}).get("group") not in used_groups):
            continue
        if cluster and cluster in used_clusters:
            continue
        if source in used_sources and any(clean(c.get("source")) not in used_sources for c in approved if c not in selected):
            continue
        selected.append(candidate)
        used_groups.add(group)
        used_sources.add(source)
        if cluster:
            used_clusters.add(cluster)
    ordered = selected + [c for c in approved if c not in selected]
    for index, candidate in enumerate(ordered):
        candidate["_quality_v12_order"] = index
        candidate["_quality_v12"]["slot"] = index + 1 if index < limit else "backup"
    rejected_by_reason = Counter((c.get("_quality_v12") or {}).get("reason") or "unknown" for c in rejected)
    report = {
        "version": VERSION, "balance_before": snapshot,
        "candidate_count": len(candidates), "approved_count": len(approved),
        "rejected_count": len(rejected), "rejected_by_reason": dict(rejected_by_reason),
        "selected": [{
            "slot": (c.get("_quality_v12") or {}).get("slot"),
            "title": sanitize_title(c.get("title")), "source": c.get("source"),
            "category_key": c.get("category_key"),
            "group": (c.get("_quality_v12") or {}).get("group"),
            "subtype": (c.get("_quality_v12") or {}).get("subtype"),
            "score": (c.get("_quality_v12") or {}).get("score"),
            "priority": (c.get("_quality_v12") or {}).get("priority"),
        } for c in ordered[:10]],
        "by_url": by_url,
    }
    return ordered, report
