from __future__ import annotations

import re

_INSTALLED = False


def install() -> None:
    """Install narrow source-cleanup rules required by live production.

    This module is imported explicitly from the shared Telegram health layer so
    the rules are present in both hardened publisher and monitor processes. The
    transformations only remove known ASTV presentation text; they do not add or
    infer article facts.
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
    extra_boilerplate = tuple(
        pattern
        for pattern in (astv_boilerplate, astv_registration)
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

    _INSTALLED = True
