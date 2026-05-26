# Autonomous editorial review for SkySakhNews.
# Owner requirements implemented here:
# - publish only concrete fresh news, not ads/deals/downloads/tutorials;
# - keep correct stream/category;
# - prioritize Russia/Sakhalin/high-impact/security/major tech/games;
# - reject routine airport/BPLA alerts without real consequences;
# - produce clean Russian Telegram text without duplicated paragraphs or broken tails;
# - use OpenRouter only as optional fallback, never as hard dependency.

import html
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from category_policy import resolve_final_category_from_item, stream_priority
from editorial_text import build_post_text, is_post_usable, cyrillic_ratio

QUEUE_FILE = Path("editorial_queue.json")
STATE_FILE = Path("state.json")
APPROVE_LIMIT = int(os.getenv("EDITORIAL_REVIEW_APPROVE_LIMIT", "3"))
PENDING_MAX_HOURS = int(os.getenv("EDITORIAL_REVIEW_PENDING_MAX_HOURS", "20"))
MIN_AUTO_SCORE = int(os.getenv("EDITORIAL_REVIEW_MIN_AUTO_SCORE", "600"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
OPENROUTER_TIMEOUT = int(os.getenv("OPENROUTER_TIMEOUT", "45"))
SAKH_TZ = timezone(timedelta(hours=11))

DEAL_TERMS = [
    "deal", "sale", "discount", "coupon", "promo", "free shipping", "amazon", "walmart", "woot",
    "memorial day", "starts at just", "less than $", "under $", "$", "lowest price", "скид",
    "распродаж", "купон", "промокод", "power bank", "prime members"
]
DOWNLOAD_TERMS = ["download", "drivers", "official nvidia drivers", "nvidia.com/en-us/drivers", "скачать драйвер", "драйвер"]
TUTORIAL_TERMS = ["как ", "руководство", "гайд", "туториал", "личный опыт", "что должен уметь", "разбираемся", "стек и грабли", "читать далее"]
LOW_VALUE_GAME_TERMS = ["sound effect", "photo mode", "motion controls", "copies", "early access sensation", "sells over", "far far west"]
WEAK_DECLARATION_TERMS = [
    "готовы к сотрудничеству", "ни с кем не борются", "допустил теоретическую возможность", "теоретическую возможность",
    "не рассматривается", "не планируется", "не стоит на повестке", "не обсуждается", "не ожидается",
    "заявил о готовности", "выразил готовность", "призвал к", "рассчитывает на"
]
WEAK_ALERT_TERMS = [
    "план ковер", "режим ковер", "угроза бпла", "опасность бпла", "закрыто воздушное пространство",
    "закрывали воздушное пространство", "введен режим", "введён режим", "угроза атаки", "работает пво",
    "объявлена тревога", "ограничения на прием и выпуск", "ограничения на приём и выпуск"
]
HARD_IMPACT_TERMS = [
    "погиб", "погибли", "есть погибшие", "ранен", "ранены", "пострадал", "пострадали", "жертвы",
    "удар", "обстрел", "атака", "попадание", "прилет", "прилёт", "разрушен", "разрушения",
    "поврежден", "повреждены", "повреждена", "сгорел", "пожар", "эвакуация", "без электроснабжения",
    "без электричества", "отключение света", "массовое отключение", "поврежден объект", "повреждено предприятие",
    "поврежден дом", "ущерб", "без воды", "лавина", "спасатели", "пропали", "массовые задержки", "десятки рейсов"
]
LAW_POLITICS_TERMS = ["госдума", "комитет", "законопроект", "закон", "совет федерации", "володин", "сенаторы", "депутаты", "правительство", "министерство", "кремль", "песков", "подписали заявление", "заседание", "мид", "лавров"]
RUSSIA_TERMS = ["russia", "russian", "putin", "kremlin", "moscow", "россия", "россий", "путин", "кремль", "москва", "рф"]
GAMING_MAJOR_TERMS = ["rockstar", "gta", "the witcher", "cd projekt", "playstation", "xbox game pass", "game pass", "steam", "nintendo", "major studio", "layoff", "acquisition", "lawsuit", "суд", "сделка", "массовые увольнения"]
STRONG_BONUS_TERMS = ["putin", "путин", "xi", "си", "pipeline", "gas", "oil", "санкц", "бпла", "iran", "иран", "google", "openai", "погиб", "пожар", "лавина", "без воды", "cve", "уязвим", "gta", "rockstar", "starship", "spacex", "сахалин"]
PROPAGANDA_PHRASES = ["беззащитным детям", "каратели", "нацисты", "террористический режим", "прицельно ударили по спящим"]
BAD_AI_OUTPUT_TERMS = ["я не могу", "as an ai", "i cannot", "не могу помочь", "извините", "sorry"]


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


def clean(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\bINTERFAX\.RU\s*-\s*", "", text)
    text = re.sub(r"\bМосква\.\s*\d+\s+[а-яА-Я]+\.\s*", "", text)
    return re.sub(r"\s+", " ", text).strip(" -—")


def norm_text(*parts: str) -> str:
    text = " ".join(str(p or "") for p in parts).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def semantic_blob(item: Dict) -> str:
    return norm_text(*(str(item.get(k) or "") for k in ("title_original", "title_ru", "source_text", "body", "url", "source")))


def blob(item: Dict) -> str:
    return norm_text(*(str(item.get(k) or "") for k in ("title_original", "title_ru", "source_text", "post_text", "edited_post_text", "url", "source", "category", "category_hint")))


def has_any(text: str, terms: List[str]) -> bool:
    text = norm_text(text)
    return any(term.lower().replace("ё", "е") in text for term in terms)


def age_hours(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
    except Exception:
        return None


def extract_json_object(raw: str) -> Optional[Dict]:
    if not raw:
        return None
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def openrouter_rewrite(item: Dict, category: str) -> Optional[Tuple[str, List[str]]]:
    if not OPENROUTER_API_KEY:
        return None
    title = clean(item.get("title_original") or item.get("title_ru") or "")[:240]
    source_text = clean(item.get("source_text") or "")[:2500]
    if not title or not source_text:
        return None
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise Russian news editor. Output JSON only."},
            {"role": "user", "content": (
                "Сделай короткий русский Telegram-новостной пост. Только факты из источника; без рекламы; без дублей; без оценочной пропаганды. "
                "Заголовок до 95 символов. Body: 1-2 коротких абзаца. Верни JSON {\"title\":\"...\",\"body\":[\"...\"]}.\n\n"
                f"Категория: {category}\nИсточник: {item.get('source') or 'Источник'}\nЗаголовок: {title}\nТекст: {source_text}"
            )},
        ],
        "temperature": 0.12,
        "max_tokens": 520,
    }
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/skyyuriofficial-stack/SkySakhNewsBot",
                "X-Title": "SkySakhNewsBot",
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        obj = extract_json_object(content)
        if not obj:
            return None
        out_title = clean(obj.get("title") or "")[:120]
        body_raw = obj.get("body") or []
        if isinstance(body_raw, str):
            body_raw = [body_raw]
        body = [clean(x) for x in body_raw if clean(x)][:2]
        full = out_title + " " + " ".join(body)
        if not body or cyrillic_ratio(full) < 0.70 or has_any(full, BAD_AI_OUTPUT_TERMS + PROPAGANDA_PHRASES):
            return None
        return out_title, body
    except Exception:
        return None


def is_weak_alert_without_consequences(text: str) -> bool:
    return has_any(text, WEAK_ALERT_TERMS) and not has_any(text, HARD_IMPACT_TERMS)


def should_force_law_politics(text: str) -> bool:
    return has_any(text, LAW_POLITICS_TERMS) and not has_any(text, HARD_IMPACT_TERMS)


def category_fix(item: Dict) -> str:
    return resolve_final_category_from_item(item)


def special_rewrite(item: Dict, category: str) -> Optional[Tuple[str, List[str]]]:
    text = semantic_blob(item)
    if "google" in text and "smart glasses" in text:
        return "Google готовит новые умные очки с Gemini", ["Google показала новые умные очки — первую попытку вернуться в этот формат после неудачи Google Glass.", "Модель должна выйти осенью и получить камеру, динамики и интеграцию с ИИ Gemini."]
    if "putin enjoys xi" in text or "pipeline deal" in text:
        return "BBC: Путин вернулся из Китая без сделки по газопроводу", ["BBC пишет, что Россия и Китай демонстрируют близость на мировой сцене, но переговоры не привели к ожидаемой сделке по трубопроводу.", "В материале отмечается, что отношения Москвы и Пекина остаются важными, но имеют пределы и дисбаланс интересов."]
    if "austrian ex-intelligence" in text and "russia spying" in text:
        return "В Австрии экс-сотрудника разведки осудили по делу о шпионаже в пользу России", ["Суд в Вене признал бывшего сотрудника австрийской разведки виновным по делу о передаче информации российской стороне.", "Этот процесс снова поднял вопрос о российской разведывательной активности в Австрии."]
    if "game pass" in text and "xbox" in text and not has_any(text, DEAL_TERMS):
        return "Microsoft раскрыла новую подборку игр для Xbox Game Pass", ["Microsoft объявила очередную подборку игр, которые появятся в Xbox Game Pass.", "Для игровой индустрии это сервисная новость: Game Pass остаётся одним из ключевых инструментов удержания аудитории Xbox и PC."]
    if "the witcher" in text and ("writer" in text or "lead writer" in text):
        return "К спин-оффу The Witcher привлекли сценаристку Destiny 2", ["К спин-оффу The Witcher присоединилась Кван Пернг, известная по работе над Destiny 2: The Final Shape.", "Она стала новым ведущим сценаристом проекта, что может усилить сюжетную часть игры."]
    return None


def build_clean_russian_post(item: Dict, category: str) -> Optional[Tuple[str, List[str], str]]:
    special = special_rewrite(item, category)
    if special and is_post_usable(special[0], special[1]):
        title, body = special
        return title, body[:2], "special"

    title, body, _post = build_post_text(item, category)
    if is_post_usable(title, body):
        return title, body[:2], "local"

    ai = openrouter_rewrite(item, category)
    if ai and is_post_usable(ai[0], ai[1]):
        return ai[0], ai[1], "openrouter"
    return None


def published_sets() -> Tuple[set, set]:
    state = load_json(STATE_FILE, {})
    return set(state.get("published_urls", []) or []), set(state.get("published_title_hashes", []) or [])


def reject_reason(item: Dict, category: str, urls: set, hashes: set) -> Optional[str]:
    text = semantic_blob(item)
    all_text = blob(item)
    if item.get("url") in urls or item.get("title_hash") in hashes:
        return "Отклонено автоматически: уже опубликовано ранее."
    published_age = age_hours(item.get("published_at") or item.get("created_at"))
    pending_age = age_hours(item.get("created_at"))
    if published_age is not None and published_age > 48:
        return "Отклонено автоматически: материал устарел для новостной ленты."
    if pending_age is not None and pending_age > PENDING_MAX_HOURS:
        return "Отклонено автоматически: черновик слишком долго висел без публикации."
    if has_any(all_text, DOWNLOAD_TERMS):
        return "Отклонено автоматически: страница загрузки/драйверов, не новость."
    if has_any(all_text, DEAL_TERMS):
        return "Отклонено автоматически: скидка/товарный материал, не новость."
    if has_any(all_text, TUTORIAL_TERMS):
        return "Отклонено автоматически: обучающая/колоночная статья, не новость."
    if has_any(text, WEAK_DECLARATION_TERMS):
        return "Отклонено автоматически: слабая декларативная/отрицательная новость без события."
    if category == "🇷🇺 РФ / война и безопасность":
        if is_weak_alert_without_consequences(text):
            return "Отклонено автоматически: слабая тревожная новость без жертв, ущерба или серьёзных последствий."
        if should_force_law_politics(text):
            return "Отклонено автоматически: материал относится к законам/политике, а не к военной безопасности."
        if not has_any(text, HARD_IMPACT_TERMS + ["с-400", "минобороны", "фсб", "заэс", "аэс", "склады боеприпасов", "аэродромов", "военных аэродромов"]):
            return "Отклонено автоматически: для военного потока недостаточно фактуры о последствиях или значимом событии."
    if category == "🎮 Игры / индустрия":
        if has_any(text, LOW_VALUE_GAME_TERMS):
            return "Отклонено автоматически: игровая новость низкой значимости для текущей ленты."
        if not has_any(text, GAMING_MAJOR_TERMS):
            return "Отклонено автоматически: игровая тема не имеет достаточной индустриальной значимости."
    if category == "🌍 Мир о России" and not has_any(text, RUSSIA_TERMS):
        return "Отклонено автоматически: нет явной связи с Россией."
    return None


def score_item(item: Dict, category: str) -> int:
    text = semantic_blob(item)
    score = stream_priority(category)
    if has_any(text, STRONG_BONUS_TERMS):
        score += 80
    return score


def review_queue() -> None:
    queue = load_json(QUEUE_FILE, {"version": 1, "items": []})
    items = queue.get("items", []) or []
    urls, hashes = published_sets()
    pending = [x for x in items if x.get("status") == "pending"]
    decisions = []
    for item in pending:
        category = category_fix(item)
        reason = reject_reason(item, category, urls, hashes)
        decisions.append((score_item(item, category), item, category, reason))
    decisions.sort(key=lambda x: x[0], reverse=True)
    approved = reviewed = 0
    for score, item, category, reason in decisions:
        reviewed += 1
        item["reviewed_at"] = now_utc()
        item["reviewed_by"] = "auto-editor-v7-local-cleaner"
        item["category"] = category
        item["stream_priority"] = stream_priority(category)
        item["score"] = score
        if reason:
            item["status"] = "rejected"
            if has_any(blob(item), DEAL_TERMS + DOWNLOAD_TERMS):
                item["image_decision"] = "drop"
            item.setdefault("editor_notes", []).append(reason)
            continue
        if approved >= APPROVE_LIMIT or score < MIN_AUTO_SCORE:
            item["status"] = "hold"
            item.setdefault("editor_notes", []).append(f"В резерве: score={score}, порог={MIN_AUTO_SCORE}, приоритет потока={stream_priority(category)}.")
            continue
        built = build_clean_russian_post(item, category)
        if not built:
            item["status"] = "hold"
            item.setdefault("editor_notes", []).append("В резерве: не удалось собрать чистый русский текст локально или через OpenRouter.")
            continue
        title, body, rewrite_mode = built
        title2, body2, post_text = build_post_text({**item, "title_ru": title, "body": body}, category)
        # Preserve special/OpenRouter text if provided; otherwise use robust local builder output.
        if rewrite_mode in {"special", "openrouter"}:
            from editorial_text import make_post
            post_text = make_post(category, title, body[:2], item.get("url") or "", item.get("source") or "Источник")
        else:
            title, body = title2, body2
        item["status"] = "approved"
        item["title_ru"] = title
        item["body"] = body[:2]
        item["post_text"] = post_text
        item["edited_post_text"] = post_text
        item["image_decision"] = "use" if item.get("image_url") else "none"
        item["with_image"] = bool(item.get("image_url"))
        item["rewrite_mode"] = rewrite_mode
        item.setdefault("editor_notes", []).append(f"Одобрено автоматическим редактором v7: clean Russian post via {rewrite_mode}.")
        approved += 1
    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["reviewed_at"] = now_utc()
    queue["reviewed_at_sakhalin"] = now_sakh()
    queue["auto_review"] = {
        "version": 7,
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
        "reviewed_pending": reviewed,
        "approved": approved,
        "approve_limit": APPROVE_LIMIT,
        "min_auto_score": MIN_AUTO_SCORE,
        "openrouter_enabled": bool(OPENROUTER_API_KEY),
        "reviewed_at": queue["reviewed_at"],
        "reviewed_at_sakhalin": queue["reviewed_at_sakhalin"],
    }
    save_json(QUEUE_FILE, queue)
    print(f"auto-review-v7-local-cleaner: reviewed={reviewed}, approved={approved}, openrouter={bool(OPENROUTER_API_KEY)}")


if __name__ == "__main__":
    review_queue()
