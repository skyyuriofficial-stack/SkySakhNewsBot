from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import mobilization_digest as digest
import mobilization_digest_final as final
import telegram_health


_CURRENT_SCHEDULE_MODES = {
    "7,37 0,1,21,22,23 * * *": "morning",
    "7 2,3,4,5,6,7 * * *": "morning",
    "7,37 8,9,10,11 * * *": "evening",
}


def resolved_mode() -> str:
    forced = os.getenv("DIGEST_MODE", "").strip().lower()
    if forced in {"morning", "evening"}:
        return forced

    scheduled = os.getenv("DIGEST_SCHEDULE", "").strip()
    current = _CURRENT_SCHEDULE_MODES.get(scheduled)
    if current:
        return current

    # Keep the canonical implementation as the fallback for manual runs and
    # legacy schedule strings. Current scheduled runs must be classified from
    # github.event.schedule rather than delayed runner wall-clock time.
    return final.resolved_mode()


def _record_blocked(mode: str, health: dict) -> None:
    state = digest.load_state()
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now(digest.TZ)
    state["version"] = "mobilization-digest-v1.4"
    state["last_attempt"] = {
        "status": "error",
        "mode": mode,
        "at_utc": now_utc.isoformat(timespec="seconds"),
        "at_sakhalin": now_local.isoformat(timespec="seconds"),
        "error": "telegram_" + str(health.get("error_kind") or "unhealthy"),
        "description": str(health.get("description") or "")[:500],
    }
    state["telegram_health"] = health
    digest.save_state(state)


def main() -> int:
    mode = resolved_mode()

    # Force the already-resolved slot into the downstream module. This avoids
    # reclassifying a delayed scheduled run from the runner's current clock.
    previous_mode = os.environ.get("DIGEST_MODE")
    os.environ["DIGEST_MODE"] = mode
    try:
        if os.getenv("DIGEST_DRY_RUN", "0") == "1":
            return int(final.main() or 0)
        health = telegram_health.check_telegram()
        telegram_health.write_status(health)
        if health.get("status") != "healthy":
            _record_blocked(mode, health)
            print(json.dumps({
                "status": "blocked_before_collection",
                "mode": mode,
                "telegram_health": health,
            }, ensure_ascii=False, indent=2))
            return 23
        return int(final.main() or 0)
    finally:
        if previous_mode is None:
            os.environ.pop("DIGEST_MODE", None)
        else:
            os.environ["DIGEST_MODE"] = previous_mode


if __name__ == "__main__":
    raise SystemExit(main())
