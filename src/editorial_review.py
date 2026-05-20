# Autonomous editorial review for SkySakhNews.
# Purpose: do not rely on ChatGPT chat-side automations for routine approvals.
# The reviewer is intentionally conservative: it approves only clear, fresh, valuable items
# and rejects/holds weak, stale, advertorial, tutorial, or wrongly classified materials.

import html
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

QUEUE_FILE = Path("editorial_queue.json")
STATE_FILE = Path("state.json")

APPROVE_LIMIT = int(os.getenv("EDITORIAL_REVIEW_APPROVE_LIMIT", "2"))
PENDING_MAX_HOURS = int(os.getenv("EDITORIAL_REVIEW_PENDING_MAX_HOURS", "20"))

SAKH_TZ = timezone(timedelta(hours=11))

FOOTERS = {
    "🌍 Мир о России": "МИР О РОССИИ",
    "🇷🇺 РФ / война и безопасность": "РФ | ВОЙНА И БЕЗОПАСНОСТЬ",
    "🇷🇺 РФ / экономика": "РФ | ЭКОНОМИКА",
    "🇷🇺 РФ / законы и политика": "РФ | ЗАКОНЫ И ПОЛИТИКА",
    "🧭 Геополитика": "ГЕОПОЛИТИКА",
    "🌐 Мировые IT": "МИРОВЫЕ IT",
    "💻 IT / технологии": "IT / ТЕХНОЛОГИИ",
    "🎮 Игры / индустрия": "ИГРОВАЯ ИНДУСТРИЯ",
    "📍 Сахалин": "САХАЛИН",
}

DEAL_TERMS = [
    "deal", "sale", "discount", "coupon", "promo", "free shipping", "amazon", "woot", "memorial day",
    "starts at just", "less than $", "under $", "скид", "распродаж", "купон", "промокод",
    "power bank", "controller with", "prime members",
]

TUTORIAL_TERMS = [
    "как управлять", "как сделать", "руководство", "гайд", "туториал", "личный опыт",
    "что должен уметь", "чему я науч", "разбираемся", "читать далее",
]

WEAK_DECLARATION_TERMS = [
    "готовы к сотрудничеству", "ни с кем не борются", "допустил теоретическую возможность",
    "теоретическую возможность", "готовы сотрудничать со всеми партнерами",
]

RUSSIA_TERMS = ["russia", "russian", "putin", "kremlin", "moscow", "россия", "россий", "путин", "кремль", "москва", "рф"]
WAR_TERMS = ["бпла", "дрон", "атака", "ранен", "погиб", "обстрел", "удар", "war", "attack", "drone", "missile", "israel", "iran", "иран", "израил", "цахал"]
ECON_TERMS = ["эконом", "банк", "вклад", "газ", "нефть", "спг", "турпоток", "экспорт", "импорт", "pipeline", "gas", "oil", "deal", "trade"]
IT_MAJOR_TERMS = ["google", "gemini", "openai", "chatgpt", "nvidia", "microsoft", "apple", "smart glasses", "ai", "ии", "нейросет", "cve", "уязвим"]
GAMING_NEWS_TERMS = ["game pass", "xbox game pass", "witcher", "gta", "rockstar", "playstation", "nintendo", "steam", "release", "studio", "developer"]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_sakh() -> str:
    return datetime.now(SAKH_TZ).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("INTERFAX.RU -", " ").replace("Москва.", " ")
    text = re.sub(r"В мире\d{1,2}\s+[а-яА-Я]+\s+\d{4}.*?Читать подробнее", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


def attr(value) -> str:
    return html.escape(str(value or ""), quote=True)


def blob(item: Dict) -> str:
    return " ".join(str(item.get(k) or "") for k in ("title_original", "title_ru", "source_text", "post_text", "url", "source", "category", "category_hint")).lower()


def has_any(text: str, terms: List[str]) -> bool:
    text = (text or "").lower()
    return any(term.lower() in text for term in terms)


def sentence_split(text: str) -> List[str]:
    text = clean(text)
    if not text:
        return []
    raw = re.split(r"(?<=[.!?])\s+", text)
    out = []
    seen = set()
    for s in raw:
        s = clean(s)
        if len(s) < 40:
            continue
        key = re.sub(r"\W+", "", s.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def source_age_hours(item: Dict) -> Optional[float]:
    raw = item.get("published_at") or item.get("created_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
    except Exception:
        return None


def pending_age_hours(item: Dict) -> Optional[float]:
    raw = item.get("created_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
    except Exception:
        return None


def category_fix(item: Dict) -> str:
    text = blob(item)
    category = item.get("category") or item.get("category_hint") or ""
    source_type = item.get("source_type") or ""

    if source_type == "world" and has_any(text, RUSSIA_TERMS):
        return "🌍 Мир о России"
    if source_type == "world" and has_any(text, WAR_TERMS):
        return "🧭 Геополитика"
    if source_type == "it" or has_any(text, IT_MAJOR_TERMS):
        return "🌐 Мировые IT"
    if source_type == "gaming":
        return "🎮 Игры / индустрия"
    if "interfax.ru/world" in text:
        return "🧭 Геополитика"
    if has_any(text, ECON_TERMS) and not has_any(text, ["бпла", "атака", "удар", "ранен", "погиб"]):
        return "🇷🇺 РФ / экономика"
    if has_any(text, ["путин", "си цзиньпин", "китай", "переговор", "саммит", "визит"]) and not has_any(text, ["бпла", "атака", "обстрел", "ранен"]):
        return "🇷🇺 РФ / законы и политика"
    return category


def make_post(category: str, title: str, body: List[str], url: str, source: str) -> str:
    footer = FOOTERS.get(category, category)
    safe_body = "\n\n".join(esc(x) for x in body if x)
    if safe_body:
        return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n{safe_body}\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source)}</a>"
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source)}</a>"


def special_rewrite(item: Dict, category: str) -> Optional[Tuple[str, List[str]]]:
    text = blob(item)
    source = item.get("source") or ""

    if "google" in text and "smart glasses" in text:
        return "Google готовит новые умные очки с Gemini", [
            "Google показала новые умные очки — первую попытку вернуться в этот формат после неудачи Google Glass.",
            "Модель должна выйти осенью и получить камеру, динамики и интеграцию с ИИ Gemini.",
            "Компания делает ставку на формат hands free: очки смогут помогать пользователю без постоянного обращения к смартфону.",
        ]

    if "putin enjoys xi" in text or "pipeline deal" in text:
        return "BBC: Путин вернулся из Китая без сделки по газопроводу", [
            "BBC пишет, что Россия и Китай демонстрируют близость на мировой сцене, но переговоры не привели к ожидаемой сделке по трубопроводу.",
            "В материале отмечается, что отношения Москвы и Пекина остаются важными, но имеют пределы и дисбаланс интересов.",
            "Это значимый сюжет для направления «Мир о России»: внешняя оценка российско-китайских переговоров и энергетической повестки.",
        ]

    if "austrian ex-intelligence" in text and "russia spying" in text:
        return "В Австрии экс-сотрудника разведки осудили по делу о шпионаже в пользу России", [
            "Суд в Вене признал бывшего сотрудника австрийской разведки виновным по делу о передаче информации российской стороне.",
            "BBC отмечает, что этот процесс снова поднял вопрос о российской разведывательной активности в Австрии.",
        ]

    if "game pass" in text and "xbox" in text and "deal" not in text:
        return "Microsoft раскрыла новую подборку игр для Xbox Game Pass", [
            "Microsoft объявила очередную подборку игр, которые появятся в Xbox Game Pass в мае и начале следующего месяца.",
            "Для игровой индустрии это значимая сервисная новость: Game Pass остаётся одним из ключевых инструментов удержания аудитории Xbox и PC.",
        ]

    if "три человека ранены" in text and "бпла" in text:
        return "Три человека ранены в ДНР при атаке БПЛА", [
            "В ДНР три мирных жителя получили ранения в результате атаки БПЛА, сообщил глава региона Денис Пушилин.",
            "По данным источника, пострадавшим оказывается медицинская помощь.",
        ]

    if "курской области" in text and "умерла" in text and "бпла" in text:
        return "В Курской области умерла пострадавшая после атаки БПЛА", [
            "В Курской области умерла женщина, получившая тяжёлые ранения при ударе БПЛА 18 мая.",
            "По данным источника, травмы оказались слишком тяжёлыми, несмотря на помощь врачей.",
        ]

    if "долгосрочных вклад" in text:
        return "Правительство РФ рассмотрит меры по долгосрочным вкладам", [
            "Правительство РФ рассмотрит изменения в закон о страховании вкладов, направленные на повышение привлекательности долгосрочных депозитов.",
            "Цель — привлечь в банковский сектор ресурсы, необходимые для долгосрочных инвестиций в экономику.",
        ]

    return None


def generic_rewrite(item: Dict, category: str) -> Tuple[str, List[str]]:
    title = clean(item.get("title_ru") or item.get("title_original") or "")
    source_text = item.get("source_text") or ""
    sentences = sentence_split(source_text)
    body = []
    for s in sentences:
        if "читать далее" in s.lower() or "sign in" in s.lower() or "support us" in s.lower():
            continue
        # Remove obvious duplicated lead fragments.
        s = re.sub(r"(.{30,180})\s+\1", r"\1", s)
        body.append(s[:360])
        if len(body) >= 2:
            break
    return title, body


def published_sets() -> Tuple[set, set]:
    state = load_json(STATE_FILE, {})
    return set(state.get("published_urls", []) or []), set(state.get("published_title_hashes", []) or [])


def decision_score(item: Dict, category: str) -> int:
    text = blob(item)
    score = 0
    source = (item.get("source") or "").lower()

    if category == "🌍 Мир о России": score += 80
    if category == "🌐 Мировые IT": score += 75
    if category == "🇷🇺 РФ / война и безопасность": score += 70
    if category == "🧭 Геополитика": score += 65
    if category == "🇷🇺 РФ / экономика": score += 60
    if category == "🎮 Игры / индустрия": score += 50

    if any(x in source for x in ["bbc", "reuters", "ap", "interfax", "eurogamer", "pc gamer"]):
        score += 15
    if has_any(text, ["google", "gemini", "smart glasses", "putin", "xi", "pipeline", "бпла", "ранены", "правительство", "вклад"]):
        score += 15
    if has_any(text, DEAL_TERMS):
        score -= 200
    if has_any(text, TUTORIAL_TERMS):
        score -= 120
    if has_any(text, WEAK_DECLARATION_TERMS):
        score -= 90
    return score


def should_reject(item: Dict, category: str, urls: set, hashes: set) -> Optional[str]:
    text = blob(item)
    title = clean(item.get("title_original") or item.get("title_ru"))
    age = source_age_hours(item)
    page = pending_age_hours(item)

    if item.get("url") in urls or item.get("title_hash") in hashes:
        return "Отклонено автоматически: уже опубликовано ранее."
    if age is not None and age > 36:
        return "Отклонено автоматически: материал устарел для новостной ленты."
    if page is not None and page > PENDING_MAX_HOURS:
        return "Отклонено автоматически: черновик слишком долго висел без публикации."
    if has_any(text, DEAL_TERMS):
        return "Отклонено автоматически: товарная скидка/партнерский материал, не новость."
    if has_any(text, TUTORIAL_TERMS) and category in {"🌐 Мировые IT", "💻 IT / технологии", "🎮 Игры / индустрия"}:
        return "Отклонено автоматически: обучающая/колоночная статья, не новость."
    if has_any(text, WEAK_DECLARATION_TERMS):
        return "Отклонено автоматически: слабая декларативная новость без достаточной фактуры."
    if category == "🎮 Игры / индустрия" and not has_any(text, GAMING_NEWS_TERMS) and has_any(text, ["power bank", "controller", "amazon", "woot"]):
        return "Отклонено автоматически: товарный материал, не игровая новость."
    if category == "🌍 Мир о России" and not has_any(text, RUSSIA_TERMS):
        return "Отклонено автоматически: нет явной связи с Россией."
    return None


def review_queue() -> None:
    queue = load_json(QUEUE_FILE, {"version": 1, "items": []})
    items = queue.get("items", []) or []
    urls, hashes = published_sets()

    pending = [x for x in items if x.get("status") == "pending"]
    decisions = []

    for item in pending:
        category = category_fix(item)
        reject_reason = should_reject(item, category, urls, hashes)
        score = decision_score(item, category)
        decisions.append((score, item, category, reject_reason))

    decisions.sort(key=lambda x: x[0], reverse=True)
    approved = 0
    reviewed = 0

    for score, item, category, reject_reason in decisions:
        reviewed += 1
        item["reviewed_at"] = now_utc()
        item["reviewed_by"] = "auto-editor"
        item["category"] = category

        if reject_reason:
            item["status"] = "rejected"
            item["image_decision"] = "drop" if has_any(blob(item), DEAL_TERMS) else item.get("image_decision", "none")
            item.setdefault("editor_notes", []).append(reject_reason)
            continue

        if approved < APPROVE_LIMIT and score >= 65:
            special = special_rewrite(item, category)
            if special:
                title, body = special
            else:
                title, body = generic_rewrite(item, category)
            if not title or not body:
                item["status"] = "hold"
                item.setdefault("editor_notes", []).append("В резерве: автоматический редактор не смог безопасно сформировать чистый текст.")
                continue
            item["status"] = "approved"
            item["title_ru"] = title
            item["body"] = body
            item["post_text"] = make_post(category, title, body, item.get("url") or "", item.get("source") or "Источник")
            item["edited_post_text"] = item["post_text"]
            if item.get("image_url"):
                item["image_decision"] = "use"
                item["with_image"] = True
            else:
                item["image_decision"] = "none"
                item["with_image"] = False
            item.setdefault("editor_notes", []).append("Одобрено автоматическим редактором: материал соответствует приоритетам канала, текст очищен.")
            approved += 1
        else:
            item["status"] = "hold"
            item.setdefault("editor_notes", []).append("В резерве: материал не прошёл в лимит публикаций или требует ручной оценки.")

    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["reviewed_at"] = now_utc()
    queue["reviewed_at_sakhalin"] = now_sakh()
    queue["auto_review"] = {
        "reviewed_pending": reviewed,
        "approved": approved,
        "approve_limit": APPROVE_LIMIT,
        "reviewed_at": queue["reviewed_at"],
        "reviewed_at_sakhalin": queue["reviewed_at_sakhalin"],
    }
    save_json(QUEUE_FILE, queue)
    print(f"auto-review: reviewed={reviewed}, approved={approved}")


if __name__ == "__main__":
    review_queue()
