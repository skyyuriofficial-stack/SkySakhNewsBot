from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Sequence

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
    r"подписывайтесь на.*(?:telegram|телеграм|max)",
    r"читайте также",
    r"подробнее на сайте",
)

CONTACT_OR_TECH_PATTERNS = (
    r"https?://",
    r"www\.",
    r"@[a-z0-9_]{4,}",
    r"\+7\s*\(?\d{3}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}",
)

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


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-я0-9]+", _norm(value), flags=re.I)
        if len(token) >= 4 and token not in GENERIC_EVENT_WORDS and not token.isdigit()
    }


def text_similarity(a: Any, b: Any) -> float:
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def duplicate_event(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    if str(a.get("url") or "") and str(a.get("url") or "") == str(b.get("url") or ""):
        return True

    cluster_a = str(a.get("topic_cluster") or "").strip()
    cluster_b = str(b.get("topic_cluster") or "").strip()
    if cluster_a and cluster_b and cluster_a == cluster_b:
        return True

    if str(a.get("category_key") or "") != str(b.get("category_key") or ""):
        return False

    title_similarity = text_similarity(a.get("title"), b.get("title"))
    source_similarity = text_similarity(
        str(a.get("title") or "") + " " + str(a.get("source_text") or "")[:1000],
        str(b.get("title") or "") + " " + str(b.get("source_text") or "")[:1000],
    )
    overlap = _tokens(a.get("title")) & _tokens(b.get("title"))
    return bool(
        (title_similarity >= 0.58 and len(overlap) >= 3)
        or (source_similarity >= 0.62 and len(overlap) >= 2)
    )


def _paragraph_duplicate(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) >= 80 and (na in nb or nb in na):
        return True
    return text_similarity(a, b) >= 0.82


def content_quality_issues(candidate: Mapping[str, Any], row: Mapping[str, Any]) -> List[str]:
    title = policy.clean(row.get("title_ru") or candidate.get("title"))
    source_text = policy.clean(candidate.get("source_text"))
    body = row.get("body") if isinstance(row.get("body"), list) else []
    paragraphs = [policy.clean(value) for value in body if policy.clean(value)]
    issues: List[str] = []

    if len(paragraphs) < 2:
        issues.append("body_too_short")

    for paragraph in paragraphs:
        low = paragraph.lower()
        if any(re.search(pattern, low, flags=re.I | re.S) for pattern in BOILERPLATE_PATTERNS):
            issues.append("body_contains_publisher_boilerplate")
            break
        if any(re.search(pattern, paragraph, flags=re.I) for pattern in CONTACT_OR_TECH_PATTERNS):
            issues.append("body_contains_contact_or_url")
            break
        if re.search(
            r"(?<=[а-яё0-9])\s+(?=(?:По|Как|При|Предварительно|В|На|Для)\s+[А-ЯЁа-яё])",
            paragraph,
        ):
            issues.append("body_missing_sentence_boundary")
            break

    for index, paragraph in enumerate(paragraphs):
        for previous in paragraphs[:index]:
            if _paragraph_duplicate(previous, paragraph):
                issues.append("repetitive_body_paragraph")
                break
        if "repetitive_body_paragraph" in issues:
            break

    source_sentences = [
        policy.clean(value)
        for value in re.split(r"(?<=[.!?])\s+", source_text)
        if len(policy.clean(value)) >= 50
    ]
    if len(source_sentences) >= 2 and _paragraph_duplicate(source_sentences[0], source_sentences[1]):
        issues.append("source_lead_duplicated")

    if re.search(r"\bсахалин(?:ец|ца|цу|цем|цы|цев|цам|цами|цах|ка|ку|ке|кой|ки)\b", title.lower()):
        if re.search(r"личност[ьи].{0,45}не\s+установ", source_text.lower()):
            issues.append("unsupported_sakhalin_resident_identity")

    return list(dict.fromkeys(issues))


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
        contract["hardening_version"] = "editorial-hardening-v1"
        return contract

    policy.classify = hardened_classify
    policy.final_contract = hardened_final_contract
    policy.patch_gate_matching()
    _INSTALLED = True


__all__ = [
    "install",
    "content_quality_issues",
    "duplicate_event",
    "text_similarity",
]
