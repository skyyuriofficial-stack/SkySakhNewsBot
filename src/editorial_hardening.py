from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Set

import editorial_policy as policy

EXTRA_LOCAL_MARKERS = (
    "синегорск",
)

EXTRA_FOREIGN_MARKERS = (
    "непал",
    "катманду",
)

BOILERPLATE_PATTERNS = (
    r"ни одна часть содержания сайта\s+astv\.ru",
    r"мы будем присылать вам на почту самые просматриваемые новости",
    r"при полном или частичном использовании материалов.*astv",
    r"копирование материалов.*astv",
    r"(?:подпиш(?:ись|итесь)|подписывайтесь)\s+на.*(?:telegram|телеграм|max|новост)",
    r"читайте также",
    r"подробнее на сайте",
)

CONTACT_OR_TECH_PATTERNS = (
    r"https?://",
    r"www\.",
    r"@[a-z0-9_]{4,}",
    r"\+7\s*\(?\d{3}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}",
)

MISSING_BOUNDARY_RE = re.compile(
    r"(?<=[а-яё0-9])\s+(?=(?:По|Как|При|Предварительно|В|На|Для|Преступление|Огнеборцы)\s+[А-ЯЁа-яё])"
)

SOURCE_HEADING_PREFIX_RE = re.compile(
    r"^ГАИ\s+ищет\s+очевидцев\s+(?=Госавтоинспекция\b)",
    flags=re.I,
)

TRUNCATED_INITIAL_RE = re.compile(r"\b[А-ЯЁ]\.$")

GENERIC_EVENT_WORDS = {
    "после", "перед", "в", "на", "по", "для", "из", "при", "дом", "дома",
    "южно", "сахалинск", "сахалинске", "сахалин", "области", "районе", "улице",
    "сегодня", "сентября", "года", "прокуратура", "сообщили", "рассказали",
}

_INSTALLED = False
_ORIGINAL_CLASSIFY = None
_ORIGINAL_FINAL_CONTRACT = None


def _norm(value: Any) -> str:
    return policy.norm(value)


def _stem_token(token: str) -> str:
    value = str(token or "").lower().replace("ё", "е")
    if len(value) <= 6:
        return value
    return value[:6]


def _tokens(value: Any) -> Set[str]:
    result: Set[str] = set()
    for token in re.findall(r"[a-zа-я0-9]+", _norm(value), flags=re.I):
        if len(token) < 4 or token in GENERIC_EVENT_WORDS or token.isdigit():
            continue
        result.add(_stem_token(token))
    return result


def _incident_anchors(value: Any) -> Set[str]:
    """Extract strong event facts that are safe to use only as duplicate corroboration."""
    text = _norm(value)
    anchors: Set[str] = set()
    for age in re.findall(r"\b(\d{1,3})[-\s]?(?:летн\w*|лет)\b", text, flags=re.I):
        anchors.add(f"age:{age}")
    for street in re.findall(r"\b(?:улиц\w*|ул\.?)\s+([а-яё-]{4,})", text, flags=re.I):
        anchors.add(f"street:{_stem_token(street)}")
    return anchors


def _sentence_parts(value: Any) -> List[str]:
    """Split source prose without mistaking a personal/street initial for sentence end."""
    text = MISSING_BOUNDARY_RE.sub(". ", policy.clean(value))
    if not text:
        return []
    protected = re.sub(
        r"\b([А-ЯЁ])\.\s+(?=[А-ЯЁ][а-яё-]{2,}\b)",
        r"\1<INIT> ",
        text,
    )
    parts = [
        policy.clean(part.replace("<INIT>", "."))
        for part in re.split(r"(?<=[.!?])\s+", protected)
        if policy.clean(part)
    ]
    return parts


def _expand_truncated_from_source(paragraph: str, source_text: str) -> str:
    if not TRUNCATED_INITIAL_RE.search(paragraph):
        return paragraph
    normalized = policy.clean(paragraph)
    for sentence in _sentence_parts(source_text):
        if sentence.startswith(normalized) and len(sentence) > len(normalized) + 3:
            return sentence
    return paragraph


def _expand_unbalanced_quote_from_source(paragraph: str, source_text: str) -> str:
    """Complete a straight-quoted source fragment only when the source contains its closing quote."""
    normalized = policy.clean(paragraph)
    source = policy.clean(source_text)
    if not normalized or normalized.count('"') % 2 == 0 or not source:
        return paragraph
    start = source.find(normalized)
    if start < 0:
        return paragraph
    remainder = source[start + len(normalized):]
    closing = remainder.find('"')
    if closing < 0:
        return paragraph
    end = start + len(normalized) + closing + 1
    expanded = source[start:end]
    suffix = source[end:]
    attribution = re.match(r"\s*,?\s*[-—]\s*[^.!?]{1,120}[.!?]", suffix)
    if attribution:
        expanded += attribution.group(0)
    expanded = re.sub(r'"\s+([А-ЯЁ])', r'"\1', expanded)
    return policy.clean(expanded)


def text_similarity(a: Any, b: Any) -> float:
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def duplicate_event(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    url_a = str(a.get("url") or "")
    url_b = str(b.get("url") or "")
    if url_a and url_a == url_b:
        return True

    cluster_a = str(a.get("topic_cluster") or "").strip()
    cluster_b = str(b.get("topic_cluster") or "").strip()
    if cluster_a and cluster_b and cluster_a == cluster_b:
        return True

    if str(a.get("category_key") or "") != str(b.get("category_key") or ""):
        return False

    title_a = _tokens(a.get("title"))
    title_b = _tokens(b.get("title"))
    title_overlap = title_a & title_b
    title_similarity = text_similarity(a.get("title"), b.get("title"))
    combined_a = str(a.get("title") or "") + " " + str(a.get("source_text") or "")[:1000]
    combined_b = str(b.get("title") or "") + " " + str(b.get("source_text") or "")[:1000]
    source_similarity = text_similarity(combined_a, combined_b)
    shared_incident_anchors = _incident_anchors(combined_a) & _incident_anchors(combined_b)

    if len(title_overlap) >= 3 and title_similarity >= 0.38:
        return True
    if len(title_overlap) >= 2 and source_similarity >= 0.50:
        return True
    # Cross-source rewrites can have modest lexical similarity while still describing
    # the exact same incident. Require two independent hard facts (for example the
    # same victim age and street) before using a lower lexical threshold.
    if len(shared_incident_anchors) >= 2 and len(title_overlap) >= 2 and source_similarity >= 0.35:
        return True
    return bool(title_similarity >= 0.58 or source_similarity >= 0.68)


def _paragraph_duplicate(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) >= 80 and (na in nb or nb in na):
        return True
    return text_similarity(a, b) >= 0.82


def _unsafe_paragraph(paragraph: str) -> bool:
    low = paragraph.lower()
    return bool(
        any(re.search(pattern, low, flags=re.I | re.S) for pattern in BOILERPLATE_PATTERNS)
        or any(re.search(pattern, paragraph, flags=re.I) for pattern in CONTACT_OR_TECH_PATTERNS)
    )


def dedupe_source_text(value: Any) -> str:
    """Remove scraper-level repeated source sentences before generation/audit."""
    parts = _sentence_parts(value)
    if not parts:
        return ""
    if len(parts) < 2:
        return parts[0]
    kept: List[str] = []
    for part in parts:
        if _unsafe_paragraph(part):
            continue
        if any(_paragraph_duplicate(existing, part) for existing in kept):
            continue
        kept.append(part)
    return " ".join(kept)


def source_quality_warnings(candidate: Mapping[str, Any]) -> List[str]:
    source_text = policy.clean(candidate.get("source_text"))
    if not source_text:
        return []
    cleaned = dedupe_source_text(source_text)
    normalized_original = " ".join(_sentence_parts(source_text))
    warnings: List[str] = []
    if cleaned != normalized_original:
        warnings.append("source_text_sanitized")
    return warnings


def _unsupported_identity(title: str, source_text: str) -> bool:
    return bool(
        re.search(r"\bсахалин(?:ец|ца|цу|цем|цы|цев|цам|цами|цах|ка|ку|ке|кой|ки)\b", title.lower())
        and re.search(r"личност[ьи].{0,45}не\s+установ", source_text.lower())
    )


def content_quality_issues(candidate: Mapping[str, Any], row: Mapping[str, Any]) -> List[str]:
    """Blocking output-quality issues only."""
    title = policy.clean(row.get("title_ru") or candidate.get("title"))
    source_text = policy.clean(candidate.get("source_text"))
    body = row.get("body") if isinstance(row.get("body"), list) else []
    paragraphs = [policy.clean(value) for value in body if policy.clean(value)]
    issues: List[str] = []

    if len(paragraphs) < 2:
        issues.append("body_too_short")

    for paragraph in paragraphs:
        if any(re.search(pattern, paragraph.lower(), flags=re.I | re.S) for pattern in BOILERPLATE_PATTERNS):
            issues.append("body_contains_publisher_boilerplate")
            break
        if any(re.search(pattern, paragraph, flags=re.I) for pattern in CONTACT_OR_TECH_PATTERNS):
            issues.append("body_contains_contact_or_url")
            break
        if MISSING_BOUNDARY_RE.search(paragraph):
            issues.append("body_missing_sentence_boundary")
            break
        if SOURCE_HEADING_PREFIX_RE.search(paragraph):
            issues.append("body_contains_source_heading_prefix")
            break
        if TRUNCATED_INITIAL_RE.search(paragraph) and _expand_truncated_from_source(paragraph, source_text) != paragraph:
            issues.append("body_truncated_at_name_initial")
            break
        if paragraph.count('"') % 2 == 1 and _expand_unbalanced_quote_from_source(paragraph, source_text) != paragraph:
            issues.append("body_truncated_inside_quote")
            break

    for index, paragraph in enumerate(paragraphs):
        for previous in paragraphs[:index]:
            if _paragraph_duplicate(previous, paragraph):
                issues.append("repetitive_body_paragraph")
                break
        if "repetitive_body_paragraph" in issues:
            break

    if _unsupported_identity(title, source_text):
        issues.append("unsupported_sakhalin_resident_identity")

    return list(dict.fromkeys(issues))


def repair_row(candidate: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
    """Deterministically repair safe-to-fix caption defects without inventing facts."""
    repaired = deepcopy(dict(row))
    source_text = policy.clean(candidate.get("source_text"))
    title = policy.clean(repaired.get("title_ru") or candidate.get("title"))

    if _unsupported_identity(title, source_text):
        replacement = "Пешехода" if re.search(r"\bпешеход", source_text.lower()) else "Человека"
        title = re.sub(
            r"\bСахалин(?:ец|ца|цу|цем|цы|цев|цам|цами|цах|ка|ку|ке|кой|ки)\b",
            replacement,
            title,
            count=1,
            flags=re.I,
        )
        repaired["title_ru"] = title

    body = repaired.get("body") if isinstance(repaired.get("body"), list) else []
    cleaned: List[str] = []
    for raw in body:
        paragraph = policy.clean(raw)
        if not paragraph or _unsafe_paragraph(paragraph):
            continue
        paragraph = MISSING_BOUNDARY_RE.sub(". ", paragraph)
        paragraph = SOURCE_HEADING_PREFIX_RE.sub("", paragraph).strip()
        paragraph = _expand_truncated_from_source(paragraph, source_text)
        paragraph = _expand_unbalanced_quote_from_source(paragraph, source_text)
        if any(_paragraph_duplicate(existing, paragraph) for existing in cleaned):
            continue
        cleaned.append(paragraph)

    # If publisher boilerplate was removed and fewer than two useful paragraphs
    # remain, rebuild only from unique sentences already present in the source.
    if len(cleaned) < 2:
        source_clean = dedupe_source_text(source_text)
        source_sentences = [
            policy.clean(part)
            for part in _sentence_parts(source_clean)
            if len(policy.clean(part)) >= 45 and not _unsafe_paragraph(policy.clean(part))
        ]
        for sentence in source_sentences:
            sentence = SOURCE_HEADING_PREFIX_RE.sub("", sentence).strip()
            if any(_paragraph_duplicate(existing, sentence) for existing in cleaned):
                continue
            cleaned.append(sentence)
            if len(cleaned) >= 2:
                break

    repaired["body"] = cleaned
    repaired["hardening_repair"] = {
        "version": "editorial-hardening-v1.5",
        "source_warnings": source_quality_warnings(candidate),
    }
    return repaired


def _reclassified(base: policy.Classification, category_key: str, group: str, *, local: bool | None = None) -> policy.Classification:
    features = set(base.features)
    features.add("hardening_reclassification")
    evidence = deepcopy(base.evidence)
    evidence["hardening_from"] = base.category_key
    return policy.Classification(
        category_key=category_key,
        group=group,
        event_type=base.event_type,
        hard_reject_reason=None,
        local=base.local if local is None else local,
        foreign=base.foreign,
        russia=base.russia,
        source_world=base.source_world,
        source_local=base.source_local,
        source_russian=base.source_russian,
        features=features,
        evidence=evidence,
    )


def install() -> None:
    global _INSTALLED, _ORIGINAL_CLASSIFY, _ORIGINAL_FINAL_CONTRACT
    if _INSTALLED:
        return

    policy.LOCAL_MARKERS = tuple(dict.fromkeys(policy.LOCAL_MARKERS + EXTRA_LOCAL_MARKERS))
    policy.FOREIGN_MARKERS = tuple(dict.fromkeys(policy.FOREIGN_MARKERS + EXTRA_FOREIGN_MARKERS))
    policy.patch_gate_matching()

    _ORIGINAL_CLASSIFY = policy.classify
    _ORIGINAL_FINAL_CONTRACT = policy.final_contract

    def hardened_classify(candidate: Mapping[str, Any]) -> policy.Classification:
        base = _ORIGINAL_CLASSIFY(candidate)
        title = policy.strip_source_suffix(candidate.get("title"))
        lead = policy.clean_article_text(candidate.get("source_text"), limit=1800)
        combined = f"{title} {lead}"

        extra_local = policy.has_any(combined, EXTRA_LOCAL_MARKERS)
        if extra_local and not base.local:
            if base.event_type == "earthquake":
                return _reclassified(base, "sakh_quake", "local", local=True)
            if base.event_type in {
                "violent_crime", "fatal_incident", "military_security", "major_emergency",
                "missing_person", "fraud", "routine_crime", "air_quality_hazard",
            }:
                return _reclassified(base, "sakh_chp", "local", local=True)
            return _reclassified(base, "sakh", "local", local=True)

        foreign_without_russia = bool(
            policy.has_any(combined, policy.FOREIGN_MARKERS)
            and not policy.has_any(combined, policy.RUSSIA_MARKERS)
            and not policy.has_any(combined, policy.LOCAL_MARKERS)
        )
        if base.category_key in {"ru_incident", "ru_security", "ru_pol", "ru_eco"} and foreign_without_russia:
            if base.event_type in {
                "major_emergency", "fatal_incident", "military_security", "geopolitical_event",
                "political_decision", "violent_crime",
            }:
                return _reclassified(base, "geo", "world", local=False)
            return policy.Classification(
                category_key=None,
                group=None,
                event_type=base.event_type,
                hard_reject_reason="foreign_story_in_russia_stream",
                local=False,
                foreign=True,
                russia=False,
                source_world=base.source_world,
                source_local=base.source_local,
                source_russian=base.source_russian,
                features=set(base.features) | {"hardening_foreign_guard"},
                evidence={**deepcopy(base.evidence), "hardening_from": base.category_key},
            )
        return base

    def hardened_final_contract(candidate: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
        contract = dict(_ORIGINAL_FINAL_CONTRACT(candidate, row))
        issues = list(contract.get("issues") or [])
        issues.extend(content_quality_issues(candidate, row))
        contract["issues"] = list(dict.fromkeys(str(issue) for issue in issues if issue))
        contract["approved"] = not contract["issues"]
        contract["hardening_version"] = "editorial-hardening-v1.5"
        contract["source_warnings"] = source_quality_warnings(candidate)
        return contract

    policy.classify = hardened_classify
    policy.final_contract = hardened_final_contract
    policy.patch_gate_matching()
    _INSTALLED = True


__all__ = [
    "install",
    "content_quality_issues",
    "dedupe_source_text",
    "duplicate_event",
    "repair_row",
    "source_quality_warnings",
    "text_similarity",
]
