"""Independent semantic/editorial gate for SkySakhNews.

The writer never decides whether its own post is safe.  This module verifies:
- generated headline against the source headline and article;
- central claim, modality, numbers and clickbait;
- story category against headline meaning and geography;
- an optional independent AI verdict for translated/rephrased headlines.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

STOPWORDS = {
    "и", "в", "во", "на", "с", "со", "к", "ко", "по", "из", "за", "от", "до", "для",
    "о", "об", "обо", "у", "над", "под", "при", "про", "через", "между", "а", "но", "или",
    "что", "как", "это", "этот", "эта", "эти", "его", "ее", "её", "их", "который", "которая",
    "которые", "после", "перед", "также", "уже", "еще", "ещё", "был", "была", "были", "будет",
    "стало", "стал", "стали", "сообщил", "сообщила", "сообщили", "заявил", "заявила", "заявили",
    "said", "the", "a", "an", "of", "to", "in", "on", "for", "with", "from", "at", "by", "as",
}

LOCAL_MARKERS = (
    "сахалин", "южно-сахалин", "холмск", "корсаков", "долинск", "невельск", "поронайск",
    "углегорск", "оха", "ноглики", "анива", "макаров", "томари", "тымовск", "смирных",
    "александровск-сахалин", "курил", "северо-курильск", "южно-курильск", "итуруп",
    "кунашир", "шикотан", "сахалинской области",
)
WEATHER = (
    "погод", "дожд", "ливн", "осад", "снег", "метел", "циклон", "шторм", "ветер", "туман",
    "мороз", "жар", "температур", "гидромет", "прогноз", "тайфун",
)
QUAKE = ("землетряс", "магнитуд", "эпицентр", "сейсм", "толчк", "толчок", "цунами")
SECURITY = (
    "бпла", "беспилот", "дрон", "пво", "всу", "воздушн тревог", "воздушн опасност",
    "обстрел", "ракет", "минобороны", "росавиац", "план ковер", "план ковёр",
    "террорист", "диверс", "взрывн устройств", "перехват", "сбит", "сбили",
    "военн удар", "нанесли удар", "атака на регион", "атаковали", "боеприпас",
)
INCIDENT = (
    "дтп", "авари", "пожар", "погиб", "смерт", "пострад", "утон", "крушен", "обруш",
    "травм", "происшеств", "убийств", "ранен", "пропал", "розыск", "мчс",
    "следовател", "полици", "прокуратур", "уголовн", "напад", "медвед", "краж",
    "украл", "украли", "задержан", "мошенн", "хищен", "возбудили дело",
)
ECONOMY = (
    "центробанк", "цб рф", "ключев ставк", "инфляц", "бюджет", "минфин", "нефт",
    "газ", "экспорт", "импорт", "пошлин", "рынок", "бирж", "ввп", "налог", "эконом",
    "рубл", "фьючерс", "индекс", "котировк", "тариф",
)
POLITICS = (
    "кремл", "путин", "лавров", "госдум", "совфед", "правительств", "президент",
    "мид рф", "совбез", "законопроект", "выбор", "депутат", "губернатор",
    "министр", "политик", "парламент",
)
IT = (
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini", "нейросет",
    "искусственн интеллект", "nvidia", "amd", "intel", "microsoft", "apple",
    "google", "android", "ios", "linux", "windows", "кибератак", "чип",
    "процессор", "telegram", "технолог", "робот", "semiconductor",
)
FOREIGN = (
    "сша", "америк", "трамп", "канада", "канад", "мексик", "иран", "израил", "китай",
    "тайван", "нато", "евросоюз", "британ", "франц", "герман", "япон", "коре",
    "украин", "зеленск", "турц", "сири", "ирак", "инд", "пакистан", "армени",
    "казахстан", "белорус", "груз", "азербайдж", "молдов", "куб", "white house",
    "usa", "canada", "mexico", "iran", "israel", "china", "taiwan", "nato",
    "ukraine", "japan", "germany", "france", "britain", "turkey", "syria",
)
RUSSIA = (
    "росси", "рф", "москв", "кремл", "путин", "лавров",
    "russia", "russian", "moscow", "kremlin", "putin", "lavrov",
)

WEAK_MODALITY = (
    "может", "могут", "могла", "могло", "возможно", "вероятно", "предполож",
    "ожидается", "ожидают", "планирует", "планируют", "намерен", "намерены",
    "рассматривает", "рассматривают", "обсуждает", "обсуждают", "предлагает",
    "предложил", "хочет", "готовится", "может быть", "не исключил",
)
STRONG_OUTCOME = (
    "ввел", "ввела", "ввели", "введен", "введена", "введены", "принял", "приняла",
    "приняли", "утвердил", "утвердила", "утвердили", "запустил", "запустила",
    "запустили", "начал", "начала", "начали", "подписал", "подписала", "подписали",
    "заключил", "заключили", "состоялся", "состоялась", "произошло", "произошел",
    "произошёл", "решил", "решили", "отменил", "отменили",
)
CLICKBAIT = (
    "шок", "срочно", "ужас", "все в панике", "все в шоке", "катастроф",
    "сенсац", "невероятн", "вы не поверите",
)

CATEGORY_TOPICS = {
    "sakh_quake": {"quake", "local"},
    "sakh_chp": {"incident", "local"},
    "sakh": {"local"},
    "ru_security": {"security"},
    "ru_incident": {"incident"},
    "ru_eco": {"economy"},
    "ru_pol": {"politics"},
    "geo": {"foreign"},
    "world_ru": {"foreign", "russia"},
    "it": {"it"},
}


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _norm(text: Any) -> str:
    value = _clean(text).lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9%+.-]+", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _contains(text: str, markers: Sequence[str]) -> bool:
    low = _norm(text)
    return any(marker in low for marker in markers)


def _contains_ai_abbreviation(text: str) -> bool:
    return bool(re.search(r"(?<![а-яa-z0-9])ии(?![а-яa-z0-9])", _norm(text), flags=re.I))


def _tokens(text: str) -> List[str]:
    result: List[str] = []
    for word in re.findall(r"[a-zа-я0-9]+", _norm(text), flags=re.I):
        if len(word) >= 3 and word not in STOPWORDS and not word.isdigit():
            result.append(word)
    return result


def _stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    if len(word) <= 6:
        return word
    return word[: max(5, min(9, len(word) - 2))]


def _token_supported(token: str, source_tokens: Iterable[str]) -> bool:
    stem = _stem(token)
    return any(
        _stem(other) == stem
        or _stem(other).startswith(stem)
        or stem.startswith(_stem(other))
        for other in source_tokens
    )


def _numbers(text: str) -> Set[str]:
    return {value.replace(",", ".") for value in re.findall(r"\d+(?:[,.]\d+)?", text or "")}


def is_russian_text(text: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return False
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text or ""))
    return cyrillic / len(letters) >= 0.72


def infer_topics(text: str, source_name: str = "", url: str = "") -> Set[str]:
    """Infer subjects from content only.

    source_name/url are accepted for backward compatibility, but publisher
    identity is deliberately ignored: SakhalinMedia is not proof that a story
    is about Sakhalin, and Interfax is not proof that a story is about Russia.
    """
    blob = _clean(text)
    topics: Set[str] = set()
    if _contains(blob, LOCAL_MARKERS):
        topics.add("local")
    if _contains(blob, WEATHER):
        topics.add("weather")
    if _contains(blob, QUAKE):
        topics.add("quake")
    if _contains(blob, SECURITY):
        topics.add("security")
    if _contains(blob, INCIDENT):
        topics.add("incident")
    if _contains(blob, ECONOMY):
        topics.add("economy")
    if _contains(blob, POLITICS):
        topics.add("politics")
    if _contains(blob, IT) or _contains_ai_abbreviation(blob):
        topics.add("it")
    if _contains(blob, FOREIGN):
        topics.add("foreign")
    if _contains(blob, RUSSIA):
        topics.add("russia")
    return topics


def title_source_metrics(
    source_title: str,
    source_text: str,
    generated_title: str,
) -> Tuple[int, int, int]:
    source_headline = _norm(source_title)
    generated = _norm(generated_title)
    if not generated:
        return 0, 0, 0
    if generated == source_headline or generated in source_headline or source_headline in generated:
        return 100, 100, 100

    source_tokens = _tokens(source_title + " " + source_text)
    generated_tokens = _tokens(generated_title)
    headline_tokens = _tokens(source_title)
    if not generated_tokens:
        return 0, 0, 0

    supported = sum(1 for token in generated_tokens if _token_supported(token, source_tokens))
    precision = round(100 * supported / len(generated_tokens))

    if headline_tokens:
        covered = sum(1 for token in headline_tokens if _token_supported(token, generated_tokens))
        coverage = round(100 * covered / len(headline_tokens))
    else:
        coverage = precision

    score = round(0.48 * precision + 0.52 * coverage)
    return max(0, min(100, score)), precision, coverage


def title_source_score(source_title: str, source_text: str, generated_title: str) -> int:
    return title_source_metrics(source_title, source_text, generated_title)[0]


def _modality_issues(source: str, generated_title: str) -> List[str]:
    source_norm = _norm(source)
    generated_norm = _norm(generated_title)
    if not any(marker in source_norm for marker in WEAK_MODALITY):
        return []
    strong = [
        marker for marker in STRONG_OUTCOME
        if marker in generated_norm and marker not in source_norm
    ]
    return ["modality_strengthened:" + ",".join(strong[:3])] if strong else []


def _clickbait_issues(source: str, generated_title: str) -> List[str]:
    source_norm = _norm(source)
    generated_norm = _norm(generated_title)
    return [
        "unsupported_clickbait:" + marker
        for marker in CLICKBAIT
        if marker in generated_norm and marker not in source_norm
    ]


def _category_review(
    category: str,
    source_topics: Set[str],
    title_topics: Set[str],
) -> Tuple[int, List[str]]:
    issues: List[str] = []
    score = 100

    if category == "sakh":
        if "local" not in source_topics:
            return 0, ["category_local_without_local_story"]
        if "foreign" in title_topics and "local" not in title_topics:
            return 0, ["foreign_story_in_local_stream"]
    elif category == "sakh_chp":
        if not {"local", "incident"}.issubset(source_topics):
            return 0, ["category_chp_mismatch"]
        if "incident" not in title_topics:
            score = 72
            issues.append("title_category_weak:incident")
        if "weather" in title_topics and "incident" not in title_topics:
            return 0, ["weather_mislabeled_as_chp"]
    elif category == "sakh_quake":
        if not {"local", "quake"}.issubset(source_topics):
            return 0, ["category_quake_mismatch"]
        if "quake" not in title_topics:
            score = 72
            issues.append("title_category_weak:quake")
    elif category == "world_ru":
        if not {"foreign", "russia"}.issubset(source_topics):
            return 0, ["world_ru_without_foreign_and_russia"]
        if not ({"foreign", "russia"} & title_topics):
            score = 72
            issues.append("title_category_weak:world_ru")
    elif category == "geo":
        if "foreign" not in source_topics:
            return 0, ["category_geo_without_foreign_story"]
    elif category in {"ru_security", "ru_incident", "ru_eco", "ru_pol"}:
        needed = {
            "ru_security": "security",
            "ru_incident": "incident",
            "ru_eco": "economy",
            "ru_pol": "politics",
        }[category]
        if needed not in source_topics:
            return 0, ["category_not_supported:" + category]
        if "foreign" in title_topics and "russia" not in title_topics:
            return 0, ["foreign_story_in_russia_stream"]
        if needed not in title_topics:
            score = 72
            issues.append("title_category_weak:" + needed)
    elif category == "it":
        if "it" not in source_topics:
            return 0, ["category_not_supported:it"]
        if "it" not in title_topics:
            score = 72
            issues.append("title_category_weak:it")
    else:
        return 0, ["unknown_category:" + category]

    return score, issues


def deterministic_review(candidate: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    source_title = _clean(candidate.get("title"))
    source_text = _clean(candidate.get("source_text"))
    generated_title = _clean(row.get("title_ru"))
    body = " ".join(_clean(value) for value in (row.get("body") or []) if _clean(value))
    category = str(candidate.get("category_key") or "")
    source_all = f"{source_title} {source_text}"

    title_score, title_precision, headline_coverage = title_source_metrics(
        source_title,
        source_text,
        generated_title,
    )
    title_topics = infer_topics(generated_title)
    source_topics = infer_topics(source_all)

    issues: List[str] = []
    issues.extend(_modality_issues(source_all, generated_title))
    issues.extend(_clickbait_issues(source_all, generated_title))

    invented = sorted(_numbers(generated_title + " " + body) - _numbers(source_all))
    if invented:
        issues.append("invented_numbers:" + ",".join(invented))

    category_score, category_issues = _category_review(
        category,
        source_topics,
        title_topics,
    )
    issues.extend(category_issues)

    exact_or_extractive = (
        _norm(generated_title) == _norm(source_title)
        or row.get("editorial_mode") == "extractive_fallback"
    )

    hard = [
        issue for issue in issues
        if not str(issue).startswith("title_category_weak:")
    ]

    if is_russian_text(source_all) and not exact_or_extractive:
        if title_score < 78:
            hard.append("title_source_score_low")
        if title_precision < 78:
            hard.append("title_contains_unsupported_concepts")
        if headline_coverage < 55:
            hard.append("headline_central_claim_lost")

    requires_ai_review = (
        not exact_or_extractive
        or not is_russian_text(source_all)
        or any(str(issue).startswith("title_category_weak:") for issue in issues)
    )

    return {
        "approved": not hard and category_score >= 90,
        "title_matches_source": title_score,
        "title_precision": title_precision,
        "headline_coverage": headline_coverage,
        "category_matches_story": category_score,
        "facts_supported": not any(str(issue).startswith("invented_numbers:") for issue in issues),
        "meaning_changed": any(str(issue).startswith("modality_strengthened:") for issue in issues),
        "requires_ai_review": requires_ai_review,
        "source_is_russian": is_russian_text(source_all),
        "issues": issues + [issue for issue in hard if issue not in issues],
        "source_topics": sorted(source_topics),
        "title_topics": sorted(title_topics),
        "mode": "deterministic",
    }


def ai_review_prompt(candidate: Dict[str, Any], row: Dict[str, Any]) -> str:
    payload = {
        "source": candidate.get("source"),
        "source_url": candidate.get("url"),
        "source_title": candidate.get("title"),
        "source_text": candidate.get("source_text"),
        "assigned_category_key": candidate.get("category_key"),
        "assigned_category": candidate.get("category"),
        "generated_title": row.get("title_ru"),
        "generated_body": row.get("body"),
    }
    return (
        "Ты независимый выпускающий редактор. Не переписывай новость — только проверь. "
        "Сравни исходник и готовый пост. Заголовок обязан передавать центральную суть исходного "
        "заголовка и статьи, а не второстепенную деталь. Нельзя менять субъект, действие, место, "
        "время, причинность и статус события. Нельзя усиливать модальность: "
        "'может/планирует/обсуждает' нельзя превращать в 'сделал/ввел/принял'. "
        "Категория должна соответствовать теме и географии события, а не стране издателя. "
        "Верни только JSON: "
        '{"approved":true,"title_matches_source":0,"category_matches_story":0,'
        '"facts_supported":true,"meaning_changed":false,"issues":[]}. '
        "approved=true только при title_matches_source>=90, category_matches_story>=90, "
        "facts_supported=true и meaning_changed=false.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def normalize_ai_verdict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    try:
        title_score = int(value.get("title_matches_source"))
        category_score = int(value.get("category_matches_story"))
    except (TypeError, ValueError):
        return None

    facts_supported = value.get("facts_supported") is True
    meaning_changed = value.get("meaning_changed") is True
    issues = value.get("issues") if isinstance(value.get("issues"), list) else []
    approved = (
        value.get("approved") is True
        and title_score >= 90
        and category_score >= 90
        and facts_supported
        and not meaning_changed
    )
    return {
        "approved": approved,
        "title_matches_source": max(0, min(100, title_score)),
        "category_matches_story": max(0, min(100, category_score)),
        "facts_supported": facts_supported,
        "meaning_changed": meaning_changed,
        "issues": [str(issue)[:180] for issue in issues[:8]],
        "mode": "independent_ai",
    }


def merge_reviews(
    deterministic: Dict[str, Any],
    ai: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if ai is None:
        result = dict(deterministic)
        result["approved"] = (
            bool(deterministic.get("approved"))
            and not deterministic.get("requires_ai_review")
        )
        if deterministic.get("requires_ai_review"):
            result.setdefault("issues", []).append("independent_ai_review_unavailable")
        return result

    deterministic_title = int(deterministic.get("title_matches_source") or 0)
    ai_title = int(ai.get("title_matches_source") or 0)
    title_score = min(
        ai_title,
        deterministic_title if deterministic.get("source_is_russian") else 100,
    )
    category_score = min(
        int(ai.get("category_matches_story") or 0),
        int(deterministic.get("category_matches_story") or 0),
    )
    issues = list(deterministic.get("issues") or []) + list(ai.get("issues") or [])
    hard_deterministic = [
        issue for issue in deterministic.get("issues") or []
        if not str(issue).startswith("title_category_weak:")
    ]
    facts_supported = (
        bool(ai.get("facts_supported"))
        and bool(deterministic.get("facts_supported"))
    )
    meaning_changed = (
        bool(ai.get("meaning_changed"))
        or bool(deterministic.get("meaning_changed"))
    )
    approved = (
        not hard_deterministic
        and ai.get("approved") is True
        and title_score >= 90
        and category_score >= 90
        and facts_supported
        and not meaning_changed
    )
    return {
        "approved": approved,
        "title_matches_source": title_score,
        "category_matches_story": category_score,
        "facts_supported": facts_supported,
        "meaning_changed": meaning_changed,
        "issues": issues[:12],
        "mode": "deterministic+independent_ai",
        "source_topics": deterministic.get("source_topics", []),
        "title_topics": deterministic.get("title_topics", []),
    }
