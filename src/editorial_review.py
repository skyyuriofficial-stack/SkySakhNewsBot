# Autonomous editorial review for SkySakhNews.
# Conservative production rules:
# - publish only Russian-language posts;
# - games are lowest priority;
# - discount/download/tutorial/service pages are rejected;
# - weak operational alerts such as airspace restrictions are rejected unless there are casualties, damage or major disruption;
# - law/politics/diplomacy must not be classified as security without real impact.

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

CATEGORY_WEIGHT = {
    "🌍 Мир о России": 1000,
    "🇷🇺 РФ / война и безопасность": 900,
    "🧭 Геополитика": 820,
    "🇷🇺 РФ / экономика": 760,
    "🇷🇺 РФ / законы и политика": 700,
    "🌐 Мировые IT": 520,
    "📍 Сахалин": 500,
    "🎮 Игры / индустрия": 120,
}

DEAL_TERMS = ["deal", "sale", "discount", "coupon", "promo", "free shipping", "amazon", "walmart", "woot", "memorial day", "starts at just", "less than $", "under $", "$", "lowest price", "скид", "распродаж", "купон", "промокод", "power bank", "prime members"]
DOWNLOAD_TERMS = ["download", "drivers", "official nvidia drivers", "nvidia.com/en-us/drivers", "скачать драйвер", "драйвер"]
TUTORIAL_TERMS = ["как ", "руководство", "гайд", "туториал", "личный опыт", "что должен уметь", "разбираемся", "стек и грабли", "читать далее"]
LOW_VALUE_GAME_TERMS = ["sound effect", "photo mode", "motion controls", "copies", "early access sensation", "sells over", "far far west"]
WEAK_DECLARATION_TERMS = ["готовы к сотрудничеству", "ни с кем не борются", "допустил теоретическую возможность", "теоретическую возможность"]

WEAK_ALERT_TERMS = ["план ковер", "режим ковер", "угроза бпла", "опасность бпла", "закрыто воздушное пространство", "закрывали воздушное пространство", "введен режим", "введён режим", "угроза атаки", "работает пво", "объявлена тревога", "ограничения на прием и выпуск", "ограничения на приём и выпуск"]
HARD_IMPACT_TERMS = ["погиб", "погибли", "есть погибшие", "ранен", "ранены", "пострадал", "пострадали", "жертвы", "удар", "обстрел", "атака", "попадание", "прилет", "прилёт", "разрушен", "разрушения", "поврежден", "повреждены", "повреждена", "сгорел", "пожар", "эвакуация", "без электроснабжения", "без электричества", "отключение света", "массовое отключение", "поврежден объект", "повреждено предприятие", "поврежден дом", "ущерб"]
LAW_POLITICS_TERMS = ["госдума", "комитет", "законопроект", "закон", "совет федерации", "володин", "сенаторы", "депутаты", "правительство", "министерство", "кремль", "песков", "подписали заявление", "переговоры", "саммит", "визит", "диалог", "заседание", "мид", "лавров"]

RUSSIA_TERMS = ["russia", "russian", "putin", "kremlin", "moscow", "россия", "россий", "путин", "кремль", "москва", "рф"]
SECURITY_TERMS = ["бпла", "дрон", "атака", "ранен", "погиб", "обстрел", "удар", "attack", "drone", "missile", "iran", "иран", "израил", "цахал"]
ECON_TERMS = ["эконом", "банк", "вклад", "газ", "нефть", "спг", "экспорт", "импорт", "pipeline", "gas", "oil", "trade", "санкц", "цб", "ставк"]
IT_MAJOR_TERMS = ["google", "gemini", "openai", "chatgpt", "anthropic", "nvidia", "microsoft", "apple", "smart glasses", "ai", "ии", "нейросет", "cve", "уязвим", "cyber"]
GAMING_MAJOR_TERMS = ["rockstar", "gta", "the witcher", "cd projekt", "playstation", "xbox game pass", "game pass", "steam", "nintendo", "major studio", "layoff", "acquisition", "lawsuit"]


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
    text = text.replace("INTERFAX.RU -", " ").replace("Москва.", " ")
    return re.sub(r"\s+", " ", text).strip()


def esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


def attr(value) -> str:
    return html.escape(str(value or ""), quote=True)


def norm_text(*parts: str) -> str:
    text = " ".join(str(p or "") for p in parts).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def blob(item: Dict) -> str:
    return norm_text(*(str(item.get(k) or "") for k in ("title_original", "title_ru", "source_text", "post_text", "edited_post_text", "url", "source", "category", "category_hint")))


def has_any(text: str, terms: List[str]) -> bool:
    text = norm_text(text)
    return any(term.lower().replace("ё", "е") in text for term in terms)


def cyrillic_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return 0.0
    cyr = re.findall(r"[А-Яа-яЁё]", text or "")
    return len(cyr) / max(1, len(letters))


def is_russian_post(title: str, body: List[str]) -> bool:
    return cyrillic_ratio(f"{title} " + " ".join(body or [])) >= 0.45


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


def sentence_split(text: str) -> List[str]:
    text = clean(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out, seen = [], set()
    for s in parts:
        s = clean(s)
        if len(s) < 35:
            continue
        key = re.sub(r"\W+", "", s.lower())[:110]
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:360])
    return out


def is_weak_alert_without_consequences(text: str) -> bool:
    return has_any(text, WEAK_ALERT_TERMS) and not has_any(text, HARD_IMPACT_TERMS)


def should_force_law_politics(text: str) -> bool:
    return has_any(text, LAW_POLITICS_TERMS) and not has_any(text, HARD_IMPACT_TERMS)


def category_fix(item: Dict) -> str:
    text = blob(item)
    source_type = item.get("source_type") or ""
    category = item.get("category") or item.get("category_hint") or ""
    if source_type == "world" and has_any(text, RUSSIA_TERMS):
        return "🌍 Мир о России"
    if "interfax.ru/world" in text or (source_type == "world" and has_any(text, SECURITY_TERMS)):
        return "🧭 Геополитика"
    if source_type == "gaming":
        return "🎮 Игры / индустрия"
    if source_type == "it" or has_any(text, IT_MAJOR_TERMS):
        return "🌐 Мировые IT"
    if should_force_law_politics(text):
        return "🇷🇺 РФ / законы и политика"
    if has_any(text, ECON_TERMS) and not has_any(text, ["бпла", "атака", "удар", "ранен", "погиб"]):
        return "🇷🇺 РФ / экономика"
    if has_any(text, ["путин", "си цзиньпин", "китай", "переговор", "саммит", "визит"]):
        return "🇷🇺 РФ / законы и политика"
    return category


def make_post(category: str, title: str, body: List[str], url: str, source: str) -> str:
    footer = FOOTERS.get(category, category)
    return f"{esc(category)}\n\n<b>{esc(title)}</b>\n\n" + "\n\n".join(esc(x) for x in body if x) + f"\n\n{esc(footer)} · <a href=\"{attr(url)}\">{esc(source)}</a>"


def special_rewrite(item: Dict, category: str) -> Optional[Tuple[str, List[str]]]:
    text = blob(item)
    if "google" in text and "smart glasses" in text:
        return "Google готовит новые умные очки с Gemini", ["Google показала новые умные очки — первую попытку вернуться в этот формат после неудачи Google Glass.", "Модель должна выйти осенью и получить камеру, динамики и интеграцию с ИИ Gemini.", "Компания делает ставку на формат hands free: очки смогут помогать пользователю без постоянного обращения к смартфону."]
    if "putin enjoys xi" in text or "pipeline deal" in text:
        return "BBC: Путин вернулся из Китая без сделки по газопроводу", ["BBC пишет, что Россия и Китай демонстрируют близость на мировой сцене, но переговоры не привели к ожидаемой сделке по трубопроводу.", "В материале отмечается, что отношения Москвы и Пекина остаются важными, но имеют пределы и дисбаланс интересов."]
    if "austrian ex-intelligence" in text and "russia spying" in text:
        return "В Австрии экс-сотрудника разведки осудили по делу о шпионаже в пользу России", ["Суд в Вене признал бывшего сотрудника австрийской разведки виновным по делу о передаче информации российской стороне.", "Этот процесс снова поднял вопрос о российской разведывательной активности в Австрии."]
    if "game pass" in text and "xbox" in text and not has_any(text, DEAL_TERMS):
        return "Microsoft раскрыла новую подборку игр для Xbox Game Pass", ["Microsoft объявила очередную подборку игр, которые появятся в Xbox Game Pass в мае и начале следующего месяца.", "Для игровой индустрии это сервисная новость: Game Pass остаётся одним из ключевых инструментов удержания аудитории Xbox и PC."]
    if "the witcher" in text and ("writer" in text or "lead writer" in text):
        return "К спин-оффу The Witcher привлекли сценаристку Destiny 2", ["К проблемному спин-оффу The Witcher присоединилась Кван Пернг, известная по работе над Destiny 2: The Final Shape.", "Она стала новым ведущим сценаристом проекта. Для CD Projekt это может быть попыткой усилить сюжетную часть игры после сложного периода разработки."]
    if "три человека ранены" in text and "бпла" in text:
        return "Три человека ранены в ДНР при атаке БПЛА", ["В ДНР три мирных жителя получили ранения в результате атаки БПЛА, сообщил глава региона Денис Пушилин.", "По данным источника, пострадавшим оказывается медицинская помощь."]
    if "долгосрочных вклад" in text:
        return "Правительство РФ рассмотрит меры по долгосрочным вкладам", ["Правительство РФ рассмотрит изменения в закон о страховании вкладов, направленные на повышение привлекательности долгосрочных депозитов.", "Цель — привлечь в банковский сектор ресурсы для долгосрочных инвестиций в экономику."]
    return None


def generic_rewrite(item: Dict, category: str) -> Tuple[str, List[str]]:
    title = clean(item.get("title_ru") or item.get("title_original") or "")
    body = []
    for s in sentence_split(item.get("source_text") or ""):
        low = s.lower()
        if any(x in low for x in ["читать далее", "continue reading", "sign in", "support us"]):
            continue
        s = re.sub(r"(.{35,160})\s+\1", r"\1", s)
        body.append(s)
        if len(body) >= 2:
            break
    return title, body


def published_sets() -> Tuple[set, set]:
    state = load_json(STATE_FILE, {})
    return set(state.get("published_urls", []) or []), set(state.get("published_title_hashes", []) or [])


def reject_reason(item: Dict, category: str, urls: set, hashes: set) -> Optional[str]:
    text = blob(item)
    if item.get("url") in urls or item.get("title_hash") in hashes:
        return "Отклонено автоматически: уже опубликовано ранее."
    published_age = age_hours(item.get("published_at") or item.get("created_at"))
    pending_age = age_hours(item.get("created_at"))
    if published_age is not None and published_age > 36:
        return "Отклонено автоматически: материал устарел для новостной ленты."
    if pending_age is not None and pending_age > PENDING_MAX_HOURS:
        return "Отклонено автоматически: черновик слишком долго висел без публикации."
    if has_any(text, DOWNLOAD_TERMS):
        return "Отклонено автоматически: страница загрузки/драйверов, не новость."
    if has_any(text, DEAL_TERMS):
        return "Отклонено автоматически: скидка/товарный материал, не новость."
    if has_any(text, TUTORIAL_TERMS):
        return "Отклонено автоматически: обучающая/колоночная статья, не новость."
    if has_any(text, WEAK_DECLARATION_TERMS):
        return "Отклонено автоматически: слабая декларативная новость без достаточной фактуры."
    if category == "🇷🇺 РФ / война и безопасность":
        if is_weak_alert_without_consequences(text):
            return "Отклонено автоматически: слабая тревожная новость без жертв, ущерба или серьёзных последствий."
        if should_force_law_politics(text):
            return "Отклонено автоматически: материал относится к законам/политике, а не к военной безопасности."
        if not has_any(text, HARD_IMPACT_TERMS + ["с-400", "минобороны", "фсб"]):
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
    text = blob(item)
    score = CATEGORY_WEIGHT.get(category, 0)
    if has_any(text, ["putin", "путин", "xi", "си", "pipeline", "gas", "oil", "санкц", "бпла", "iran", "иран", "google", "openai"]):
        score += 80
    if category == "🎮 Игры / индустрия":
        score -= 250
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
        item["reviewed_by"] = "auto-editor"
        item["category"] = category
        if reason:
            item["status"] = "rejected"
            if has_any(blob(item), DEAL_TERMS + DOWNLOAD_TERMS):
                item["image_decision"] = "drop"
            item.setdefault("editor_notes", []).append(reason)
            continue
        if approved >= APPROVE_LIMIT or score < 650:
            item["status"] = "hold"
            item.setdefault("editor_notes", []).append("В резерве: ниже текущих приоритетов канала или требует ручной оценки.")
            continue
        special = special_rewrite(item, category)
        title, body = special if special else generic_rewrite(item, category)
        if not title or not body or not is_russian_post(title, body):
            item["status"] = "hold"
            item.setdefault("editor_notes", []).append("В резерве: нет безопасного русскоязычного текста для публикации.")
            continue
        item["status"] = "approved"
        item["title_ru"] = title
        item["body"] = body
        item["post_text"] = make_post(category, title, body, item.get("url") or "", item.get("source") or "Источник")
        item["edited_post_text"] = item["post_text"]
        item["image_decision"] = "use" if item.get("image_url") else "none"
        item["with_image"] = bool(item.get("image_url"))
        item.setdefault("editor_notes", []).append("Одобрено автоматическим редактором: соответствует приоритетам, текст русифицирован и очищен.")
        approved += 1
    queue["updated_at"] = now_utc()
    queue["updated_at_sakhalin"] = now_sakh()
    queue["reviewed_at"] = now_utc()
    queue["reviewed_at_sakhalin"] = now_sakh()
    queue["auto_review"] = {"reviewed_pending": reviewed, "approved": approved, "approve_limit": APPROVE_LIMIT, "reviewed_at": queue["reviewed_at"], "reviewed_at_sakhalin": queue["reviewed_at_sakhalin"]}
    save_json(QUEUE_FILE, queue)
    print(f"auto-review: reviewed={reviewed}, approved={approved}")


if __name__ == "__main__":
    review_queue()
