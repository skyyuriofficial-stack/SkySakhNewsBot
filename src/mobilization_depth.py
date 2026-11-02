"""Source-bound depth checks for the scheduled mobilisation digest.

No Telegram writes, current-event assumptions, or network calls at import time.
Historical legal references remain historical; quotations require fetched text.
"""
from __future__ import annotations

import copy
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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


def format_message(draft, evidence, mode):
    """Fit by dropping repetitive presentation, never by cutting legal clauses.

    The complete evidence/draft remains available in the digest state. The
    single Telegram overview keeps at least the first non-legal story, every
    legal clause, and links to any omitted secondary stories.
    """
    by_id = {int(r["id"]): r for r in evidence}
    def refs(values):
        links, seen = [], set()
        for value in values:
            try:
                idx = int(value)
            except (ValueError, TypeError):
                continue
            row = by_id.get(idx)
            url = str((row or {}).get("url") or "")
            if url in seen or urlsplit(url).scheme not in {"https", "http"}:
                continue
            seen.add(url)
            links.append(f'<a href="{html.escape(url, quote=True)}">[{idx}]</a>')
        return " ".join(links)
    esc = lambda v: html.escape(clean(v))
    sections = draft.get("section_sources") or {}
    label = "УТРЕННЯЯ" if mode == "morning" else "ВЕЧЕРНЯЯ"
    stories = []
    for item in (draft.get("items") or [])[:6]:
        item_ids = [int(i) for i in item.get("source_ids", []) if str(i).isdigit()]
        if item_ids and all(by_id.get(i, {}).get("group") == "law" for i in item_ids):
            continue
        stories.append((item, item_ids))
    labels = {"started": "Запуск", "near_term": "Ближайшие месяцы", "staffing": "Кадры", "infrastructure": "Готовность", "large_wave_decision": "Крупная волна"}

    def render(story_count, compact):
        parts = [f"🇷🇺 <b>МОБИЛИЗАЦИЯ РФ — {label} СВОДКА</b>", f"<b>{esc(draft.get('headline'))}</b>"]
        if not compact:
            parts.append(esc(draft.get("short")))
        for item, item_ids in stories[:story_count]:
            # Keep the full attributed summary, including its limitations.
            parts.append(esc(item.get("text")) + " " + refs(item_ids))
        rest = [idx for _, item_ids in stories[story_count:] for idx in item_ids]
        if rest:
            parts.append("Другие сообщения в выборке: " + refs(rest))
        parts += ["<b>Право: содержание и последствия</b>", esc(draft.get("legal")) + " " + refs(sections.get("legal", []))]
        for quote in (draft.get("legal_quotes") or [])[:2]:
            parts.append("Фрагмент нормы: «" + esc(quote.get("text")) + "» " + refs([quote.get("source_id")]))
        if compact and sections.get("practice"):
            practice = "«Идите лесом»: сообщения проекта, не независимое подтверждение массовости. Учёт, сборы, контракт и мобилизация различаются."
        else:
            practice = clean(draft.get("practice"))
        parts += ["<b>Практика и покрытие источников</b>", esc(practice) + " " + refs([i for _, values in stories[:story_count] for i in values if by_id.get(i, {}).get("group") == "civil_society"] or sections.get("practice", [])[:2])]
        if sections.get("isw"):
            parts.append(esc(sentence_excerpt(draft.get("isw"), 300)) + " " + refs(sections["isw"][:2]))
        else:
            parts.append("Свежих данных ISW в выборке нет; это пробел покрытия, а не оценка риска.")
        parts.append("<b>Раздельная оценка</b>")
        for axis, axis_label in labels.items():
            parts.append(f"<b>{axis_label}:</b> {esc((draft.get('assessment') or {}).get(axis))}")
        return "\n\n".join(p for p in parts if p).strip()

    candidates = [(min(3, len(stories)), False), (min(2, len(stories)), True), (min(1, len(stories)), True)]
    for count, compact in candidates:
        message = render(count, compact)
        if visible_units(message) <= 4000:
            return message
    raise ValueError("digest cannot fit without losing a legal clause or primary attributed story")


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
