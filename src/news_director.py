"""Autonomous news director for SkySakhNews.

The director is the final editorial controller before text generation.  It:
- corrects stream/category from the actual headline and article lead;
- rejects ceremonial, calendar, lifestyle, advertorial and other low-value items;
- scores public significance and seriousness;
- limits repetitive low-value subtypes;
- maintains the originally requested rolling mix: one strong Sakhalin item per
  cycle plus one rotating national/international/IT item;
- records an auditable decision for every candidate.

The deterministic policy is authoritative.  An optional independent LLM batch
review can veto borderline stories but cannot override hard rejects.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import category_reconciler as reconciler
import editorial_gate as gate

VERSION = "director-v1"
ROLLING_WINDOW = 12

# Six scheduled runs x two posts. This is the original operating idea:
# one useful Sakhalin item in each release and one rotating external stream.
TARGET_COUNTS: Dict[str, int] = {
    "local": 6,
    "world_ru": 1,
    "ru_safety": 1,
    "ru_pol": 1,
    "ru_eco": 1,
    "geo": 1,
    "it": 1,
}

SECOND_SLOT_BY_HOUR = {
    7: "world_ru",
    10: "ru_safety",
    13: "ru_pol",
    16: "ru_eco",
    19: "geo",
    22: "it",
}

CATEGORY_GROUP = {
    "sakh": "local",
    "sakh_chp": "local",
    "sakh_quake": "local",
    "world_ru": "world_ru",
    "ru_security": "ru_safety",
    "ru_incident": "ru_safety",
    "ru_pol": "ru_pol",
    "ru_eco": "ru_eco",
    "geo": "geo",
    "it": "it",
}

CATEGORY_BASE = {
    "sakh_quake": 95,
    "sakh_chp": 82,
    "sakh": 55,
    "world_ru": 84,
    "ru_security": 89,
    "ru_incident": 80,
    "ru_pol": 77,
    "ru_eco": 75,
    "geo": 80,
    "it": 72,
}

MIN_SCORE = {
    "local": 62,
    "world_ru": 76,
    "ru_safety": 72,
    "ru_pol": 72,
    "ru_eco": 70,
    "geo": 75,
    "it": 76,
}

SUBTYPE_CAPS = {
    "fraud": 2,
    "traffic_enforcement": 1,
    "weather_forecast": 2,
    "routine_crime": 2,
    "local_infrastructure": 2,
    "corporate_forecast": 1,
}

CALENDAR_HISTORY = (
    "в этот день",
    "день в истории",
    "календарь событий",
    "историческая дата",
    "памятная дата",
    "годовщина",
    "лет назад",
    "в 1945 году",
    "в 1941 году",
    "история праздника",
)

CEREMONY = (
    "наградили",
    "поздравили",
    "вручили наград",
    "вручили знак",
    "торжественная церемония",
    "чествовали",
    "почтили память",
    "отметили юбилей",
    "праздничный концерт",
    "доброволец сахалинской области",
)

LIFESTYLE_PROMO = (
    "райское место",
    "по карману",
    "сентябрьский хит",
    "от 1000 руб",
    "куда поехать",
    "где отдохнуть",
    "лучшие места",
    "не санаторий и не дача",
    "гороскоп",
    "рецепт",
    "народные приметы",
    "церковный праздник",
    "тест на внимательность",
    "головолом",
    "лайфхак",
    "как выбрать",
    "как сэкономить",
    "что приготовить",
)

ADVERTORIAL = (
    "на правах рекламы",
    "партнерский материал",
    "партнёрский материал",
    "спецпроект",
    "акция действует",
    "скидка",
    "успейте купить",
    "подробнее на сайте",
)

FATAL = (
    "погиб",
    "погибли",
    "умер",
    "жертв",
    "смертельн",
)

HARM = (
    "пострад",
    "ранен",
    "травм",
    "лишилась денег",
    "лишился денег",
    "выманил",
    "украден",
    "похитил",
    "мошенн",
)

EMERGENCY = (
    "пожар",
    "авари",
    "дтп",
    "обруш",
    "эвакуац",
    "отключен",
    "без света",
    "без воды",
    "подтоп",
    "наводнен",
    "шторм",
    "ураган",
    "циклон",
    "землетряс",
    "цунами",
)

INFRASTRUCTURE = (
    "открыл центр",
    "открыли центр",
    "ввели в эксплуатацию",
    "запустили",
    "запустил",
    "газификац",
    "мост",
    "дорог",
    "аэропорт",
    "больниц",
    "школ",
    "детский сад",
    "расчетно информационный центр",
    "расчётно информационный центр",
    "коммунальн",
    "водоснабжен",
    "электроснабжен",
    "теплоснабжен",
)

PUBLIC_IMPACT = (
    "жителей",
    "тысяч человек",
    "тыс человек",
    "муниципальн",
    "район",
    "область",
    "регион",
    "населени",
)

OFFICIAL_DECISION = (
    "принял закон",
    "приняла закон",
    "утвердил",
    "утвердили",
    "подписал",
    "ввел",
    "ввели",
    "объявил",
    "решение",
    "постановлен",
    "законопроект",
    "санкц",
    "ограничен",
    "запрет",
    "программа",
)

MACRO_ECONOMY = (
    "втб",
    "сбер",
    "центробанк",
    "цб рф",
    "минфин",
    "инфляц",
    "ключев ставк",
    "рынок сбережений",
    "трлн рублей",
    "ввп",
    "бюджет",
    "газификац",
    "инвестиц",
)

DIPLOMACY = (
    "отношени",
    "переговор",
    "санкц",
    "посол",
    "мид",
    "саммит",
    "договор",
    "соглашен",
    "позици",
    "токио",
    "вашингтон",
    "пекин",
)

WAR_SECURITY = (
    "бпла",
    "беспилот",
    "пво",
    "ракет",
    "обстрел",
    "атака",
    "военн",
    "минобороны",
    "террорист",
    "диверс",
)

IT_MAJOR = (
    "openai",
    "chatgpt",
    "anthropic",
    "google",
    "microsoft",
    "apple",
    "nvidia",
    "amd",
    "кибератак",
    "утечка данных",
    "искусственн интеллект",
    "нейросет",
    "чип",
    "процессор",
)

FRAUD = (
    "мошенн",
    "выманил",
    "перевел деньги",
    "перевела деньги",
    "лишилась денег",
    "лишился денег",
    "безопасный счет",
    "безопасный счёт",
    "липов инвести",
)

TRAFFIC_ENFORCEMENT = (
    "гибдд",
    "гаи",
    "нарушител",
    "без прав",
    "пьяных",
    "рейд",
)

ROUTINE_CRIME = (
    "задержали",
    "задержан",
    "уголовное дело",
    "возбудили дело",
    "суд",
    "нелегальный улов",
    "наркотик",
)

CLICKBAIT = (
    "шок",
    "срочно",
    "ужас",
    "райское",
    "хит",
    "по карману",
    "вы не поверите",
    "трое пьяных, шесть без прав",
)

SOURCE_QUALITY = {
    "reuters": 5,
    "associated press": 5,
    "ap news": 5,
    "bbc": 4,
    "guardian": 4,
    "interfax": 4,
    "tass": 4,
    "тасс": 4,
    "sakhalinmedia": 3,
    "astv": 3,
    "sakh.online": 3,
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    return gate._norm(value)


def _tokens(value: Any) -> List[str]:
    return re.findall(r"[a-zа-я0-9]+", _norm(value), flags=re.I)


def _marker_match(text: str, marker: str) -> bool:
    words = _tokens(text)
    marker_words = _tokens(marker)
    if not words or not marker_words:
        return False
    width = len(marker_words)
    for start in range(len(words) - width + 1):
        window = words[start:start + width]
        if all(word.startswith(prefix) for word, prefix in zip(window, marker_words)):
            return True
    return False


def _has(text: str, markers: Sequence[str]) -> bool:
    return any(_marker_match(text, marker) for marker in markers)


def _hits(text: str, markers: Sequence[str]) -> List[str]:
    return [marker for marker in markers if _marker_match(text, marker)]


def _source_quality(source: str) -> int:
    low = _norm(source)
    return max(
        (score for marker, score in SOURCE_QUALITY.items() if marker in low),
        default=0,
    )


def group_for_category(category_key: Optional[str]) -> Optional[str]:
    return CATEGORY_GROUP.get(str(category_key or ""))


def _source_is_world(source: str) -> bool:
    low = _norm(source)
    return any(marker in low for marker in ("bbc", "reuters", "guardian", "associated press", "ap news"))


def _source_is_russian(source: str) -> bool:
    low = _norm(source)
    return any(marker in low for marker in ("interfax", "tass", "тасс", "sakhalinmedia", "astv", "sakh online"))


def _hard_reject_reason(title: str, lead: str) -> Optional[str]:
    combined = f"{title} {lead}"
    if _has(title, CALENDAR_HISTORY):
        return "calendar_or_archive_not_current_news"
    if _has(title, CEREMONY):
        return "ceremony_or_congratulation_low_value"
    if _has(combined, LIFESTYLE_PROMO):
        return "lifestyle_or_seo_content"
    if _has(combined, ADVERTORIAL):
        return "advertorial_or_promotion"
    return None


def _independent_category(candidate: Mapping[str, Any]) -> Optional[str]:
    """Headline-centred fallback when the lower classifier is inconclusive."""
    title = _clean(candidate.get("title"))
    lead = _clean(candidate.get("source_text"))[:1100]
    source = _clean(candidate.get("source"))
    title_topics = set(gate.infer_topics(title))
    lead_topics = set(gate.infer_topics(lead))
    all_topics = title_topics | lead_topics

    local_title = "local" in title_topics
    local_incident_signal = (
        "incident" in title_topics
        or _has(title, FATAL + HARM + EMERGENCY + ROUTINE_CRIME)
    )

    if local_title:
        if "quake" in title_topics:
            return "sakh_quake"
        if local_incident_signal:
            return "sakh_chp"
        return "sakh"

    if "foreign" in title_topics:
        if _source_is_world(source) and "russia" in all_topics:
            return "world_ru"
        return "geo"

    if "it" in title_topics:
        return "it"

    if "security" in title_topics or _has(title, WAR_SECURITY):
        return "ru_security"

    if "incident" in title_topics or _has(title, FATAL + HARM + EMERGENCY):
        return "ru_incident"

    if "economy" in title_topics or _has(title, MACRO_ECONOMY):
        return "ru_eco"

    if "politics" in title_topics:
        return "ru_pol"

    # A local publisher may syndicate a national item. The publisher's name is
    # not regional evidence; classify the actual headline.
    if _source_is_russian(source):
        if _has(title, DIPLOMACY) and ("russia" in all_topics or "foreign" in all_topics):
            return "geo"
        if _has(title, OFFICIAL_DECISION):
            return "ru_pol"

    return None


def corrected_category(candidate: Mapping[str, Any]) -> Optional[str]:
    """Return the final stream key independently from the publisher label."""
    title = _clean(candidate.get("title"))
    lead = _clean(candidate.get("source_text"))[:1100]

    if _hard_reject_reason(title, lead):
        return None

    proposed = reconciler.suggest_category(dict(candidate))
    independent = _independent_category(candidate)

    current = str(candidate.get("category_key") or "")
    title_topics = set(gate.infer_topics(title))

    # Never keep a local stream when the headline has no local geography.
    if current in {"sakh", "sakh_chp", "sakh_quake"} and "local" not in title_topics:
        if independent:
            return independent
        return None

    # A generic geo result must have an actual foreign subject in the title.
    if current == "geo" and "foreign" not in title_topics:
        if independent:
            return independent
        return None

    # Prefer the independent headline interpretation when it exposes a more
    # specific stream than a generic local label.
    if independent and independent != proposed:
        if current in {"sakh", "geo"} or proposed in {None, "sakh", "geo"}:
            return independent

    return independent or proposed


def _event_subtype(title: str, lead: str, category_key: str) -> str:
    combined = f"{title} {lead}"

    if _has(combined, FRAUD):
        return "fraud"
    if _has(title, TRAFFIC_ENFORCEMENT) and not _has(title, FATAL + HARM):
        return "traffic_enforcement"
    if _has(combined, FATAL):
        return "fatal_incident"
    if category_key == "sakh_quake":
        return "earthquake"
    if "weather" in gate.infer_topics(title):
        if _has(title, ("опасн", "предупрежд", "шторм", "ураган", "циклон", "ливен", "метел")):
            return "severe_weather"
        return "weather_forecast"
    if _has(combined, INFRASTRUCTURE):
        return "local_infrastructure" if category_key.startswith("sakh") else "infrastructure_policy"
    if category_key == "ru_security" or _has(combined, WAR_SECURITY):
        return "war_security"
    if category_key in {"ru_incident", "sakh_chp"} and _has(combined, TRAFFIC_ENFORCEMENT):
        return "traffic_incident"
    if category_key in {"ru_incident", "sakh_chp"} and _has(combined, ROUTINE_CRIME):
        return "routine_crime"
    if category_key == "ru_eco" and _has(combined, ("прогноз", "ожидает", "вырастет", "сбережен")):
        return "corporate_forecast"
    if category_key == "ru_eco":
        return "economy_policy"
    if category_key == "ru_pol":
        return "political_decision"
    if category_key in {"geo", "world_ru"}:
        return "diplomacy"
    if category_key == "it":
        return "technology"
    return "local_public_interest" if category_key.startswith("sakh") else "general"


def _score(candidate: Mapping[str, Any], category_key: str, subtype: str) -> Tuple[int, List[str]]:
    title = _clean(candidate.get("title"))
    lead = _clean(candidate.get("source_text"))[:1400]
    combined = f"{title} {lead}"
    score = CATEGORY_BASE.get(category_key, 50)
    reasons = [f"base:{score}"]

    if _has(combined, FATAL):
        score += 16
        reasons.append("fatal_or_casualties:+16")
    elif _has(combined, HARM):
        score += 8
        reasons.append("harm_or_loss:+8")

    if _has(combined, EMERGENCY):
        score += 10
        reasons.append("emergency:+10")

    if _has(combined, INFRASTRUCTURE):
        score += 13
        reasons.append("infrastructure:+13")
        if _has(combined, PUBLIC_IMPACT):
            score += 7
            reasons.append("public_impact:+7")

    if _has(combined, OFFICIAL_DECISION):
        score += 8
        reasons.append("official_decision:+8")

    if category_key == "ru_eco" and _has(combined, MACRO_ECONOMY):
        score += 9
        reasons.append("macro_economy:+9")

    if category_key in {"geo", "world_ru"} and _has(combined, DIPLOMACY):
        score += 8
        reasons.append("diplomacy:+8")

    if category_key == "it" and _has(combined, IT_MAJOR):
        score += 8
        reasons.append("major_it:+8")

    if subtype == "traffic_enforcement":
        score += 5
        reasons.append("local_public_safety:+5")

    source_bonus = _source_quality(_clean(candidate.get("source")))
    if source_bonus:
        score += source_bonus
        reasons.append(f"source_quality:+{source_bonus}")

    if _has(title, CLICKBAIT):
        score -= 12
        reasons.append("clickbait:-12")

    if subtype == "corporate_forecast":
        score -= 3
        reasons.append("forecast_not_decision:-3")

    original_score = candidate.get("score")
    try:
        source_rank = max(0, min(8, int(float(original_score)) // 20))
    except Exception:
        source_rank = 0
    if source_rank:
        score += source_rank
        reasons.append(f"collector_rank:+{source_rank}")

    return max(0, min(100, int(score))), reasons


def review_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    title = _clean(candidate.get("title"))
    lead = _clean(candidate.get("source_text"))[:1400]
    original_category = str(candidate.get("category_key") or "")
    hard_reason = _hard_reject_reason(title, lead)

    if hard_reason:
        return {
            "approved": False,
            "hard_reject": True,
            "reason": hard_reason,
            "original_category": original_category,
            "corrected_category": None,
            "group": None,
            "seriousness": 0,
            "subtype": hard_reason,
            "needs_ai_review": False,
            "risks": [hard_reason],
        }

    category_key = corrected_category(candidate)
    if not category_key or category_key not in CATEGORY_GROUP:
        return {
            "approved": False,
            "hard_reject": True,
            "reason": "no_valid_news_stream",
            "original_category": original_category,
            "corrected_category": None,
            "group": None,
            "seriousness": 0,
            "subtype": "offtopic",
            "needs_ai_review": False,
            "risks": ["no_valid_news_stream"],
        }

    group = group_for_category(category_key)
    subtype = _event_subtype(title, lead, category_key)
    score, reasons = _score(candidate, category_key, subtype)
    threshold = MIN_SCORE[group]

    risks: List[str] = []
    if original_category != category_key:
        risks.append(f"category_corrected:{original_category or '-'}->{category_key}")
    if score < threshold + 7:
        risks.append("borderline_importance")
    if subtype in {"corporate_forecast", "traffic_enforcement", "routine_crime"}:
        risks.append("routine_or_repetitive_type")

    return {
        "approved": score >= threshold,
        "hard_reject": False,
        "reason": "approved" if score >= threshold else "importance_below_threshold",
        "original_category": original_category,
        "corrected_category": category_key,
        "group": group,
        "seriousness": score,
        "threshold": threshold,
        "subtype": subtype,
        "needs_ai_review": score < threshold + 7 or bool(risks),
        "risks": risks,
        "score_reasons": reasons,
    }


def _legacy_post_review(post: Mapping[str, Any]) -> Dict[str, Any]:
    stored = post.get("news_director")
    if isinstance(stored, dict) and stored.get("version") == VERSION:
        return dict(stored)

    candidate = {
        "title": post.get("title"),
        "source_text": post.get("source_text") or "",
        "source": post.get("source"),
        "url": post.get("url"),
        "category_key": post.get("category_key"),
        "score": 0,
    }
    review = review_candidate(candidate)
    review["retrospective"] = True
    return review


def balance_snapshot(state: Mapping[str, Any], *, window: int = ROLLING_WINDOW) -> Dict[str, Any]:
    posts = [post for post in (state.get("last_posts") or []) if isinstance(post, dict)][-window:]

    counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    anomalies: List[Dict[str, Any]] = []

    for post in posts:
        review = _legacy_post_review(post)
        if not review.get("approved"):
            anomalies.append({
                "title": _clean(post.get("title"))[:180],
                "category_key": post.get("category_key"),
                "reason": review.get("reason"),
                "corrected_category": review.get("corrected_category"),
            })
            continue

        group = review.get("group") or group_for_category(
            review.get("corrected_category") or post.get("category_key")
        )
        if group:
            counts[str(group)] += 1
        subtype = review.get("subtype")
        if subtype:
            subtype_counts[str(subtype)] += 1

    deficits = {
        group: max(0, target - counts.get(group, 0))
        for group, target in TARGET_COUNTS.items()
    }
    overages = {
        group: max(0, counts.get(group, 0) - target)
        for group, target in TARGET_COUNTS.items()
    }

    return {
        "window": window,
        "targets": dict(TARGET_COUNTS),
        "counts": {group: counts.get(group, 0) for group in TARGET_COUNTS},
        "deficits": deficits,
        "overages": overages,
        "subtype_counts": dict(subtype_counts),
        "retrospective_anomalies": anomalies[-12:],
        "valid_posts_counted": sum(counts.values()),
    }


def scheduled_second_group(now: Optional[datetime]) -> str:
    if now is None:
        return "world_ru"
    hour = int(now.hour)
    nearest = min(SECOND_SLOT_BY_HOUR, key=lambda scheduled: abs(scheduled - hour))
    return SECOND_SLOT_BY_HOUR[nearest]


def _candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    return str(candidate.get("url") or candidate.get("title_hash") or f"candidate-{index}")


def ai_review_prompt(reviews: Sequence[Mapping[str, Any]]) -> str:
    items = []
    for review in reviews[:10]:
        candidate = review["_candidate"]
        items.append({
            "id": review["id"],
            "source": candidate.get("source"),
            "title": candidate.get("title"),
            "article_lead": _clean(candidate.get("source_text"))[:650],
            "deterministic_category": review.get("corrected_category"),
            "deterministic_seriousness": review.get("seriousness"),
            "subtype": review.get("subtype"),
            "risks": review.get("risks"),
        })

    return (
        "Ты независимый главный редактор новостного Telegram-канала. "
        "Проверь только неоднозначные кандидаты. Канал публикует: "
        "1) важные новости Сахалина — ДТП, происшествия, опасную погоду, отключения, "
        "существенную инфраструктуру; 2) крупную политику, безопасность и экономику России; "
        "3) позицию иностранных государств и мировых СМИ о России; "
        "4) серьёзную геополитику; 5) только крупные IT-события. "
        "Не являются новостями канала: награждения, поздравления, памятные даты, "
        "'в этот день', бытовой lifestyle, туризм, рецепты, рекламные и SEO-материалы, "
        "малозначимые церемонии. Издатель SakhalinMedia сам по себе не делает сюжет "
        "сахалинским. Верни только JSON вида "
        '{"reviews":[{"id":"...","newsworthy":true,"importance":0,'
        '"corrected_category":"sakh|sakh_chp|sakh_quake|world_ru|ru_security|'
        'ru_incident|ru_pol|ru_eco|geo|it|null","reason":"..."}]}. '
        "newsworthy=true только для общественно значимого текущего события. "
        "importance ниже 70 означает не публиковать.\n"
        + json.dumps({"items": items}, ensure_ascii=False)
    )


def normalize_ai_reviews(value: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    rows = value.get("reviews")
    if not isinstance(rows, list):
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    allowed = set(CATEGORY_GROUP)
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("id") or "")
        if not identifier:
            continue
        category = row.get("corrected_category")
        if category is not None and category not in allowed:
            category = None
        try:
            importance = int(row.get("importance"))
        except (TypeError, ValueError):
            importance = 0
        result[identifier] = {
            "newsworthy": row.get("newsworthy") is True,
            "importance": max(0, min(100, importance)),
            "corrected_category": category,
            "reason": _clean(row.get("reason"))[:220],
        }
    return result


def _apply_ai_review(review: Dict[str, Any], ai: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if review.get("hard_reject"):
        return review
    if ai is None:
        if review.get("needs_ai_review") and review.get("seriousness", 0) < review.get("threshold", 0) + 4:
            review["approved"] = False
            review["reason"] = "borderline_without_independent_review"
        return review

    review["ai_review"] = dict(ai)
    if not ai.get("newsworthy") or int(ai.get("importance") or 0) < 70:
        review["approved"] = False
        review["reason"] = "independent_director_rejected"
        return review

    suggested = ai.get("corrected_category")
    if (
        suggested
        and suggested in CATEGORY_GROUP
        and group_for_category(suggested) == review.get("group")
    ):
        # The independent reviewer may refine only within the same balance group.
        # It can veto, but cannot move a story to another geography.
        review["corrected_category"] = suggested

    review["seriousness"] = min(
        100,
        round((int(review.get("seriousness") or 0) * 2 + int(ai.get("importance") or 0)) / 3),
    )
    review["approved"] = review["seriousness"] >= review["threshold"]
    review["reason"] = "approved_with_independent_review" if review["approved"] else "importance_below_threshold"
    return review


def _quota_priority(
    review: Mapping[str, Any],
    balance: Mapping[str, Any],
    scheduled_group: str,
    recent_subtypes: Mapping[str, int],
    candidate: Mapping[str, Any],
) -> int:
    group = str(review.get("group") or "")
    score = int(review.get("seriousness") or 0)
    deficit = int((balance.get("deficits") or {}).get(group, 0))
    target = max(1, int(TARGET_COUNTS.get(group, 1)))
    score += round(22 * deficit / target)

    if group == scheduled_group:
        score += 18
    if group == "local":
        score += 12
    if candidate.get("_pending_delivery"):
        score += 8

    subtype = str(review.get("subtype") or "")
    recent_count = int(recent_subtypes.get(subtype, 0))
    cap = SUBTYPE_CAPS.get(subtype)
    if cap is not None:
        if recent_count >= cap and int(review.get("seriousness") or 0) < 90:
            score -= 36
        else:
            score -= recent_count * 8

    return score


def direct_candidates(
    state: Mapping[str, Any],
    candidates: Sequence[Dict[str, Any]],
    *,
    category_map: Mapping[str, Tuple[str, str]],
    now: Optional[datetime] = None,
    ai_reviewer: Optional[
        Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Mapping[str, Any]]]
    ] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    balance = balance_snapshot(state)
    scheduled_group = scheduled_second_group(now)
    reviews: List[Dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        review = review_candidate(candidate)
        review["id"] = _candidate_id(candidate, index)
        review["_candidate"] = candidate
        reviews.append(review)

    ambiguous = [
        review
        for review in reviews
        if not review.get("hard_reject")
        and review.get("needs_ai_review")
        and review.get("approved")
    ][:10]

    ai_results: Mapping[str, Mapping[str, Any]] = {}
    if ambiguous and ai_reviewer is not None:
        try:
            ai_results = ai_reviewer(ambiguous) or {}
        except Exception:
            ai_results = {}

    approved: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    by_url: Dict[str, Dict[str, Any]] = {}
    recent_subtypes = balance.get("subtype_counts") or {}

    for review in reviews:
        review = _apply_ai_review(review, ai_results.get(review["id"]))
        candidate = review.pop("_candidate")
        review["version"] = VERSION

        subtype = str(review.get("subtype") or "")
        subtype_cap = SUBTYPE_CAPS.get(subtype)
        recent_subtype_count = int(recent_subtypes.get(subtype, 0))
        urgent_subtypes = {"fatal_incident", "earthquake", "severe_weather", "war_security"}
        if (
            review.get("approved")
            and subtype_cap is not None
            and recent_subtype_count >= subtype_cap
            and subtype not in urgent_subtypes
        ):
            review["approved"] = False
            review["reason"] = "subtype_quota_exhausted"
            review.setdefault("risks", []).append(
                f"recent_subtype_cap:{subtype}:{recent_subtype_count}/{subtype_cap}"
            )

        category_key = review.get("corrected_category")
        if review.get("approved") and category_key in category_map:
            old = str(candidate.get("category_key") or "")
            if old != category_key:
                candidate["_news_director_reclass"] = (old, category_key)
                candidate["category_key"] = category_key
                candidate["category"], candidate["footer"] = category_map[category_key]
                candidate["_editorial_prechecked"] = False
                if candidate.get("_pending_delivery"):
                    # Stored copy was approved for another category; regenerate it.
                    candidate["_pending_delivery"] = False
                    candidate.pop("_pending_row", None)
                if candidate.get("topic_cluster"):
                    candidate["topic_cluster"] = (
                        category_key + ":" + str(candidate["topic_cluster"]).split(":", 1)[-1]
                    )

            review["priority_score"] = _quota_priority(
                review,
                balance,
                scheduled_group,
                recent_subtypes,
                candidate,
            )
            candidate["_news_director"] = review
            approved.append(candidate)
        else:
            review["approved"] = False
            candidate["_news_director"] = review
            rejected.append(candidate)

        by_url[str(candidate.get("url") or review["id"])] = dict(review)

    approved.sort(
        key=lambda item: (
            -int((item.get("_news_director") or {}).get("priority_score") or 0),
            -int((item.get("_news_director") or {}).get("seriousness") or 0),
            str(item.get("published_at") or ""),
        )
    )

    local = [
        item for item in approved
        if (item.get("_news_director") or {}).get("group") == "local"
    ]
    nonlocal_items = [item for item in approved if item not in local]

    slot_one = local[0] if local else (approved[0] if approved else None)

    available_groups = {
        str((item.get("_news_director") or {}).get("group"))
        for item in nonlocal_items
    }
    desired_group = None
    if scheduled_group in available_groups:
        desired_group = scheduled_group
    elif available_groups:
        deficits = balance.get("deficits") or {}
        desired_group = max(
            available_groups,
            key=lambda group: (
                int(deficits.get(group, 0)),
                TARGET_COUNTS.get(group, 0),
            ),
        )

    slot_two = None
    if desired_group:
        same_subtype = (
            (slot_one.get("_news_director") or {}).get("subtype")
            if slot_one else None
        )
        group_candidates = [
            item for item in nonlocal_items
            if (item.get("_news_director") or {}).get("group") == desired_group
        ]
        slot_two = next(
            (
                item for item in group_candidates
                if (item.get("_news_director") or {}).get("subtype") != same_subtype
            ),
            group_candidates[0] if group_candidates else None,
        )

    if slot_two is None:
        slot_two = next((item for item in approved if item is not slot_one), None)

    ordered: List[Dict[str, Any]] = []
    for slot, item in ((1, slot_one), (2, slot_two)):
        if item is not None and item not in ordered:
            item["_news_director"]["slot"] = slot
            ordered.append(item)

    for item in approved:
        if item not in ordered:
            item["_news_director"]["slot"] = "backup"
            ordered.append(item)

    for position, item in enumerate(ordered):
        item["_news_director_order"] = position

    rejected_by_reason = Counter(
        str((item.get("_news_director") or {}).get("reason") or "unknown")
        for item in rejected
    )

    report = {
        "version": VERSION,
        "rolling_balance_before": balance,
        "scheduled_second_group": scheduled_group,
        "candidate_count": len(candidates),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "rejected_by_reason": dict(rejected_by_reason),
        "ai_review_requested": len(ambiguous),
        "ai_review_received": len(ai_results),
        "selected_preview": [
            {
                "slot": (item.get("_news_director") or {}).get("slot"),
                "title": _clean(item.get("title"))[:180],
                "category_key": item.get("category_key"),
                "group": (item.get("_news_director") or {}).get("group"),
                "subtype": (item.get("_news_director") or {}).get("subtype"),
                "seriousness": (item.get("_news_director") or {}).get("seriousness"),
                "priority_score": (item.get("_news_director") or {}).get("priority_score"),
            }
            for item in ordered[:8]
        ],
        "by_url": by_url,
    }
    return ordered, report


def compact_review(review: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "version": review.get("version") or VERSION,
        "approved": bool(review.get("approved")),
        "reason": review.get("reason"),
        "original_category": review.get("original_category"),
        "corrected_category": review.get("corrected_category"),
        "group": review.get("group"),
        "subtype": review.get("subtype"),
        "seriousness": int(review.get("seriousness") or 0),
        "threshold": int(review.get("threshold") or 0),
        "priority_score": int(review.get("priority_score") or 0),
        "slot": review.get("slot"),
        "risks": [str(value)[:160] for value in (review.get("risks") or [])[:8]],
        "ai_review": review.get("ai_review"),
    }


def finalize_report(state: Mapping[str, Any], report: Mapping[str, Any]) -> Dict[str, Any]:
    result = {key: value for key, value in report.items() if key != "by_url"}
    result["rolling_balance_after"] = balance_snapshot(state)
    return result
