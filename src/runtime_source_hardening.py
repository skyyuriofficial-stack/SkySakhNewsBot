from __future__ import annotations

import re

_INSTALLED = False


def install() -> None:
    """Install narrow source-cleanup rules required by live production.

    This module is imported explicitly from the shared Telegram health layer so
    the rules are present in both hardened publisher and monitor processes. The
    transformations only remove known publisher presentation text or complete
    source-verifiable quotations; they do not add or infer article facts.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    import editorial_hardening as hardening

    astv_boilerplate = r"на\s+сайте\s+astv\.ru\s+размещаются\s+текстовые\s+материалы"
    astv_registration = (
        r"иа\s+[\"«]?аств[\"»]?\s+зарегистрировано\s+федеральной\s+службой\s+"
        r"по\s+надзору\s+в\s+сфере\s+связи"
    )
    # ASTV registration boilerplate can be truncated by the source parser so
    # only the certificate-number tail is appended to an otherwise valid news
    # sentence (for example: "... водовода. за номером ИА № ФС 77 - 73225.").
    # Treat that tail as presentation metadata, not article content.
    astv_registration_number = (
        r"за\s+номером\s+(?:иа\s+)?№?\s*фс\s*77\s*[-–—]?\s*\d{4,}"
    )
    # Sakh.online often prefixes article text with a generic SEO/navigation
    # sentence. It is presentation text and must never become a rebuilt body
    # paragraph during queue hardening.
    sakh_online_teaser = (
        r"читайте\s+последние\s+актуальные\s+новости\s+главных\s+событий\s+сахалина"
        r".*?в\s+ленте\s+новостей\s+на\s+сайте\s+sakh\.online"
    )
    extra_boilerplate = tuple(
        pattern
        for pattern in (
            astv_boilerplate,
            astv_registration,
            astv_registration_number,
            sakh_online_teaser,
        )
        if pattern not in hardening.BOILERPLATE_PATTERNS
    )
    if extra_boilerplate:
        hardening.BOILERPLATE_PATTERNS = (
            *hardening.BOILERPLATE_PATTERNS,
            *extra_boilerplate,
        )

    source_heading = hardening.SOURCE_HEADING_PREFIX_RE
    astv_power_heading = (
        r"^Энергетики\s+запланировали\s+работы\s+на\s+сетях\s+и\s+подстанциях\s+"
        r"(?=Специалисты\b)"
    )
    if astv_power_heading not in source_heading.pattern:
        hardening.SOURCE_HEADING_PREFIX_RE = re.compile(
            rf"(?:{source_heading.pattern})|(?:{astv_power_heading})",
            flags=source_heading.flags,
        )

    # The canonical hardening layer historically completed only straight-quoted
    # fragments. Russian sources commonly use guillemets, so an extractive row
    # could retain an opening « while truncating the quote before its closing ».
    # Complete such a fragment only when the exact continuation and closing quote
    # are present in source_text; otherwise leave it untouched so validation can
    # fail closed.
    original_expand_quote = hardening._expand_unbalanced_quote_from_source

    def expand_unbalanced_quote_from_source(paragraph: str, source_text: str) -> str:
        expanded = original_expand_quote(paragraph, source_text)
        if expanded != paragraph:
            return expanded

        normalized = hardening.policy.clean(paragraph)
        source = hardening.policy.clean(source_text)
        if not normalized or not source:
            return paragraph
        if normalized.count("«") <= normalized.count("»"):
            return paragraph

        start = source.find(normalized)
        if start < 0:
            return paragraph
        remainder = source[start + len(normalized):]
        closing = remainder.find("»")
        if closing < 0:
            return paragraph

        end = start + len(normalized) + closing + 1
        value = source[start:end]
        suffix = source[end:]
        attribution = re.match(r"\s*,?\s*[-—]\s*[^.!?]{1,120}[.!?]", suffix)
        if attribution:
            value += attribution.group(0)
        return hardening.policy.clean(value)

    original_content_quality_issues = hardening.content_quality_issues

    def content_quality_issues(candidate, row):
        issues = list(original_content_quality_issues(candidate, row))
        source_text = hardening.policy.clean(candidate.get("source_text"))
        body = row.get("body") if isinstance(row.get("body"), list) else []
        for raw in body:
            paragraph = hardening.policy.clean(raw)
            if not paragraph or paragraph.count("«") == paragraph.count("»"):
                continue
            repaired = expand_unbalanced_quote_from_source(paragraph, source_text)
            if repaired != paragraph:
                issues.append("body_truncated_inside_quote")
            else:
                issues.append("body_unbalanced_quote")
            break
        return list(dict.fromkeys(str(issue) for issue in issues if issue))

    hardening._expand_unbalanced_quote_from_source = expand_unbalanced_quote_from_source
    hardening.content_quality_issues = content_quality_issues

    _INSTALLED = True
