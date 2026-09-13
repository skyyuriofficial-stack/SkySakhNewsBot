from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_PATH = ROOT / "telegram_health.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_telegram(*, timeout: int = 15) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    result: Dict[str, Any] = {
        "checked_at_utc": _now(),
        "status": "error",
        "auth_ok": False,
        "chat_ok": False,
        "error_kind": None,
        "http_status": None,
        "description": None,
        "bot_username": None,
        "permissions": {},
    }

    if not token:
        result.update(error_kind="token_missing", description="TELEGRAM_BOT_TOKEN is missing")
        return result
    if not chat:
        result.update(error_kind="chat_missing", description="TELEGRAM_CHANNEL_ID is missing")
        return result

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=timeout,
        )
    except requests.RequestException as exc:
        result.update(error_kind="transport", description=str(exc)[:500])
        return result

    result["http_status"] = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = {"ok": False, "description": response.text[:500]}

    if response.status_code == 401:
        result.update(
            error_kind="token_unauthorized",
            description=str(payload.get("description") or "Telegram token rejected")[:500],
        )
        return result
    if response.status_code >= 400 or payload.get("ok") is not True:
        result.update(
            error_kind="telegram_api",
            description=str(payload.get("description") or payload)[:500],
        )
        return result

    bot = payload.get("result") or {}
    result["auth_ok"] = True
    result["bot_username"] = bot.get("username")
    bot_id = bot.get("id")

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getChatMember",
            params={"chat_id": chat, "user_id": bot_id},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        result.update(error_kind="transport", description=str(exc)[:500])
        return result

    result["http_status"] = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = {"ok": False, "description": response.text[:500]}

    if response.status_code == 401:
        result.update(
            auth_ok=False,
            error_kind="token_unauthorized",
            description=str(payload.get("description") or "Telegram token rejected")[:500],
        )
        return result
    if response.status_code >= 400 or payload.get("ok") is not True:
        result.update(
            error_kind="chat_access",
            description=str(payload.get("description") or payload)[:500],
        )
        return result

    member = payload.get("result") or {}
    member_status = str(member.get("status") or "")
    is_creator = member_status == "creator"
    is_admin = member_status == "administrator"
    permissions = {
        "status": member_status,
        "can_post_messages": bool(is_creator or member.get("can_post_messages") is True),
        "can_edit_messages": bool(is_creator or member.get("can_edit_messages") is True),
        "can_delete_messages": bool(is_creator or member.get("can_delete_messages") is True),
    }
    result["permissions"] = permissions

    missing = [
        name
        for name in ("can_post_messages", "can_edit_messages", "can_delete_messages")
        if not permissions[name]
    ]
    if not (is_creator or is_admin) or missing:
        result.update(
            error_kind="chat_permission",
            description=(
                f"bot membership status={member_status or 'unknown'}; "
                f"missing permissions={','.join(missing) if missing else 'administrator'}"
            ),
        )
        return result

    result.update(status="healthy", chat_ok=True, error_kind=None, description=None)
    return result


def write_status(status: Dict[str, Any], path: Path = DEFAULT_STATUS_PATH) -> None:
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    status = check_telegram()
    write_status(status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status.get("status") == "healthy" else 2


if __name__ == "__main__":
    raise SystemExit(main())
