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


# A bare Russian word "цунами" is also used as a proper name (for example the
# South Sakhalin skate park "Цунами"). Treating that token alone as seismic
# evidence can promote routine local stories to sakh_quake with an earthquake
# score. Keep real tsunami headlines detectable only through explicit hazard
# context and refresh the legacy gate markers that mirror editorial_policy.
try:
    import editorial_policy as _editorial_policy

    _editorial_policy.QUAKE = tuple(
        marker for marker in _editorial_policy.QUAKE if marker != "цунами"
    ) + (
        "угроза цунами",
        "предупреждение о цунами",
        "опасность цунами",
        "волна цунами",
        "цунами после землетрясения",
    )
    _editorial_policy.patch_gate_matching()
except Exception:
    # usercustomize must never prevent Python startup; the normal policy remains
    # available if this optional runtime hardening cannot be installed.
    pass
