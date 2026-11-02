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


def resolved_mode(*, now_local: datetime | None = None) -> str:
    forced = os.getenv("DIGEST_MODE", "").strip().lower()
    if forced in {"morning", "evening"}:
        return forced

    scheduled = os.getenv("DIGEST_SCHEDULE", "").strip()
    current = _CURRENT_SCHEDULE_MODES.get(scheduled)
    if current:
        local_now = now_local or datetime.now(digest.TZ)
        # A delayed morning trigger must not replace the evening update.
        if current == "morning" and local_now.hour >= 19:
            return "evening"
        return current
    return final.resolved_mode()


def _record_blocked(mode: str, health: dict) -> None:
    state = digest.load_state()
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now(digest.TZ)
    state["version"] = "mobilization-digest-v1.4"
    state["last_attempt"] = {
        "status": "blocked",
        "mode": mode,
        "at_utc": now_utc.isoformat(timespec="seconds"),
        "at_sakhalin": now_local.isoformat(timespec="seconds"),
        "error": "telegram_" + str(health.get("error_kind") or "unhealthy"),
        "description": str(health.get("description") or "")[:500],
    }
    state["telegram_health"] = health
    digest.save_state(state)


def main() -> int:
    # Install once at execution, not at import: read-only tools and other
    # production entrypoints retain their own independent behaviour.
    import mobilization_depth
    import mobilization_sources
    import mobilization_digest_runner
    mobilization_depth.install(digest, final, mobilization_sources, mobilization_digest_runner)
    mode = resolved_mode()
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
            return 0
        return int(final.main() or 0)
    finally:
        if previous_mode is None:
            os.environ.pop("DIGEST_MODE", None)
        else:
            os.environ["DIGEST_MODE"] = previous_mode


if __name__ == "__main__":
    raise SystemExit(main())
