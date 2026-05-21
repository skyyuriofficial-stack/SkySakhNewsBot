# SkySakhNews executable system smoke test.
# Verifies that the automation runtime can load modules, generate a thematic image,
# read queue/state files, and access Telegram Bot API. Optional live send/delete test
# is controlled by SMOKE_SEND=1.

import io
import json
import os
import time
from pathlib import Path

import requests

from thematic_image import generate_thematic_image

ROOT = Path(__file__).resolve().parents[1]
QUEUE_FILE = ROOT / "editorial_queue.json"
STATE_FILE = ROOT / "state.json"
WORKFLOW_FILE = ROOT / ".github" / "workflows" / "editorial_cycle.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict:
    require(path.exists(), f"Missing required file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_files() -> None:
    queue = load_json(QUEUE_FILE)
    state = load_json(STATE_FILE)
    workflow = WORKFLOW_FILE.read_text(encoding="utf-8")

    require(isinstance(queue.get("items"), list), "editorial_queue.json must contain items list")
    require("Collect drafts" in workflow, "editorial_cycle.yml missing Collect step")
    require("Review drafts" in workflow, "editorial_cycle.yml missing Review step")
    require("Final guard" in workflow, "editorial_cycle.yml missing Final guard step")
    require("editorial_publish_safe.py" in workflow, "editorial_cycle.yml must publish via editorial_publish_safe.py")
    require(isinstance(state, dict), "state.json must be a JSON object")

    print(f"files: ok; queue_items={len(queue.get('items', []))}; state_keys={len(state.keys())}")


def check_generated_image() -> tuple[bytes, str, str]:
    item = {
        "category": "🇷🇺 РФ / война и безопасность",
        "title_ru": "Системная проверка генерации тематической иллюстрации",
        "url": "smoke-test://local",
    }
    data, content_type, filename = generate_thematic_image(item)
    require(content_type == "image/jpeg", "generated image must be image/jpeg")
    require(filename.endswith(".jpg"), "generated image filename must end with .jpg")
    require(len(data) > 20_000, f"generated image is too small: {len(data)} bytes")
    require(data[:2] == b"\xff\xd8", "generated image is not a JPEG")
    print(f"generated_image: ok; bytes={len(data)}; content_type={content_type}")
    return data, content_type, filename


def telegram_api(method: str, token: str, **kwargs) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    files = kwargs.pop("files", None)
    timeout = kwargs.pop("timeout", 30)
    if files:
        response = requests.post(url, data=kwargs, files=files, timeout=timeout)
    else:
        response = requests.post(url, data=kwargs, timeout=timeout)
    try:
        payload = response.json()
    except Exception:
        raise RuntimeError(f"Telegram {method} returned non-JSON response: HTTP {response.status_code}")
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {payload}")
    return payload


def check_telegram(data: bytes) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    require(bool(token), "TELEGRAM_BOT_TOKEN is missing")
    require(bool(channel_id), "TELEGRAM_CHANNEL_ID is missing")

    me = telegram_api("getMe", token)
    print(f"telegram_getMe: ok; bot=@{me['result'].get('username')}")

    chat = telegram_api("getChat", token, chat_id=channel_id)
    print(f"telegram_getChat: ok; title={chat['result'].get('title')}; type={chat['result'].get('type')}")

    if os.getenv("SMOKE_SEND", "0") != "1":
        print("telegram_send_delete: skipped; set SMOKE_SEND=1 for live send/delete test")
        return

    caption = "🧪 SkySakhNews system smoke test. Автоудаление через 3 секунды."
    send = telegram_api(
        "sendPhoto",
        token,
        chat_id=channel_id,
        caption=caption,
        disable_notification="true",
        files={"photo": ("smoke.jpg", io.BytesIO(data), "image/jpeg")},
        timeout=60,
    )
    message_id = send["result"]["message_id"]
    print(f"telegram_sendPhoto: ok; message_id={message_id}")
    time.sleep(3)
    telegram_api("deleteMessage", token, chat_id=channel_id, message_id=str(message_id))
    print("telegram_deleteMessage: ok")


def main() -> None:
    check_files()
    image_data, _, _ = check_generated_image()
    check_telegram(image_data)
    print("SYSTEM_SMOKE_TEST_OK")


if __name__ == "__main__":
    main()
