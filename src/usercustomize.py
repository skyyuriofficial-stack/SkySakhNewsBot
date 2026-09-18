"""Runtime environment policy loaded automatically by Python's site module.

The v12 news director and Russian-language publication path are deterministic.
OpenRouter is enabled only as a small, optional budget for translating foreign
articles during an actual Telegram run. Its failure cannot affect selection or
Russian posts.
"""

from __future__ import annotations

import os


if os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
    # The workflow deliberately sets AI_CALL_BUDGET=0 as a safe baseline. A
    # live publisher receives two optional translation attempts, which is
    # enough for the 10% world + 5% technology quotas without making the whole
    # release dependent on the free external service.
    if os.getenv("AI_CALL_BUDGET", "0").strip() in {"", "0"}:
        os.environ["AI_CALL_BUDGET"] = "2"

    os.environ.setdefault("EDITORIAL_AUDIT_AI_BUDGET", "0")
    os.environ.setdefault("NEWS_DIRECTOR_AI_BUDGET", "0")
    os.environ.setdefault("OPENROUTER_MAX_ATTEMPTS", "3")
    os.environ.setdefault("OPENROUTER_RETRY_BASE_SECONDS", "1.0")


# Russian animal-identification verbs such as "чипировали" are not evidence
# of a semiconductor/IT event. The editorial ontology intentionally uses
# prefix matching for most stems, so constrain only the ambiguous noun "чип"
# to real Russian noun forms while preserving ordinary semiconductor stories.
import editorial_policy as _editorial_policy

_CHIP_NOUN_FORMS = {
    "чип", "чипа", "чипу", "чипом", "чипе",
    "чипы", "чипов", "чипам", "чипами", "чипах",
}
_editorial_policy.IT_CORE = tuple(
    marker for marker in _editorial_policy.IT_CORE if marker != "чип"
) + tuple(sorted(_CHIP_NOUN_FORMS))
_editorial_policy.EXACT_SINGLE_MARKERS.update(_CHIP_NOUN_FORMS)
_editorial_policy.patch_gate_matching()
