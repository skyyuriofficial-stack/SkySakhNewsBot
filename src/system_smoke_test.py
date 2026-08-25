"""Manual smoke test for the current stable-v10.2 production system."""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "state.json"
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "auto_publish_v7.yml"
PRODUCTION_FILES = (
    ROOT / "src" / "news_bot_v8.py",
    ROOT / "src" / "news_bot_v9.py",
    ROOT / "src" / "production.py",
    ROOT / "src" / "editorial_gate.py",
    ROOT / "src" / "category_reconciler.py",
    ROOT / "src" / "editorial_gate_runner.py",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def check_files_and_imports() -> None:
    require(STATE_FILE.exists(), "state.json is missing")
    require(PUBLISH_WORKFLOW.exists(), "production publisher workflow is missing")
    for path in PRODUCTION_FILES:
        require(path.exists(), f"missing production module: {path}")

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    require(isinstance(state, dict), "state.json must be a JSON object")

    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    require("SkySakhNews Auto Publisher Stable v10.2" in workflow, "publisher is not stable-v10.2")
    require("editorial_gate_runner.py" in workflow, "publisher bypasses editorial gate")
    require("schedule:" in workflow, "publisher schedule is missing")

    sys.path.insert(0, str(ROOT / "src"))
    import editorial_gate as gate
    import category_reconciler as reconciler
    import editorial_gate_runner as runner

    require(runner.VERSION == "stable-v10.2", f"unexpected production version: {runner.VERSION}")

    sample = {
        "title": "Аэропорт ограничил работу из-за угрозы БПЛА",
        "source_text": "Росавиация сообщила об ограничениях из-за беспилотников.",
        "source": "Interfax",
        "url": "https://www.interfax.ru/russia/1",
        "category_key": "ru_pol",
        "category": "Россия / политика",
    }
    require(reconciler.suggest_category(sample) == "ru_security", "category reconciler smoke test failed")

    verdict = gate.deterministic_review(
        {
            **sample,
            "category_key": "ru_security",
            "category": "Россия / безопасность",
        },
        {
            "title_ru": sample["title"],
            "body": [],
            "editorial_mode": "extractive_fallback",
        },
    )
    require(verdict.get("approved") is True, f"editorial gate smoke test failed: {verdict}")
    print("production_files_and_semantics: ok")


def make_smoke_image() -> bytes:
    image = Image.new("RGB", (1200, 675), (28, 32, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1120, 595), outline=(230, 230, 230), width=5)
    draw.text((125, 285), "SkySakhNews stable-v10.2 smoke test", fill=(245, 245, 245))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    data = buffer.getvalue()
    require(data.startswith(b"\xff\xd8"), "smoke image is not JPEG")
    require(len(data) > 10_000, "smoke image is unexpectedly small")
    return data


def telegram_api(method: str, token: str, **kwargs) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    files = kwargs.pop("files", None)
    timeout = kwargs.pop("timeout", 30)
    response = requests.post(url, data=kwargs, files=files, timeout=timeout)
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Telegram {method} returned non-JSON: HTTP {response.status_code}") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {payload}")
    return payload


def check_telegram(image_data: bytes) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    require(bool(token), "TELEGRAM_BOT_TOKEN is missing")
    require(bool(channel_id), "TELEGRAM_CHANNEL_ID is missing")

    me = telegram_api("getMe", token)
    chat = telegram_api("getChat", token, chat_id=channel_id)
    print(f"telegram_getMe: ok; bot=@{me['result'].get('username')}")
    print(f"telegram_getChat: ok; title={chat['result'].get('title')}; type={chat['result'].get('type')}")

    if os.getenv("SMOKE_SEND", "0") != "1":
        print("telegram_send_delete: skipped")
        return

    sent = telegram_api(
        "sendPhoto",
        token,
        chat_id=channel_id,
        caption="🧪 SkySakhNews stable-v10.2 smoke test. Автоудаление через 3 секунды.",
        disable_notification="true",
        files={"photo": ("smoke.jpg", io.BytesIO(image_data), "image/jpeg")},
        timeout=60,
    )
    message_id = sent["result"]["message_id"]
    time.sleep(3)
    telegram_api("deleteMessage", token, chat_id=channel_id, message_id=str(message_id))
    print(f"telegram_send_delete: ok; message_id={message_id}")


def main() -> None:
    check_files_and_imports()
    image_data = make_smoke_image()
    check_telegram(image_data)
    print("SYSTEM_SMOKE_TEST_OK stable-v10.2")


if __name__ == "__main__":
    main()
