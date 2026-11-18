"""Source-bound depth checks for the scheduled mobilisation digest.

No Telegram writes, current-event assumptions, or network calls at import time.
Historical legal references remain historical; quotations require fetched text.
"""
from __future__ import annotations

import copy
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

VERSION = "mobilization-depth-v1"
LEGAL_PAGES = (
    ("stage_snapshot", "Госдума: карточка проекта", "https://sozd.duma.gov.ru/bill/1322096-8", r"1322096[-–]8"),
    ("bill_text", "ГАРАНТ: текст проекта", "https://base.garant.ru/411685332/", r"Неисполнение решения"),
    ("bill_rationale", "ГАРАНТ: пояснительная записка", "https://base.garant.ru/411685333/", r"Законопроект разработан|Целью законопроекта|В целях"),
    ("presidential_powers", "31-ФЗ, статья 4", "https://www.consultant.ru/document/cons_doc_LAW_13454/d3ebcd75ea7e860fa6718349b0f6ef1705dc1634/", r"объявляет общую или частичную мобилизацию"),
    ("regional_framework", "Указ Президента №757", "https://publication.pravo.gov.ru/Document/View/0001202210190003", r"Решения оперативных штабов|оперативные штабы"),
)


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def norm(value):
    return clean(value).casefold().replace("ё", "е")


def sentence_excerpt(value, limit=400):
    """Clip only on sentence/word boundaries, visibly marking incomplete excerpts."""
    value = clean(value)
    if len(value) <= limit:
        return value
    prefix = value[:limit]
    ends = list(re.finditer(r"[.!?](?:\s|$)", prefix))
    if ends and ends[-1].end() > limit // 2:
        return prefix[:ends[-1].end()].strip()
    return prefix.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def direct_civil_claim(item):
    """Do not turn every mention of a summons into 'clarification of records'."""
    title, body = clean(item.get("title")), clean(item.get("summary"))
    stamp = str(item.get("published_utc") or "")[:10]
    date_label = (stamp + ": ") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp) else "дата не установлена: "
    text = re.sub(r"^З\s+апасник", "Запасник", body or title)
    purpose = "Цель вызова отдельно не установлена."
    purposes = []
    low = norm(text)
    if re.search(r"уточнен\w* (?:воинск\w* |военно.учетн\w* )?(?:данных|учет)", low):
        purposes.append("уточнение учётных данных")
    if re.search(r"военн\w* сбор", low):
        purposes.append("военные сборы")
    if re.search(r"заключен\w* контракт|служб\w* по контракт|контрактн\w* служб", low):
        purposes.append("контрактная служба")
    if re.search(r"призыв\w* по мобилизац|повестк\w* (?:на|по) мобилизац", low):
        purposes.append("призыв по мобилизации — формулировка источника")
    if purposes:
        purpose = "В тексте обсуждаются категории: " + "; ".join(purposes) + "."
    fake = bool(re.search(r"фейков|поддельн", norm(title)))
    prefix = "Предупреждение проекта" if fake else "Сообщение проекта"
    return (
        f"{prefix} «Идите лесом», {date_label}"
        f"{sentence_excerpt(text, 320)} {purpose} "
        "Это сведения проекта, а не независимо проверенный масштаб призыва."
    )


def dated_queries(queries):
    """Rolling discovery must not stay pinned to September 2026."""
    out = []
    for group, query, lang, country in queries:
        query = re.sub(r"\bSeptember\s+20\d{2}\b|\bсентябр\w*\s+20\d{2}\b", "", query, flags=re.I)
        out.append((group, clean(query), lang, country))
    return out


def literal_quote(text, pattern, max_words=22):
    """An exact contiguous excerpt, never a quotation invented from a summary."""
    text = clean(text)
    match = re.search(pattern, text, re.I)
    if not match:
        return ""
    tail = text[match.start():]
    tokens = list(re.finditer(r"\S+", tail))
    if not tokens:
        return ""
    end = tokens[min(max_words, len(tokens)) - 1].end()
    quote = tail[:end]
    stop = re.search(r"[.!?](?:\s|$)", quote)
    if stop and stop.end() > 35:
        quote = quote[:stop.end()].strip()
    return quote


def source_quote(text, role):
    """Short complete syntactic fragments, not the first N header words."""
    patterns = {
        "presidential_powers": r"объявляет общую или частичную мобилизацию",
        "bill_text": r"за исключением случаев, предусмотренных статьей 20\.5\.1 (?:настоящего Кодекса|КоАП)",
        "bill_rationale": r"в целях установления административной ответственности за неисполнение решений",
        "regional_framework": r"являются обязательными для исполнения гражданами, организациями",
    }
    match = re.search(patterns.get(role, r"(?!)"), clean(text), re.I)
    return match.group(0) if match else ""


def fetch_legal_snapshots(get, strip_html):
    """Whitelisted parallel reads. Retrieval time is not a law's effective date."""
    def one(spec):
        role, name, url, pattern = spec
        try:
            response = get(url, timeout=(5, 14), headers={"User-Agent": "SkySakhNews evidence reader"})
            if response.status_code != 200:
                return None
            text = strip_html(response.text[:1_200_000])
            match = re.search(pattern, text, re.I)
            if not match or len(text) < 250:
                return None
            excerpt = text[max(0, match.start()-90):match.start()+3300]
            if role == "stage_snapshot":
                if not re.search(r"чтени|Федеральный закон|отклон|снят с рассмотрения", excerpt, re.I):
                    return None
                quote = ""
            else:
                quote = source_quote(text, role)
            return {
                "group": "law", "trust": 100 if role in {"stage_snapshot", "regional_framework"} else 98,
                "source": name, "title": name, "url": url,
                "summary": clean(excerpt), "published_utc": None,
                "legal_role": role, "evidence_kind": "retrieved_legal_text",
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "retrieved_text": clean(excerpt), "literal_quote": quote,
                "current_stage_verified": False,
            }
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        return [row for row in pool.map(one, LEGAL_PAGES) if row]


def merge_evidence(rows, snapshots, limit=42):
    """Preserve distinct historical and live evidence; group related bill pages."""
    out, seen = [], set()
    for raw in list(snapshots) + list(rows):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        url = str(row.get("url") or "")
        role = str(row.get("legal_role") or "")
        if role and not row.get("evidence_kind"):
            row["evidence_kind"] = "historical_reference"
            row["current_stage_verified"] = False
        kind = row.get("evidence_kind", "news_report")
        key = (url, role, kind)
        if key in seen:
            continue
        seen.add(key)
        if "1322096" in clean(row.get("title")) + clean(row.get("summary")) or any(x in url for x in ("411685332", "411685333", "414784137", "1322096")):
            row["event_family"] = "bill:1322096-8"
        else:
            row["event_family"] = url
        out.append(row)
    out.sort(key=lambda r: (r.get("group") not in {"law", "civil_society"}, not bool(r.get("retrieved_text")), -int(r.get("trust") or 0)))
    out = out[:limit]
    for i, row in enumerate(out, 1):
        row["id"] = i
    return out


def supported_basis(basis, by_id, axis):
    if not isinstance(basis, dict) or len(clean(basis.get("reasoning"))) < 60:
        return False
    refs = basis.get("source_ids") or []
    excerpt = clean(basis.get("evidence_excerpt"))
    if not refs or len(excerpt) < 30:
        return False
    if any(not str(i).isdigit() or int(i) not in by_id for i in refs):
        return False
    # Statutory powers alone are not evidence of manpower shortages or actual
    # readiness. Require a dated, current observational source and exact text.
    now = datetime.now(timezone.utc)
    patterns = {
        "near_term": r"мобилизац|комплектован|кадров|повестк|mobiliz|manpower|recruit",
        "staffing": r"потер|набор|комплектован|кадров|loss|manpower|recruit",
        "infrastructure": r"военком|сборн.{0,20}пункт|повестк|разверт|развёрт|deployment|draft notice",
    }
    for raw in refs:
        row = by_id[int(raw)]
        if row.get("group") == "law" or row.get("evidence_kind") == "historical_reference":
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get("published_utc") or "").replace("Z", "+00:00"))
            if stamp.tzinfo is None or not (-7200 <= (now-stamp).total_seconds() <= 8*86400):
                continue
        except (ValueError, TypeError):
            continue
        if excerpt in clean(row.get("summary")) and re.search(patterns[axis], excerpt, re.I):
            return True
    return False


def enrich_draft(draft, evidence):
    """Attach source-specific reasoning and reject conclusions from silence."""
    draft = copy.deepcopy(draft)
    # A model-supplied version flag is never permission to skip checks.
    law = [r for r in evidence if r.get("group") == "law"]
    civil = [r for r in evidence if r.get("group") == "civil_society"]
    isw = [r for r in evidence if r.get("group") == "isw"]
    ids = lambda rows: [int(r["id"]) for r in rows]
    legal = clean(draft.get("legal"))
    legal = legal.replace(
        "Предлагаемые, ещё НЕ действующие санкции:",
        "Санкции по проекту (вступление в силу отдельно не подтверждено):"
    )
    # Inline quotations inherited from a cached template are not live-document
    # quotations. Only the independently verified legal_quotes are rendered.
    legal = re.sub(
        r"Из текста проекта:\s*«[^»]+»\s*[—-]\s*это описание состава правонарушения, а не мобилизационный призыв\.",
        "Предлагаемый состав правонарушения не является решением о призыве.",
        legal,
    )
    legal = legal.replace(
        "Это не вступивший в силу штраф по новой статье.",
        "Это санкции из текста проекта; вступление новой статьи в силу отдельно не подтверждено."
    )
    if any(r.get("evidence_kind") == "historical_reference" for r in law) and "Текущая стадия отдельно не подтверждена" not in legal:
        legal += " Текущая стадия отдельно не подтверждена; приведённая контрольная дата не заменяет проверку карточки Госдумы и официального опубликования."
    roles = {r.get("legal_role") for r in law}
    if "bill_text" in roles and "Анализ: предмет проекта" not in legal:
        legal += " Анализ: предмет проекта — ответственность за неисполнение конкретного решения уполномоченного органа; сам проект не устанавливает факт призыва, численность или сроки новой волны."
    rationale = next((r for r in law if r.get("legal_role") == "bill_rationale" and r.get("retrieved_text")), None)
    if rationale and "Цель по пояснительной записке:" not in legal:
        legal += " Цель по пояснительной записке: установить федеральную ответственность за неисполнение решений региональных властей и оперштабов в пределах их компетенции."
    quotes = []
    for row in sorted(law, key=lambda r: {"presidential_powers": 0, "bill_text": 1, "bill_rationale": 2}.get(r.get("legal_role"), 3)):
        quote = clean(row.get("literal_quote"))
        if quote and quote in clean(row.get("retrieved_text")) and len(quote.split()) <= 25:
            quotes.append({"text": quote, "source_id": int(row["id"])})
    draft["legal"] = legal
    unique_quotes, quote_urls = [], set()
    for quote in quotes:
        row = next(r for r in law if int(r["id"]) == quote["source_id"])
        if row.get("url") not in quote_urls:
            unique_quotes.append(quote)
            quote_urls.add(row.get("url"))
    draft["legal_quotes"] = unique_quotes[:2]
    draft["section_sources"] = {"legal": ids(law), "practice": ids(civil), "isw": ids(isw)}
    by_id = {int(r["id"]): r for r in evidence}
    for item in draft.get("items") or []:
        refs = [by_id.get(int(i)) for i in item.get("source_ids", []) if str(i).isdigit()]
        own = next((r for r in refs if r and r.get("group") == "civil_society"), None)
        if own:
            item["status"] = "СООБЩЕНИЕ ПРОЕКТА — НЕЗАВИСИМО НЕ ПОДТВЕРЖДЕНО"
            item["text"] = direct_civil_claim(own)
    if civil:
        draft["practice"] = (
            "Сообщения «Идите лесом» включены с датами и конкретными ссылками. "
            "Цель каждой повестки берётся из её описания; учёт, сборы, контракт и призыв по мобилизации не отождествляются. "
            "Количество обращений не равно числу мобилизованных; общероссийский масштаб по этой выборке не установлен."
        )
    else:
        draft["practice"] = "Свежих доступных сообщений «Идите лесом» в этой выборке нет. Это ограничение покрытия, а не доказательство отсутствия повесток."
    basis = draft.get("assessment_basis") or {}
    assessment = dict(draft.get("assessment") or {})
    limits = {
        "near_term": "НЕДОСТАТОЧНО ДАННЫХ — отсутствие указа в выборке не означает низкий риск. Для пересмотра нужны проверенные кадровые и региональные операционные данные.",
        "staffing": "НЕ ОЦЕНЕНО — без сопоставимых данных о потерях, наборе и пополнении кадровое давление не измерено.",
        "infrastructure": "НОРМАТИВНАЯ БАЗА НЕ РАВНА ГОТОВНОСТИ — наличие полномочий не доказывает фактическую работу сборных пунктов и развёртывание инфраструктуры.",
    }
    for axis, default in limits.items():
        b = basis.get(axis) if isinstance(basis, dict) else None
        refs = b.get("source_ids", []) if isinstance(b, dict) else []
        valid = supported_basis(b, by_id, axis)
        if not valid:
            assessment[axis] = default
    if norm(assessment.get("started")).startswith(("не подтверждено", "нет —", "нет -")):
        assessment["started"] = (
            "НЕ УСТАНОВЛЕН ПО ВЫБОРКЕ — юридические акты и фактические мероприятия "
            "проверяются отдельно; отсутствие нового указа не исключает действий по прежним актам."
        )
    draft["assessment"] = assessment
    used = list(draft.get("source_ids") or [])
    for item in draft.get("items") or []:
        used.extend(item.get("source_ids") or [])
    used.extend(ids(law))
    draft["source_ids"] = list(dict.fromkeys(int(i) for i in used if str(i).isdigit() and int(i) in by_id))
    draft["depth_version"] = VERSION
    return draft


def depth_issues(draft, evidence):
    by_id = {int(r["id"]): r for r in evidence}
    issues = []
    for q in draft.get("legal_quotes") or []:
        row = by_id.get(q.get("source_id"), {})
        if not clean(q.get("text")) or clean(q["text"]) not in clean(row.get("retrieved_text")):
            issues.append("quotation_not_in_retrieved_document")
    for axis in ("near_term", "staffing", "infrastructure"):
        text = clean((draft.get("assessment") or {}).get(axis)).upper()
        if re.match(r"^(НИЗК|УМЕРЕН|ПОВЫШЕН|ВЫСОК|СРЕДН)", text):
            b = (draft.get("assessment_basis") or {}).get(axis) or {}
            if not supported_basis(b, by_id, axis):
                issues.append("unsupported_axis_rating:" + axis)
    return issues


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def visible_units(text):
    parser = _Visible()
    parser.feed(text)
    return len("".join(parser.parts).encode("utf-16-le")) // 2


def _plain_language_legal(draft, evidence):
    """Explain the *conditional* effect of the bill, never assert it is in force."""
    full = clean(draft.get("legal"))
    roles = {str(r.get("legal_role") or "") for r in evidence if r.get("group") == "law"}
    tokens = ("19.5.5", "31-ФЗ", "757", "3–5", "30–50", "300")
    if not set(("first_reading_baseline", "bill_text", "presidential_powers",
                "regional_framework")).issubset(roles):
        return None
    if not all(token in full for token in tokens):
        return None
    stage = next((r for r in evidence if r.get("legal_role") == "first_reading_baseline"), {})
    if not ("27.10.2026" in clean(stage.get("summary"))
            or "27 октября 2026" in clean(stage.get("summary"))):
        return None
    return {
        "possible": (
            "Проект №1322096-8 предлагает отдельные штрафы за неисполнение "
            "решений губернаторов и региональных оперштабов в пределах их "
            "полномочий. Если норму примут и она вступит в силу: "
            "для граждан — 3–5 тыс. ₽, должностных лиц — 30–50 тыс. ₽ "
            "(либо дисквалификация), организаций — 300 тыс.–1 млн ₽ "
            "(либо приостановление деятельности). "
            "Это НЕ штраф за любую повестку и НЕ решение о новой мобилизации."
        ),
        "current": (
            "27.10.2026 Госдума приняла проект в первом чтении. "
            "Это подтверждённая историческая стадия; актуальный статус и "
            "вступление в силу по данной выборке не установлены. "
            "По ст. 4 закона №31-ФЗ мобилизацию объявляет Президент. "
            "Указ №757 от 2022 года регулирует региональные штабы, "
            "но сам по себе не объявляет новую волну."
        ),
        "easing": (
            "В изученных материалах нет подтверждённого нового послабления "
            "для запасников по повесткам, сборам или выезду. "
            "Это ограничение выборки, а не утверждение, что послаблений вообще не было."
        ),
    }


def _practical_note(row):
    """Short, attributed description of actual source topics, without inferred calls."""
    title = clean(row.get("title"))
    body = clean(row.get("summary"))
    low = norm(title + " " + body)
    topics = []
    if "уточнен" in low and ("данн" in low or "учет" in low):
        topics.append("уточнение данных")
    if re.search(r"военн\w* сбор", low):
        topics.append("военные сборы")
    if "мобилизационн" in low and "предписани" in low:
        topics.append("мобилизационные предписания")
    if re.search(r"контрактн\w* служб|служб\w* по контракт|заключени\w* контракт", low):
        topics.append("службу по контракту")
    if "выезд" in low or "выезда" in low:
        topics.append("выезд из России")
    stamp = str(row.get("published_utc") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
        y, m, d = stamp.split("-")
        when = f"{d}.{m}.{y}"
    else:
        when = "дата не установлена"
    if topics:
        subject = ", ".join(topics[:5])
        return (
            f"«Идите лесом», {when}: проект рассказывает об обращениях "
            f"по вопросам: {subject}. "
            "Это сообщения об обращениях, а не статистика призыва "
            "или подтверждение новой волны."
        )
    return (
        f"«Идите лесом», {when}: «{sentence_excerpt(title, 120)}». "
        "Это сообщение проекта; его охват независимо не установлен."
    )


def format_message(draft, evidence, mode):
    """Readable evidence-bound Telegram brief with explicit change/impact logic.

    No auto-publishing, provider inference or invented risk levels. Names of
    sources replace opaque numeric references, and the original four legal
    primary URLs remain attached to the rendered publication.
    """
    by_id = {int(r["id"]): r for r in evidence}
    legal = _plain_language_legal(draft, evidence)
    sections = draft.get("section_sources") or {}
    esc = lambda value: html.escape(clean(value))
    linked = set()

    def link(url, label):
        url = str(url or "")
        if urlsplit(url).scheme not in {"https", "http"}:
            return ""
        linked.add(url)
        return f'<a href="{html.escape(url, quote=True)}">{esc(label)}</a>'

    def first_role(role):
        return next((row for row in evidence if row.get("legal_role") == role), None)

    civil = next((
        row for row in evidence
        if row.get("group") == "civil_society"
        and str(row.get("url") or "").startswith("https://t.me/iditelesom_help/")
    ), None)
    isw = next((row for row in evidence if row.get("group") == "isw"), None)

    local_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=11)))
    when = local_now.strftime("%d.%m.%Y")
    label = "УТРО" if mode == "morning" else "ВЕЧЕР"
    assessment = draft.get("assessment") or {}
    started = norm(assessment.get("started"))
    unconfirmed = (
        not started
        or any(x in started for x in ("не установлен", "не подтвержден", "нет доказательств", "в выборке нет"))
    )

    heading = f"🇷🇺 <b>МОБИЛИЗАЦИЯ РФ · {label} · {when}</b>"
    if unconfirmed:
        main = (
            "В проверенных материалах нет подтверждения нового решения о "
            "массовой мобилизации. Это не означает, что повестки не приходят "
            "или что будущий риск равен нулю."
        )
    else:
        main = sentence_excerpt(assessment.get("started"), 220) or sentence_excerpt(
            draft.get("short"), 220
        )

    def render(*, compact=False, extra_stories=1):
        linked.clear()
        parts = [heading]
        # When no complete legal basis exists, retain the source-provided
        # headline visibly, escaped. Never silently discard source context.
        if legal is None and clean(draft.get("headline")):
            parts.append("<b>" + esc(draft.get("headline")) + "</b>")
        parts += ["<b>Главное</b>", esc(main)]
        if legal is not None:
            parts += [
                "<b>⚠️ Что может стать строже — ПОКА ПРОЕКТ</b>",
                esc(legal["possible"]),
                "<b>Что действует сейчас</b>",
                esc(legal["current"]),
                "<b>Что стало легче?</b>",
                esc(legal["easing"]),
            ]
        else:
            parts += [
                "<b>Право: что известно</b>",
                esc(draft.get("legal")),
                "Текущую стадию документов и последствия без дополнительных "
                "проверенных данных не определяем.",
            ]

        if civil:
            parts += [
                "<b>Повестки: что происходит на практике</b>",
                esc(_practical_note(civil)),
            ]
        else:
            parts += [
                "<b>Повестки: что происходит на практике</b>",
                "Свежих конкретных сообщений проекта «Идите лесом» в доступной "
                "выборке нет. Это пробел наблюдения, а не доказательство отсутствия вызовов.",
            ]

        # One additional distinct non-legal event is allowed only if it adds
        # independent information and fits the user-facing overview.
        extras = []
        for item in draft.get("items") or []:
            ids = [int(i) for i in item.get("source_ids", []) if str(i).isdigit()]
            if not ids:
                continue
            rows = [by_id.get(i, {}) for i in ids]
            if rows and all(r.get("group") == "law" for r in rows):
                continue
            if civil and any(r.get("url") == civil.get("url") for r in rows):
                continue
            if civil and any(r.get("group") == "civil_society" for r in rows):
                continue
            extras.append((item, rows))
        for item, rows in extras[:extra_stories]:
            # A non-legal generic evidence record has no safe replacement
            # synopsis: preserve the actual primary story in full.
            title = (
                clean(item.get("text")) if legal is None
                else sentence_excerpt(item.get("text"), 165 if compact else 230)
            )
            if title:
                parts += ["<b>Ещё одно подтверждённое сообщение</b>", esc(title)]

        near = norm(assessment.get("near_term"))
        near_unknown = not near or "недостаточно данных" in near or "не оцен" in near
        if near_unknown:
            risk = (
                "Недостаточно данных, чтобы оценить вероятность на ближайшие "
                "месяцы: нужны сравнимые сведения о наборе, потерях и вызовах."
            )
        else:
            risk = sentence_excerpt(assessment.get("near_term"), 170)

        parts += [
            "<b>Оценка риска</b>",
            esc("Новая волна: не подтверждена в проверенной выборке."
                if unconfirmed else sentence_excerpt(assessment.get("started"), 140)),
            esc(risk),
        ]
        if isw:
            parts.append(
                "ISW: " + esc(sentence_excerpt(draft.get("isw"), 105)) + " "
                + link(isw.get("url"), "материал ISW")
            )
        else:
            parts.append("ISW: свежей подходящей оценки в выборке нет; это не оценка риска.")

        if not compact:
            parts += [
                "<b>Что важно проверить дальше</b>",
                "Стадию законопроекта, новые юридические решения, "
                "подтверждённые массовые вызовы запасников и кадровую динамику.",
            ]

        # Clearly named source documents, not [1] [2] [10] throughout copy.
        sources = [
            ("first_reading_baseline", "Госдума · законопроект"),
            ("bill_text", "Текст ст. 19.5.5"),
            ("presidential_powers", "31-ФЗ · ст. 4"),
            ("regional_framework", "Указ №757"),
        ]
        links = []
        for role, name in sources:
            row = first_role(role)
            if row:
                links.append(link(row.get("url"), name))
        rationale = first_role("bill_rationale")
        if rationale and not compact:
            links.append(link(rationale.get("url"), "Пояснительная записка"))
        if civil:
            links.append(link(civil.get("url"), "«Идите лесом» · сообщение"))
        else:
            links.append(link("https://t.me/s/iditelesom_help", "«Идите лесом» · канал"))
        if extra_stories and extras:
            for row in extras[0][1][:1]:
                if row and row.get("url"):
                    links.append(link(row.get("url"), "Доп. сообщение"))
        # Preserve links to any omitted non-legal reports; they are short
        # named hyperlinks and do not justify repeating long paragraphs.
        for item in (draft.get("items") or [])[:6]:
            for raw in item.get("source_ids", []):
                if not str(raw).isdigit():
                    continue
                row = by_id.get(int(raw))
                if row and row.get("group") != "law":
                    url = str(row.get("url") or "")
                    if url and url not in linked:
                        links.append(link(url, "Другой материал"))
        parts += ["<b>Проверить первоисточники</b>", " · ".join(v for v in links if v)]

        return "\n\n".join(v for v in parts if v).strip()

    for compact, extra_stories in ((False, 1), (True, 1), (True, 0)):
        message = render(compact=compact, extra_stories=extra_stories)
        if visible_units(message) <= 4000 and len(message) <= 4000:
            return message

    raise ValueError("readable digest cannot fit without losing legal facts or source links")


def install(digest, final, sources, runner):
    """One explicit integration point; idempotent and safe to import in tests."""
    if getattr(final, "_depth_installed", False):
        return
    final._depth_installed = True
    digest.QUERIES = dated_queries(digest.QUERIES)
    old_collect, old_fallback = final.robust_collect, final.safe_fallback_draft
    old_verify, old_validate, old_prompt = digest.verify_draft, digest.validate_draft, digest.draft_prompt
    def collect():
        rows = old_collect()
        snapshots = fetch_legal_snapshots(sources.requests.get, sources.clean)
        rows = merge_evidence(rows, snapshots, digest.MAX_EVIDENCE)
        runner._evidence_cache = rows
        return rows
    def fallback(evidence):
        return enrich_draft(old_fallback(evidence), evidence)
    def verify(draft, evidence):
        return enrich_draft(old_verify(draft, evidence), evidence)
    def validate(draft, evidence):
        return old_validate(draft, evidence) + depth_issues(draft, evidence)
    def prompt(evidence, mode):
        context = old_prompt(evidence, mode)
        return context + "\n\nДополнительные обязательные условия: не считай историческую контрольную дату текущей стадией. " \
            "Документы одного законопроекта — один сюжет. Объясни предмет, адресатов, исключения, санкции, стадию, срок вступления в силу (если подтверждён), цель по пояснительной записке и связь с мобилизацией. " \
            "Для каждого уровня риска добавь assessment_basis: ключ оси, source_ids, evidence_excerpt (точный фрагмент текущего сообщения) и reasoning с причинной связью и альтернативным объяснением. Исторический закон не доказывает оперативную готовность или кадровый дефицит. " \
            "При недостатке данных вместо уровня используй НЕДОСТАТОЧНО ДАННЫХ. Не выводи цель повестки по слову 'запасник'. " \
            "Цитаты только из literal_quote; retrieved_at не является датой принятия акта.\n" + __import__('json').dumps([
                {k: r.get(k) for k in ('id', 'legal_role', 'evidence_kind', 'retrieved_at', 'literal_quote', 'current_stage_verified', 'event_family')}
                for r in evidence
            ], ensure_ascii=False)
    final._civil_society_claim = direct_civil_claim
    final.safe_fallback_draft = fallback
    runner.conservative_draft = fallback
    digest.collect_evidence = collect
    digest.verify_draft = verify
    digest.validate_draft = validate
    digest.draft_prompt = prompt
    digest.format_message = format_message
