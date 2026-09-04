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
