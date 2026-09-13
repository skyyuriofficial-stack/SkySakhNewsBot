from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
TZ = timezone(timedelta(hours=11))
PRODUCTION_HOURS = (7, 10, 13, 16, 19, 22)
BLOCKED_RETRY_COOLDOWN_MINUTES = 15


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    except Exception:
        return None


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def production_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    if (
        os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.getenv("FORCE_PRODUCTION", "0") == "1"
    ):
        return {"due": True, "slot": "manual", "reason": "forced_workflow_dispatch"}

    target_hour = max((hour for hour in PRODUCTION_HOURS if hour <= now.hour), default=None)
    if target_hour is None:
        return {"due": False, "slot": "none", "reason": "before_first_daily_slot"}

    target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    slot = target.strftime("%Y-%m-%dT%H:%M%z")
    state = _load_state()
    last_run = state.get("last_run") or {}
    finished = _parse(last_run.get("finished_sakhalin"))
    if finished and finished.astimezone(TZ) >= target:
        return {
            "due": False,
            "slot": slot,
            "reason": "slot_already_processed",
            "finished_sakhalin": finished.astimezone(TZ).isoformat(timespec="seconds"),
        }

    attempt = state.get("last_production_attempt") or {}
    attempted_at = _parse(attempt.get("checked_at_utc"))
    if (
        attempt.get("status") == "blocked"
        and attempted_at
        and attempted_at.astimezone(TZ) >= target
    ):
        age = now - attempted_at.astimezone(TZ)
        if age.total_seconds() < BLOCKED_RETRY_COOLDOWN_MINUTES * 60:
            return {
                "due": False,
                "slot": slot,
                "reason": "blocked_attempt_cooldown",
                "retry_after_minutes": round((BLOCKED_RETRY_COOLDOWN_MINUTES * 60 - age.total_seconds()) / 60, 1),
            }

    return {"due": True, "slot": slot, "reason": "slot_missing_or_failed"}


def _write_output(result: Dict[str, Any]) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("due=" + ("true" if result.get("due") else "false") + "\n")
        handle.write("slot=" + str(result.get("slot") or "") + "\n")
        handle.write("reason=" + str(result.get("reason") or "") + "\n")


def main() -> int:
    mode = (os.sys.argv[1] if len(os.sys.argv) > 1 else "production").strip().lower()
    if mode != "production":
        raise SystemExit(f"unsupported guard mode: {mode}")
    result = production_due()
    _write_output(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
