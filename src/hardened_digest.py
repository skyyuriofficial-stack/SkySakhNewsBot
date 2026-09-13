from __future__ import annotations

import json
from datetime import datetime, timezone

import mobilization_digest as digest
import mobilization_digest_final as final
import telegram_health


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
    mode = final.resolved_mode()
    if __import__("os").getenv("DIGEST_DRY_RUN", "0") == "1":
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


if __name__ == "__main__":
    raise SystemExit(main())
