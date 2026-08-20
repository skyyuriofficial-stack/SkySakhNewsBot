"""Independent semantic/editorial gate for SkySakhNews.

The writer never decides whether its own post is safe. This module checks the
source story, generated headline/body and assigned stream before Telegram.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

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
    "углегорск", "оха", "ноглики", "александровск-сахалин", "курил", "северо-курильск",
    "южно-курильск", "сахалинской области",
)
WEATHER = (
    "погод", "дожд", "ливн", "осад", "снег", "метел", "циклон", "шторм", "ветер", "туман",
    "мороз", "жар", "температур", "гидромет", "прогноз",
)
QUAKE = ("землетряс", "магнитуд", "эпицентр", "сейсм", "толчк", "толчок")
SECURITY = (
    "бпла", "дрон", "пво", "воздушн", "атак", "обстрел", "ракет", "минобороны", "росавиац",
    "план ковер", "план ковёр", "террорист", "диверс", "взрывн", "перехват", "сбит", "сбили",
)
INCIDENT = (
    "дтп", "авари", "пожар", "погиб", "смерт", "пострад", "утон", "крушен", "обруш", "травм",
    "происшеств", "убийств", "ранен", "пропал", "розыск", "мчс", "следовател", "полици",
    "прокуратур", "уголовн", "напад", "медвед", "краж", "украл", "украли", "задержан",
)
ECONOMY = (
    "центробанк", "цб ", "ключев", "ставк", "инфляц", "рубл", "бюджет", "минфин", "нефт",
    "газ", "экспорт", "импорт", "пошлин", "рынок", "акци", "ввп", "налог", "эконом",
)
POLITICS = (
    "кремл", "путин", "лавров", "госдум", "совфед", "правительств", "президент", "мид ",
    "совбез", "законопроект", "выбор", "депутат", "губернатор", "министр", "политик",
)
IT = (
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini", "нейросет", "искусственн интеллект",
    "ии ", "nvidia", "amd", "intel", "microsoft", "apple", "google", "android", "ios", "linux",
    "windows", "кибератак", "чип", "процессор", "telegram", "технолог",
)
FOREIGN = (
    "сша", "америк", "трамп", "канада", "канад", "иран", "израил", "китай", "тайван", "нато",
    "евросоюз", "британ", "франц", "герман", "япон", "коре", "украин", "зеленск", "white house",
    "usa", "canada", "iran", "israel", "china", "taiwan", "nato", "ukraine",
)
RUSSIA = ("росси", "рф", "москв", "кремл", "путин", "лавров")

WEAK_MODALITY = (
    "может", "могут", "могла", "могло", "возможно", "вероятно", "предполож", "ожидается",
    "ожидают", "планирует", "планируют", "намерен", "намерены", "рассматривает", "рассматривают",
    "обсуждает", "обсуждают", "предлагает", "предложил", "хочет", "готовится", "может быть",
)
STRONG_OUTCOME = (
    "ввел", "ввела", "ввели", "введен", "введена", "введены", "принял", "приняла", "приняли",
    "утвердил", "утвердила", "утвердили", "запустил", "запустила", "запустили", "начал", "начала",
    "начали", "подписал", "подписала", "подписали", "заключил", "заключили", "состоялся",
    "состоялась", "произошло", "произошел", "произошёл", "решил", "решили", "отменил", "отменили",
)
CLICKBAIT = ("шок", "срочно", "ужас", "все в панике", "все в шоке", "катастроф", "сенсац", "невероятн")

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
    s = _clean(text).lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9%+.-]+", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _contains(text: str, markers: Sequence[str]) -> bool:
    low = _norm(text)
    return any(m in low for m in markers)


def _tokens(text: str) -> List[str]:
    out = []
    for w in re.findall(r"[a-zа-я0-9]+", _norm(text), flags=re.I):
        if len(w) >= 3 and w not in STOPWORDS and not w.isdigit():
            out.append(w)
    return out


def _stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    if len(w) <= 6:
        return w
    return w[: max(5, min(9, len(w) - 2))]


def _token_supported(token: str, source_tokens: Iterable[str]) -> bool:
    st = _stem(token)
    return any(_stem(x) == st or _stem(x).startswith(st) or st.startswith(_stem(x)) for x in source_tokens)


def _numbers(text: str) -> Set[str]:
    return {x.replace(",", ".") for x in re.findall(r"\d+(?:[,.]\d+)?", text or "")}


def is_russian_text(text: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", text or ""))
    return cyr / len(letters) >= 0.72


def infer_topics(text: str, source_name: str = "", url: str = "") -> Set[str]:
    blob = f"{text} {source_name} {url}".lower()
    topics: Set[str] = set()
    if _contains(blob, LOCAL_MARKERS) or any(x in blob for x in ("sakhalinmedia", "astv.ru", "sakh.online")):
        topics.add("local")
    if _contains(blob, WEATHER): topics.add("weather")
    if _contains(blob, QUAKE): topics.add("quake")
    if _contains(blob, SECURITY): topics.add("security")
    if _contains(blob, INCIDENT): topics.add("incident")
    if _contains(blob, ECONOMY): topics.add("economy")
    if _contains(blob, POLITICS): topics.add("politics")
    if _contains(blob, IT): topics.add("it")
    if _contains(blob, FOREIGN): topics.add("foreign")
    if _contains(blob, RUSSIA): topics.add("russia")
    return topics


def title_source_score(source_title: str, source_text: str, generated_title: str) -> int:
    src_title = _norm(source_title)
    gen = _norm(generated_title)
    if not gen:
        return 0
    if gen == src_title or gen in src_title or src_title in gen:
        return 100
    src_tokens = _tokens(source_title + " " + source_text)
    gen_tokens = _tokens(generated_title)
    if not gen_tokens:
        return 0
    supported = sum(1 for t in gen_tokens if _token_supported(t, src_tokens))
    precision = supported / len(gen_tokens)
    headline = _tokens(source_title)
    covered = (
        sum(1 for t in headline if _token_supported(t, gen_tokens)) / len(headline)
        if headline else precision
    )
    return max(0, min(100, round(100 * (0.72 * precision + 0.28 * covered))))


def _modality_issues(source: str, generated_title: str) -> List[str]:
    src = _norm(source)
    gen = _norm(generated_title)
    if not any(x in src for x in WEAK_MODALITY):
        return []
    strong = [x for x in STRONG_OUTCOME if x in gen and x not in src]
    return ["modality_strengthened:" + ",".join(strong[:3])] if strong else []


def _clickbait_issues(source: str, generated_title: str) -> List[str]:
    src = _norm(source)
    gen = _norm(generated_title)
    return ["unsupported_clickbait:" + x for x in CLICKBAIT if x in gen and x not in src]


def deterministic_review(candidate: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    source_title = _clean(candidate.get("title"))
    source_text = _clean(candidate.get("source_text"))
    title = _clean(row.get("title_ru"))
    body = " ".join(_clean(x) for x in (row.get("body") or []) if _clean(x))
    cat = str(candidate.get("category_key") or "")
    source_all = f"{source_title} {source_text}"

    title_score = title_source_score(source_title, source_text, title)
    # IMPORTANT: title semantics are evaluated from the title alone. Source URL or
    # publisher must never make a wrong headline appear local/Russian/IT/etc.
    title_topics = infer_topics(title)
    source_topics = infer_topics(
        source_all,
        str(candidate.get("source") or ""),
        str(candidate.get("url") or ""),
    )

    issues: List[str] = []
    issues.extend(_modality_issues(source_all, title))
    issues.extend(_clickbait_issues(source_all, title))

    invented = sorted(_numbers(title + " " + body) - _numbers(source_all))
    if invented:
        issues.append("invented_numbers:" + ",".join(invented))

    required = CATEGORY_TOPICS.get(cat, set())
    category_score = 100

    if cat == "sakh":
        if "local" not in source_topics:
            category_score = 0
            issues.append("category_local_without_local_story")
    elif cat == "sakh_chp":
        if "local" not in source_topics:
            category_score = 0; issues.append("category_chp_without_local_story")
        if "incident" not in source_topics:
            category_score = 0; issues.append("category_chp_without_incident")
        if "weather" in title_topics and "incident" not in title_topics:
            category_score = 0; issues.append("weather_mislabeled_as_chp")
    elif cat == "sakh_quake":
        if "local" not in source_topics or "quake" not in source_topics:
            category_score = 0; issues.append("category_quake_mismatch")
    elif cat == "world_ru":
        if not {"foreign", "russia"}.issubset(source_topics):
            category_score = 0; issues.append("world_ru_without_foreign_and_russia")
    elif required and not required.issubset(source_topics):
        category_score = 0
        issues.append("category_not_supported:" + cat)

    precise = {
        "ru_security": "security", "ru_incident": "incident", "ru_eco": "economy",
        "ru_pol": "politics", "it": "it", "sakh_quake": "quake", "sakh_chp": "incident",
    }
    need = precise.get(cat)
    if need and need not in title_topics:
        category_score = min(category_score, 72)
        issues.append("title_category_weak:" + need)

    # Geography-first protection for the exact class of errors previously seen:
    # foreign political/economic headlines from Russian publishers must not become
    # "Russia / politics" or "Russia / economy" merely because of the publisher.
    if cat in {"ru_pol", "ru_eco"} and "foreign" in title_topics and "russia" not in title_topics:
        category_score = min(category_score, 60)
        issues.append("title_foreign_focus_for_russia_stream")

    # All Russia streams reject clearly foreign-only source stories. Domestic
    # incidents/security can mention a foreign attacker, so this source-level rule
    # fires only when Russia is absent from the entire source context.
    if cat in {"ru_security", "ru_incident", "ru_pol", "ru_eco"}:
        if "foreign" in source_topics and "russia" not in source_topics and "local" not in source_topics:
            category_score = min(category_score, 60)
            issues.append("foreign_story_in_russia_stream")

    exact_or_extractive = (
        _norm(title) == _norm(source_title)
        or row.get("editorial_mode") == "extractive_fallback"
    )

    soft_prefixes = ("title_category_weak:",)
    hard = [x for x in issues if not str(x).startswith(soft_prefixes)]
    if is_russian_text(source_all) and title_score < 70 and not exact_or_extractive:
        hard.append("title_source_overlap_low")

    requires_ai = (
        not exact_or_extractive
        or any(str(x).startswith("title_category_weak:") for x in issues)
    )

    return {
        "approved": not hard and category_score >= 90,
        "title_matches_source": title_score,
        "category_matches_story": category_score,
        "facts_supported": not any(str(x).startswith("invented_numbers:") for x in issues),
        "meaning_changed": any(str(x).startswith("modality_strengthened:") for x in issues),
        "requires_ai_review": requires_ai,
        "source_is_russian": is_russian_text(source_all),
        "issues": issues,
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
        "Сравни исходник и готовый пост. Заголовок обязан отражать ЦЕНТРАЛЬНУЮ суть, а не "
        "второстепенную деталь. Нельзя усиливать модальность: 'может/планирует/обсуждает' нельзя "
        "превращать в 'сделал/ввел/принял'. Категория должна соответствовать и ТЕМЕ, и ГЕОГРАФИИ "
        "самого события, а не стране/типу издателя. Проверь субъект, действие, место, время, "
        "причинность, статус события и числа. Верни только JSON: "
        '{"approved":true,"title_matches_source":0,"category_matches_story":0,'
        '"facts_supported":true,"meaning_changed":false,"issues":[]}. '
        "approved=true только при title_matches_source>=90, category_matches_story>=90, "
        "facts_supported=true, meaning_changed=false.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def normalize_ai_verdict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    try:
        title_score = int(value.get("title_matches_source"))
        cat_score = int(value.get("category_matches_story"))
    except Exception:
        return None
    facts = value.get("facts_supported") is True
    changed = value.get("meaning_changed") is True
    issues = value.get("issues") if isinstance(value.get("issues"), list) else []
    approved = (
        value.get("approved") is True
        and title_score >= 90
        and cat_score >= 90
        and facts
        and not changed
    )
    return {
        "approved": approved,
        "title_matches_source": max(0, min(100, title_score)),
        "category_matches_story": max(0, min(100, cat_score)),
        "facts_supported": facts,
        "meaning_changed": changed,
        "issues": [str(x)[:180] for x in issues[:8]],
        "mode": "independent_ai",
    }


def merge_reviews(deterministic: Dict[str, Any], ai: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if ai is None:
        out = dict(deterministic)
        out["approved"] = bool(deterministic.get("approved")) and not deterministic.get("requires_ai_review")
        if deterministic.get("requires_ai_review"):
            out.setdefault("issues", []).append("independent_ai_review_unavailable")
        return out

    det_title = int(deterministic.get("title_matches_source") or 0)
    ai_title = int(ai.get("title_matches_source") or 0)
    title_score = min(ai_title, det_title if deterministic.get("source_is_russian") else 100)
    category_score = min(
        int(ai.get("category_matches_story") or 0),
        int(deterministic.get("category_matches_story") or 0),
    )
    issues = list(deterministic.get("issues") or []) + list(ai.get("issues") or [])
    hard_det = [x for x in deterministic.get("issues") or [] if not str(x).startswith("title_category_weak:")]
    facts = bool(ai.get("facts_supported")) and bool(deterministic.get("facts_supported"))
    changed = bool(ai.get("meaning_changed")) or bool(deterministic.get("meaning_changed"))
    approved = (
        not hard_det
        and ai.get("approved") is True
        and title_score >= 90
        and category_score >= 90
        and facts
        and not changed
    )
    return {
        "approved": approved,
        "title_matches_source": title_score,
        "category_matches_story": category_score,
        "facts_supported": facts,
        "meaning_changed": changed,
        "issues": issues[:12],
        "mode": "deterministic+independent_ai",
        "source_topics": deterministic.get("source_topics", []),
        "title_topics": deterministic.get("title_topics", []),
    }
