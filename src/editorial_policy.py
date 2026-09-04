"""Authoritative deterministic editorial ontology for SkySakhNews.

The policy answers five questions before a post can reach Telegram:
1. Is this a current, public-interest news event rather than filler?
2. What is the event's real geography?
3. Which stream/category is supported by the headline and article?
4. Does the source headline require a safe deterministic correction?
5. Does the final post still satisfy the same contract?

Publisher identity is provenance, not geography. A Sakhalin publisher can carry
a federal story; a Russian publisher can carry a foreign story.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

import editorial_gate as gate

VERSION = "policy-v2.1"

CATEGORY_GROUP = {
    "sakh": "local",
    "sakh_chp": "local",
    "sakh_quake": "local",
    "ru_pol": "ru_pol",
    "ru_eco": "ru_eco",
    "ru_security": "ru_safety",
    "ru_incident": "ru_safety",
    "world_ru": "world",
    "geo": "world",
    "it": "it",
}

LOCAL_MARKERS = (
    "сахалин", "сахалинск", "сахалинц", "южно сахалинск", "корсаков",
    "холмск", "долинск", "поронайск", "невельск", "анив", "углегорск",
    "шахтерск", "александровск сахалин", "оха", "ноглик", "макаров",
    "томари", "тымовск", "смирных", "северо курильск", "южно курильск",
    "курил", "итуруп", "кунашир", "шикотан", "парамушир", "монерон",
    "рейдово", "малокурильск", "охотское море",
)

RUSSIA_MARKERS = (
    "россия", "российск", "рф", "москва", "кремл", "путин", "лавров",
    "госдум", "совфед", "правительство россии", "мид россии", "цб рф",
    "росавиац", "минобороны россии", "росстат", "фнс", "дальний восток",
    "дфо", "амурская область", "белгородская область", "ростовская область",
    "russia", "russian", "moscow", "kremlin", "putin", "lavrov",
)

FOREIGN_MARKERS = (
    "сша", "америк", "трамп", "канада", "канад", "мексик", "иран",
    "израил", "китай", "тайван", "нато", "евросоюз", "британ", "лондон",
    "франц", "париж", "герман", "берлин", "япон", "токио", "корея",
    "украин", "зеленск", "киев", "турц", "сири", "ирак", "индия",
    "пакистан", "армени", "казахстан", "белорус", "грузия", "азербайдж",
    "молдов", "куба", "вашингтон", "пекин", "брюссел", "оон", "g7",
    "g20", "usa", "u s", "united states", "canada", "mexico", "iran",
    "israel", "china", "taiwan", "nato", "ukraine", "japan", "germany",
    "france", "britain", "uk", "turkey", "syria", "india", "white house",
)

WORLD_MEDIA = (
    "bbc", "reuters", "guardian", "associated press", "ap news",
)
LOCAL_MEDIA = ("sakhalinmedia", "astv", "sakh.online", "sakh online")
RUSSIAN_MEDIA = ("interfax", "интерфакс", "tass", "тасс")
DOMESTIC_PATHS = (
    "/russia/", "/moscow/", "/business/", "/economy/", "/politics/",
    "/politika/", "/ekonomika/",
)

CALENDAR_HISTORY = (
    "в этот день", "день в истории", "календарь событий", "историческая дата",
    "памятная дата", "годовщина", "лет назад", "в 1945 году", "в 1941 году",
    "история праздника", "страницы истории",
)
CEREMONY = (
    "наградили", "награждение", "поздравили", "вручили наград", "вручили знак",
    "торжественная церемония", "чествовали", "почтили память", "отметили юбилей",
    "праздничный концерт", "доброволец сахалинской области", "открыли аллею славы",
)
LIFESTYLE = (
    "гороскоп", "рецепт", "народные приметы", "церковный праздник",
    "тест на внимательность", "головолом", "лайфхак", "как выбрать",
    "как сэкономить", "что приготовить", "куда поехать", "где отдохнуть",
    "райское место", "по карману", "сентябрьский хит", "от 1000 руб",
    "не санаторий и не дача", "модные тренды", "дачный совет", "огород",
    "удобрени", "черенк", "томаты", "косметолог", "уголки губ",
)
ADVERTORIAL = (
    "на правах рекламы", "партнерский материал", "партнёрский материал",
    "спецпроект", "акция действует", "скидка", "успейте купить",
    "подробнее на сайте", "открыл первый офис", "совместное исследование",
)
SERVICE_NOTICE = (
    "чтобы вернуть ему вещи", "чтобы вернуть ей вещи", "вернуть документы",
    "вернуть ему документы", "вернуть ей документы", "найденные вещи",
    "найденные документы", "разыскивают владельца", "ищут владельца",
    "просьба откликнуться", "владелец может забрать", "разыскивают хозяина",
    "чтобы вернуть найденное", "вернуть найденные вещи",
)
ACTUAL_MISSING_PERSON = (
    "пропал без вести", "пропала без вести", "не выходит на связь",
    "местонахождение неизвестно", "ушел и не вернулся", "ушла и не вернулась",
)
ROUTINE_EVENT = (
    "туристический форум", "открылся туристический форум", "состоялся туристический форум",
    "прошел туристический форум", "прошёл туристический форум",
    "провел выездное совещание", "провёл выездное совещание",
    "встреча с жителями", "отчетный концерт", "отчётный концерт",
)
CLICKBAIT = (
    "шок", "срочно", "ужас", "вы не поверите", "райское", "хит",
    "по карману", "трое пьяных", "пять пьяных", "шесть без прав",
    "16 без прав", "почти 100 нарушителей",
)

QUAKE = (
    "землетряс", "магнитуд", "эпицентр", "сейсм", "толчок", "цунами",
    "earthquake", "magnitude", "epicentre", "epicenter", "seismic",
)
VIOLENT_CRIME = (
    "убийств", "зарезал", "зарезали", "ножев", "ранил", "изнасил",
    "напал", "нападен", "удерживал", "лишение свободы", "заложник",
    "похищение человека", "избил до смерти", "обвиняют в убийстве",
    "обвиняемому в убийстве", "скончалась в больнице", "murder", "murdered",
    "stabbed", "hostage", "kidnapped", "killed by attacker",
)
FATAL = (
    "погиб", "погибли", "скончал", "умер", "умерла", "умерли", "жертв",
    "смертельн", "killed", "died", "dead", "deaths", "fatal",
)
ACCIDENT_EMERGENCY = (
    "дтп", "авари", "пожар", "возгорани", "обруш", "крушен", "опрокинул",
    "сошел с проезжей части", "сошёл с проезжей части", "наводнен", "подтоп",
    "эвакуац", "спасател", "мчс", "crash", "fire", "explosion", "flood",
    "collapse", "evacuated", "emergency",
)
SECURITY = (
    "бпла", "беспилот", "дрон", "пво", "всу", "обстрел", "ракет",
    "воздушная тревога", "воздушная опасность", "минобороны", "теракт",
    "террорист", "диверс", "взрывное устройство", "перехват", "сбили",
    "drone", "missile", "air strike", "airstrike", "shelling", "terror",
    "military attack", "warship", "air defence", "air defense",
)
FRAUD = (
    "мошенн", "выманил", "выманили", "лишилась денег", "лишился денег",
    "перевел деньги", "перевела деньги", "безопасный счет", "безопасный счёт",
    "липов инвести", "подделывать голоса", "обманули", "fraud", "scam",
)
TRAFFIC_ENFORCEMENT = (
    "гибдд", "гаи", "нарушител", "без прав", "пьяных", "профилактический рейд",
    "нарушения пдд", "штрафов",
)
ROUTINE_CRIME = (
    "краж", "украл", "украли", "уголовное дело", "задержали", "задержан",
    "наркотик", "нелегальный улов", "суд взял под стражу", "возбудили дело",
    "theft", "arrested", "detained", "drug seizure",
)

INFRA_ACTION = (
    "открыл", "открыли", "запустил", "запустили", "построил", "построили",
    "ввели в эксплуатацию", "завершили ремонт", "отремонтировали", "восстановили",
    "начали строительство", "одобрили строительство", "профинансирует",
    "включили программу", "включении программы", "opened", "launched", "built",
    "commissioned", "restored", "approved funding",
)
INFRA_ASSET = (
    "мост", "дорог", "аэропорт", "больниц", "поликлиник", "школ", "детский сад",
    "центр", "газификац", "водоснабжен", "электроснабжен", "теплоснабжен",
    "железнодорож", "поезд", "порт", "жилье", "жильё", "котельн", "сеть",
    "bridge", "road", "airport", "hospital", "school", "rail", "port",
)
PUBLIC_SERVICE = (
    "без света", "без воды", "отключат", "отключили", "перекроют", "закроют дорогу",
    "ограничили движение", "изменили схему движения", "горячую воду отключат",
    "холодной воды", "электроэнергии", "теплоснабжение", "водоснабжение",
    "power outage", "water outage", "road closed", "service disruption",
)
WEATHER = (
    "погода", "дожд", "ливен", "снег", "метел", "циклон", "шторм",
    "ветер", "туман", "мороз", "жара", "температур", "тайфун", "weather",
    "storm", "rain", "snow", "typhoon", "temperature",
)
SEVERE_WEATHER = (
    "опасн", "предупрежд", "шторм", "ураган", "тайфун", "метел", "сильный ливень",
    "очень сильный дождь", "угроза подтопления", "лавин", "warning", "severe",
    "hurricane", "dangerous",
)
AIR_QUALITY = (
    "дым", "гарь", "задымлен", "завеса в воздухе", "качество воздуха",
    "wildfire smoke", "air quality", "smoke haze",
)

POLICY_ACTOR = (
    "президент", "правительство", "госдум", "совфед", "кремл", "министр",
    "губернатор", "мид", "совбез", "кабмин", "депутат", "путин",
    "president", "government", "parliament", "congress", "prime minister",
)
POLICY_ACTION = (
    "утвердил", "утвердили", "подписал", "принял закон", "приняли закон",
    "ввел", "ввели", "одобрил", "одобрили", "законопроект", "постановлен",
    "режим запустят", "особый правовой режим", "объявил", "поручил",
    "approved", "signed", "adopted", "introduced a bill", "banned", "imposed",
)
SPEECH_ONLY = (
    "заявил", "сообщил", "рассказал", "считает", "призвал", "выступил",
    "said", "says", "called for", "addressed",
)
MACRO_ECONOMY = (
    "центробанк", "цб рф", "ключевая ставка", "инфляц", "бюджет", "минфин",
    "ввп", "рубль", "налог", "экспорт", "импорт", "рынок труда", "безработиц",
    "рынок сбережений", "трлн рублей", "инвестиц", "газификац", "тариф",
    "приватизац", "втб", "сбер", "росстат", "фнс", "central bank", "inflation",
    "interest rate", "gdp", "budget", "tariff", "exports", "imports",
)
CORPORATE_FORECAST = (
    "прогноз втб", "по прогнозам втб", "рынок сбережений", "может вырасти",
    "ожидает роста", "прогнозирует рост", "forecast", "expects growth",
)
DIPLOMACY = (
    "отношени", "переговор", "санкц", "посол", "саммит", "договор", "соглашен",
    "позиция токио", "позиция вашингтона", "позиция пекина", "дипломат",
    "прекращение огня", "мирный план", "пошлин", "нефть российск", "relations",
    "talks", "negotiations", "sanctions", "summit", "treaty", "agreement",
    "ceasefire", "peace plan", "tariffs", "diplomatic",
)
MAJOR_WORLD = (
    "войн", "конфликт", "санкц", "удар", "атака", "выборы президента",
    "переговор", "саммит", "нато", "g7", "g20", "ядерн", "пошлин",
    "war", "conflict", "attack", "election", "nuclear", "sanctions", "summit",
)
IT_CORE = (
    "openai", "chatgpt", "anthropic", "claude", "gemini", "нейросет",
    "искусственный интеллект", "nvidia", "amd", "intel", "microsoft", "apple",
    "google", "android", "ios", "linux", "windows", "кибератак", "утечка данных",
    "уязвимост", "чип", "процессор", "полупроводник", "новая модель ии",
    "artificial intelligence", "cyberattack", "data breach", "vulnerability",
    "semiconductor", "processor", "chip",
)
IT_TIPS = (
    "смартфон можно ускорить", "одним способом", "названы профессии", "эксперты советуют",
    "технологически продвинутые пенсионеры", "how to speed up", "tips to improve",
)

SOURCE_SUFFIX_RE = re.compile(
    r"\s*(?:-|—|\|)\s*(?:SakhalinMedia(?:\.ru)?|ASTV(?:\.RU)?|SAKH\.ONLINE|Sakh\.online|Interfax|TASS|ТАСС)\s*$",
    re.I,
)

EXACT_SINGLE_MARKERS = {
    "рф", "сша", "оон", "нато", "g7", "g20", "usa", "uk", "nato",
    "умер", "dead",
}

BOILERPLATE_PATTERNS = (
    r"Читайте последние актуальные новости.*?(?=[А-ЯA-Z])",
    r"Мы будем присылать вам на почту.*$",
    r"Подпишись на самые важные новости.*$",
    r"Подписывайтесь на.*$",
    r"по оценке\s+\d+\s+пользовател.*$",
    r"©\s*20\d{2}.*$",
    r"Подробности здесь\s*\.?",
)


@dataclass
class Classification:
    category_key: Optional[str]
    group: Optional[str]
    event_type: str
    hard_reject_reason: Optional[str] = None
    local: bool = False
    foreign: bool = False
    russia: bool = False
    source_world: bool = False
    source_local: bool = False
    source_russian: bool = False
    features: Set[str] = field(default_factory=set)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["features"] = sorted(self.features)
        return value


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    return gate._norm(value)


def tokens(value: Any) -> List[str]:
    return re.findall(r"[a-zа-я0-9]+", norm(value), flags=re.I)


def marker_match(text: str, marker: str) -> bool:
    words = tokens(text)
    marker_words = tokens(marker)
    if not words or not marker_words:
        return False
    if len(marker_words) == 1 and marker_words[0] in EXACT_SINGLE_MARKERS:
        return marker_words[0] in words
    width = len(marker_words)
    for start in range(len(words) - width + 1):
        window = words[start:start + width]
        if all(word.startswith(prefix) for word, prefix in zip(window, marker_words)):
            return True
    return False


def has_any(text: str, markers: Sequence[str]) -> bool:
    return any(marker_match(text, marker) for marker in markers)


def matched(text: str, markers: Sequence[str]) -> List[str]:
    return [marker for marker in markers if marker_match(text, marker)]


def patch_gate_matching() -> None:
    gate._contains = has_any
    gate.LOCAL_MARKERS = LOCAL_MARKERS
    gate.WEATHER = WEATHER
    gate.QUAKE = QUAKE
    gate.SECURITY = SECURITY
    gate.INCIDENT = (
        VIOLENT_CRIME + FATAL + ACCIDENT_EMERGENCY + FRAUD
        + ROUTINE_CRIME + ACTUAL_MISSING_PERSON + AIR_QUALITY
    )
    gate.ECONOMY = MACRO_ECONOMY
    gate.POLITICS = POLICY_ACTOR + POLICY_ACTION
    gate.IT = IT_CORE
    gate.FOREIGN = FOREIGN_MARKERS
    gate.RUSSIA = RUSSIA_MARKERS


patch_gate_matching()


def source_flags(candidate: Mapping[str, Any]) -> Tuple[bool, bool, bool, bool]:
    source = norm(candidate.get("source"))
    parsed = urlparse(str(candidate.get("url") or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    value = f"{source} {host}"
    source_world = any(marker in value for marker in WORLD_MEDIA)
    source_local = any(marker in value for marker in LOCAL_MEDIA)
    source_russian = any(marker in value for marker in RUSSIAN_MEDIA)
    domestic_path = any(marker in path for marker in DOMESTIC_PATHS)
    return source_world, source_local, source_russian, domestic_path


def strip_source_suffix(title: Any) -> str:
    value = clean(title)
    value = SOURCE_SUFFIX_RE.sub("", value).strip(" -—|:")
    return re.sub(r"\s+", " ", value).strip()


def clean_article_text(value: Any, *, limit: int = 3000) -> str:
    text = clean(value)
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I | re.S)
    text = re.sub(r"\s+", " ", text).strip()

    # Remove adjacent duplicate sentences produced by RSS + page concatenation.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: List[str] = []
    seen: Set[str] = set()
    for sentence in sentences:
        sentence = clean(sentence)
        key = norm(sentence)
        if len(key) < 20:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(sentence)
    return " ".join(result)[:limit].strip()


def parse_ruble_amount(text: str) -> int:
    maximum = 0.0
    for match in re.finditer(
        r"(?P<number>\d+(?:[\s.,]\d+)*)\s*(?P<unit>млрд|миллиард(?:а|ов)?|млн|миллион(?:а|ов)?|тыс(?:яч[аиу]?)?|тысяч(?:а|и)?)?\s*(?:руб(?:лей|ля|ль|\.)?)",
        norm(text),
        flags=re.I,
    ):
        raw = match.group("number").replace(" ", "").replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            continue
        unit = match.group("unit") or ""
        if unit.startswith("млрд") or unit.startswith("миллиард"):
            number *= 1_000_000_000
        elif unit.startswith("млн") or unit.startswith("миллион"):
            number *= 1_000_000
        elif unit.startswith("тыс"):
            number *= 1_000
        maximum = max(maximum, number)
    return int(maximum)


def _hard_reject(title: str, lead: str) -> Optional[str]:
    combined = f"{title} {lead}"
    if has_any(title, CALENDAR_HISTORY):
        return "calendar_or_archive"
    if has_any(title, CEREMONY):
        return "ceremony_or_congratulation"
    if has_any(combined, LIFESTYLE):
        return "lifestyle_or_seo"
    if has_any(combined, ADVERTORIAL):
        return "advertorial_or_corporate_pr"
    if has_any(title, ("туристический форум",)):
        return "routine_event_without_outcome"
    if has_any(title, ROUTINE_EVENT) and not has_any(title, POLICY_ACTION + INFRA_ACTION):
        return "routine_event_without_outcome"
    if has_any(combined, SERVICE_NOTICE) and not has_any(combined, ACTUAL_MISSING_PERSON):
        return "service_or_lost_and_found_notice"
    if has_any(title, IT_TIPS):
        return "soft_technology_advice"
    return None


def _is_infrastructure(title: str) -> bool:
    return has_any(title, INFRA_ACTION) and has_any(title, INFRA_ASSET)


def _is_policy(title: str) -> bool:
    return has_any(title, POLICY_ACTION) or (
        has_any(title, POLICY_ACTOR)
        and has_any(title, ("закон", "режим", "правило", "поручение", "bill", "law"))
    )


def _event_type(title: str, lead: str, *, foreign: bool) -> str:
    combined = f"{title} {lead}"
    if has_any(title, QUAKE):
        return "earthquake"
    if has_any(combined, VIOLENT_CRIME):
        return "violent_crime"
    if has_any(combined, FATAL) and has_any(combined, ACCIDENT_EMERGENCY + ROUTINE_CRIME):
        return "fatal_incident"
    if has_any(title, SECURITY):
        return "military_security"
    if has_any(title, ACCIDENT_EMERGENCY):
        return "major_emergency"
    if has_any(title, ACTUAL_MISSING_PERSON):
        return "missing_person"
    if has_any(title, FRAUD):
        return "fraud"
    if has_any(title, TRAFFIC_ENFORCEMENT) and not has_any(title, FATAL + ACCIDENT_EMERGENCY):
        return "traffic_enforcement"
    if has_any(title, PUBLIC_SERVICE):
        return "public_service_disruption"
    if _is_infrastructure(title):
        return "major_infrastructure"
    if has_any(title, WEATHER):
        return "severe_weather" if has_any(title, SEVERE_WEATHER) else "ordinary_weather"
    if has_any(title, AIR_QUALITY):
        return "air_quality_hazard"
    if _is_policy(title):
        return "political_decision"
    if has_any(title, MACRO_ECONOMY):
        return "corporate_forecast" if has_any(title, CORPORATE_FORECAST) else "macro_economy"
    if foreign and (has_any(title, DIPLOMACY) or has_any(title, MAJOR_WORLD) or has_any(title, SECURITY)):
        return "geopolitical_event"
    if has_any(title, IT_CORE):
        return "major_it"
    if has_any(title, ROUTINE_CRIME):
        return "routine_crime"
    if has_any(title, SPEECH_ONLY) and has_any(title, POLICY_ACTOR):
        return "political_statement"
    return "general"


def classify(candidate: Mapping[str, Any]) -> Classification:
    title = strip_source_suffix(candidate.get("title"))
    lead = clean_article_text(candidate.get("source_text"), limit=1800)
    combined = f"{title} {lead}"
    source_world, source_local, source_russian, domestic_path = source_flags(candidate)

    hard = _hard_reject(title, lead)
    title_local = has_any(title, LOCAL_MARKERS)
    lead_local = has_any(lead, LOCAL_MARKERS)
    local = title_local or (source_local and lead_local)
    foreign = has_any(title, FOREIGN_MARKERS)
    russia = (
        has_any(title, RUSSIA_MARKERS)
        or has_any(lead[:900], RUSSIA_MARKERS)
        or (source_russian and domestic_path)
    )
    event_type = _event_type(title, lead, foreign=foreign)

    if hard:
        return Classification(
            None, None, event_type, hard, local, foreign, russia,
            source_world, source_local, source_russian,
            evidence={"title": title},
        )

    category_key: Optional[str] = None
    domestic_provenance = source_russian or source_local or domestic_path

    if local:
        if event_type == "earthquake":
            category_key = "sakh_quake"
        elif event_type in {
            "violent_crime", "fatal_incident", "military_security", "major_emergency",
            "missing_person", "fraud", "routine_crime", "air_quality_hazard",
        }:
            category_key = "sakh_chp"
        else:
            category_key = "sakh"
    elif source_world and russia and event_type not in {
        "general", "ordinary_weather", "traffic_enforcement", "routine_crime",
    }:
        category_key = "world_ru"
    elif foreign and event_type in {
        "geopolitical_event", "military_security", "political_decision",
    }:
        category_key = "geo"
    elif event_type == "major_it":
        category_key = "it"
    elif event_type == "military_security" and domestic_provenance:
        category_key = "ru_security"
    elif event_type in {
        "violent_crime", "fatal_incident", "major_emergency", "missing_person",
        "fraud", "routine_crime",
    } and domestic_provenance:
        category_key = "ru_incident"
    elif event_type in {"macro_economy", "corporate_forecast", "major_infrastructure"} and domestic_provenance:
        category_key = "ru_eco"
    elif event_type in {"political_decision", "political_statement"} and domestic_provenance:
        category_key = "ru_pol"

    group = CATEGORY_GROUP.get(category_key) if category_key else None
    features: Set[str] = set()
    for name, condition in (
        ("local_title", title_local),
        ("local_lead", lead_local),
        ("foreign_title", foreign),
        ("russia_context", russia),
        ("source_world", source_world),
        ("source_local", source_local),
        ("source_russian", source_russian),
        ("domestic_path", domestic_path),
        ("clickbait", has_any(title, CLICKBAIT)),
    ):
        if condition:
            features.add(name)

    return Classification(
        category_key=category_key,
        group=group,
        event_type=event_type,
        hard_reject_reason=None if category_key else "no_supported_news_stream",
        local=local,
        foreign=foreign,
        russia=russia,
        source_world=source_world,
        source_local=source_local,
        source_russian=source_russian,
        features=features,
        evidence={
            "title": title,
            "clean_lead": lead[:900],
            "title_local": title_local,
            "lead_local": lead_local,
            "money_rub": parse_ruble_amount(combined),
            "matched_fatal": matched(combined, FATAL),
            "matched_harm": matched(combined, VIOLENT_CRIME + FRAUD),
        },
    )


def autocorrect_title(candidate: Mapping[str, Any], classification: Classification) -> Tuple[str, List[str]]:
    original = strip_source_suffix(candidate.get("title"))
    lead = clean_article_text(candidate.get("source_text"), limit=1800)
    title = original
    reasons: List[str] = []

    replacements = (
        (r"\bудерживал\s+в\s+(сожительниц\w*)", r"удерживал \1"),
        (r"\bудерживал\s+в\s+(женщин\w*)", r"удерживал \1"),
        (r"\s+-\s+-\s+", " — "),
    )
    for pattern, replacement in replacements:
        corrected = re.sub(pattern, replacement, title, flags=re.I)
        if corrected != title:
            title = corrected
            reasons.append("grammar_pattern_fixed")

    if (
        classification.event_type == "violent_crime"
        and has_any(lead, (
            "обвиняемому в убийстве", "обвиняют в убийстве",
            "обвинение в убийстве", "предъявлено обвинение в убийстве",
        ))
        and has_any(lead, ("под стражу", "заключение под стражу"))
    ):
        title = (
            "Сахалинца заключили под стражу по обвинению в убийстве женщины"
            if classification.local
            else "Мужчину заключили под стражу по обвинению в убийстве женщины"
        )
        reasons.append("violent_crime_fact_template")

    title = re.sub(r"\s+", " ", title).strip(" -—|:")
    title = title[:180].rstrip(" ,;:-")
    if title and title[-1] in ".!?":
        title = title[:-1]
    return title, reasons


def title_quality_issues(title: str) -> List[str]:
    value = clean(title)
    issues: List[str] = []
    if len(value) < 24:
        issues.append("title_too_short")
    if len(value) > 180:
        issues.append("title_too_long")
    if SOURCE_SUFFIX_RE.search(value):
        issues.append("source_suffix_in_title")
    if re.search(r"\bудерживал\s+в\s+(?:сожительниц|женщин)", norm(value)):
        issues.append("broken_government_pattern")
    if re.search(r"\b(\w+)\s+\1\b", norm(value)):
        issues.append("duplicated_word")
    if has_any(value, CLICKBAIT):
        issues.append("clickbait_title")
    if value.count('"') % 2 or value.count("«") != value.count("»"):
        issues.append("unbalanced_quotes")
    return issues


def final_contract(candidate: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
    final_title = clean(row.get("title_ru") or candidate.get("title"))
    final_body = " ".join(clean(value) for value in (row.get("body") or []) if clean(value))
    final_candidate = dict(candidate)
    final_candidate["title"] = final_title
    final_candidate["source_text"] = final_body or candidate.get("source_text")
    final_class = classify(final_candidate)
    expected = str(candidate.get("category_key") or "")
    title_issues = title_quality_issues(final_title)

    # The director's corrected headline is itself grounded in the original
    # article. The final draft is compared against that contract, while the
    # original headline remains part of the supporting source text.
    source_title = strip_source_suffix(candidate.get("title"))
    original_title = strip_source_suffix(candidate.get("title_original"))
    source_text = clean_article_text(candidate.get("source_text"), limit=3000)
    if original_title and original_title != source_title:
        source_text = f"{original_title}. {source_text}"
    title_score, title_precision, title_coverage = gate.title_source_metrics(
        source_title,
        source_text,
        final_title,
    )

    issues = list(title_issues)
    if final_class.hard_reject_reason:
        issues.append("final_hard_reject:" + final_class.hard_reject_reason)
    if final_class.category_key != expected:
        issues.append(f"final_category_mismatch:{final_class.category_key}->{expected}")
    if title_score < 78 or title_precision < 78 or title_coverage < 50:
        issues.append("final_title_not_grounded")

    return {
        "approved": not issues,
        "expected_category": expected,
        "final_category": final_class.category_key,
        "event_type": final_class.event_type,
        "title_score": title_score,
        "title_precision": title_precision,
        "title_coverage": title_coverage,
        "issues": issues,
        "policy_version": VERSION,
    }
