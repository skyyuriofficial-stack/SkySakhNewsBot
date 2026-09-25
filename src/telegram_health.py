from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

import requests
import runtime_source_hardening

runtime_source_hardening.install()

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_PATH = ROOT / "telegram_health.json"
EXPECTED_BOT_USERNAME = os.getenv("TELEGRAM_EXPECTED_BOT_USERNAME", "SkySakhNewsPublisher_bot").strip().lstrip("@")
_CHAT_ID_RE = re.compile(r"^-100\d{6,}$")
_CHAT_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{4,31}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_description(value: Any) -> str:
    """Redact credentials before truncation, persistence or workflow logging."""
    text = str(value)
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID"):
        secret = os.getenv(name, "").strip()
        if secret:
            for variant in (secret, quote(secret, safe="")):
                text = text.replace(variant, "[REDACTED]")
    text = re.sub(
        r"(?i)(https?://api\.telegram\.org/(?:file/)?bot)[^/\s\"'<>]+",
        r"\1[REDACTED]", text,
    )
    text = re.sub(r"(?<!\w)\d{6,16}:[A-Za-z0-9_-]{20,}(?!\w)", "[REDACTED]", text)
    return text[:500]


def check_telegram(*, timeout: int = 15) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    result: Dict[str, Any] = {
        "checked_at_utc": _now(), "status": "error", "auth_ok": False,
        "chat_ok": False, "error_kind": None, "http_status": None,
        "description": None, "bot_username": None, "permissions": {},
    }
    if not token:
        result.update(error_kind="token_missing", description="TELEGRAM_BOT_TOKEN is missing")
        return result
    if not chat:
        result.update(error_kind="chat_missing", description="TELEGRAM_CHANNEL_ID is missing")
        return result
    if not (_CHAT_ID_RE.fullmatch(chat) or _CHAT_USERNAME_RE.fullmatch(chat)):
        result.update(error_kind="chat_config_invalid", description="Telegram destination must be a -100... channel id or @channel username")
        return result
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=timeout)
    except requests.RequestException as exc:
        result.update(error_kind="transport", description=_safe_description(exc))
        return result
    result["http_status"] = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = {"ok": False, "description": _safe_description(response.text)}
    if response.status_code == 401:
        result.update(error_kind="token_unauthorized", description=_safe_description(payload.get("description") or "Telegram token rejected"))
        return result
    if response.status_code >= 400 or payload.get("ok") is not True:
        result.update(error_kind="telegram_api", description=_safe_description(payload.get("description") or payload))
        return result
    bot = payload.get("result") or {}
    result["auth_ok"] = True
    result["bot_username"] = bot.get("username")
    actual_username = str(bot.get("username") or "").strip().lstrip("@")
    expected_username = os.getenv("TELEGRAM_EXPECTED_BOT_USERNAME", EXPECTED_BOT_USERNAME).strip().lstrip("@")
    if expected_username and actual_username.lower() != expected_username.lower():
        result.update(
            error_kind="bot_identity_mismatch",
            description=f"authenticated bot @{actual_username or 'unknown'} does not match expected @{expected_username}",
        )
        return result
    bot_id = bot.get("id")
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getChatMember",
            params={"chat_id": chat, "user_id": bot_id}, timeout=timeout,
        )
    except requests.RequestException as exc:
        result.update(error_kind="transport", description=_safe_description(exc))
        return result
    result["http_status"] = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = {"ok": False, "description": _safe_description(response.text)}
    if response.status_code == 401:
        result.update(auth_ok=False, error_kind="token_unauthorized", description=_safe_description(payload.get("description") or "Telegram token rejected"))
        return result
    if response.status_code >= 400 or payload.get("ok") is not True:
        result.update(error_kind="chat_access", description=_safe_description(payload.get("description") or payload))
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
    missing = [name for name in ("can_post_messages", "can_edit_messages", "can_delete_messages") if not permissions[name]]
    if not (is_creator or is_admin) or missing:
        result.update(error_kind="chat_permission", description=_safe_description(
            f"bot membership status={member_status or 'unknown'}; "
            f"missing permissions={','.join(missing) if missing else 'administrator'}"
        ))
        return result
    result.update(status="healthy", chat_ok=True, error_kind=None, description=None)
    return result


def write_status(status: Dict[str, Any], path: Path = DEFAULT_STATUS_PATH) -> None:
    # Defence in depth for callers supplying an externally produced description.
    safe = dict(status)
    if safe.get("description") is not None:
        safe["description"] = _safe_description(safe["description"])
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    status = check_telegram()
    write_status(status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status.get("status") == "healthy" else 2


if __name__ == "__main__":
    raise SystemExit(main())
