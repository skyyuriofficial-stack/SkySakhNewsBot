"""Offline Telegram health regressions. Never call Telegram or use live secrets."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

# Isolate these unit tests from unrelated runtime patches and live services.
with patch.dict(sys.modules, {"runtime_source_hardening": types.SimpleNamespace(install=lambda: None)}):
    import telegram_health as health


class TelegramHealthTests(unittest.TestCase):
    def setUp(self):
        self.token = "offline-credential-for-unit-tests"
        self.chat = "@offline_test_channel"
        self.environment = patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": self.token,
            "TELEGRAM_CHANNEL_ID": self.chat,
            "TELEGRAM_EXPECTED_BOT_USERNAME": "offline_test_bot",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.transport = patch.object(health.requests, "get")
        self.get = self.transport.start()
        self.addCleanup(self.transport.stop)
        self.get.side_effect = AssertionError("Unexpected network request")

    def response(self, status, payload=None, text=""):
        response = Mock(status_code=status, text=text)
        if payload is None:
            response.json.side_effect = ValueError("Not JSON")
        else:
            response.json.return_value = payload
        return response

    def me(self):
        return self.response(200, {"ok": True, "result": {"id": 42, "username": "offline_test_bot"}})

    def test_missing_token_does_not_call_network(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = ""
        self.assertEqual(health.check_telegram()["error_kind"], "token_missing")
        self.get.assert_not_called()

    def test_missing_channel_does_not_call_network(self):
        os.environ["TELEGRAM_CHANNEL_ID"] = ""
        self.assertEqual(health.check_telegram()["error_kind"], "chat_missing")
        self.get.assert_not_called()

    def test_transport_error_redacts_before_truncation(self):
        self.get.side_effect = health.requests.ConnectionError("x" * 490 + " https://api.telegram.org/bot" + self.token + "/getMe")
        result = health.check_telegram()
        self.assertEqual(result["error_kind"], "transport")
        self.assertNotIn(self.token, json.dumps(result))
        self.assertNotIn(self.token[:10], result["description"])
        self.assertLessEqual(len(result["description"]), 500)

    def test_transport_error_after_auth_does_not_leak(self):
        self.get.side_effect = [self.me(), health.requests.ConnectionError("https://api.telegram.org/bot" + self.token + "/getChatMember?chat_id=" + self.chat)]
        result = health.check_telegram()
        self.assertTrue(result["auth_ok"])
        self.assertFalse(result["chat_ok"])
        self.assertNotIn(self.token, json.dumps(result))
        self.assertNotIn(self.chat, json.dumps(result))

    def test_non_json_response_is_sanitized(self):
        self.get.side_effect = [self.response(502, text="Bad gateway https://api.telegram.org/bot" + self.token + "/getMe")]
        result = health.check_telegram()
        self.assertEqual(result["error_kind"], "telegram_api")
        self.assertNotIn(self.token, json.dumps(result))

    def test_invalid_chat_configuration_fails_before_network(self):
        os.environ["TELEGRAM_CHANNEL_ID"] = "https://t.me/c/3918486965/317"
        result = health.check_telegram()
        self.assertEqual(result["error_kind"], "chat_config_invalid")
        self.get.assert_not_called()

    def test_bot_identity_mismatch_blocks_before_chat_lookup(self):
        os.environ["TELEGRAM_EXPECTED_BOT_USERNAME"] = "another_bot"
        self.get.side_effect = [self.me()]
        result = health.check_telegram()
        self.assertTrue(result["auth_ok"])
        self.assertFalse(result["chat_ok"])
        self.assertEqual(result["error_kind"], "bot_identity_mismatch")
        self.assertEqual(self.get.call_count, 1)

    def test_numeric_private_channel_id_reaches_telegram(self):
        os.environ["TELEGRAM_CHANNEL_ID"] = "-1003918486965"
        self.get.side_effect = [self.me(), self.response(400, {"ok": False, "description": "Bad Request: chat not found"})]
        result = health.check_telegram()
        self.assertTrue(result["auth_ok"])
        self.assertEqual(result["error_kind"], "chat_access")
        self.assertEqual(self.get.call_count, 2)

    def test_chat_not_found_is_not_token_failure(self):
        self.get.side_effect = [self.me(), self.response(400, {"ok": False, "description": "Bad Request: chat not found"})]
        result = health.check_telegram()
        self.assertTrue(result["auth_ok"])
        self.assertFalse(result["chat_ok"])
        self.assertEqual(result["error_kind"], "chat_access")
        self.assertEqual(result["description"], "Bad Request: chat not found")

    def test_unauthorized_still_blocks(self):
        self.get.side_effect = [self.response(401, {"ok": False, "description": "Unauthorized " + self.token})]
        result = health.check_telegram()
        self.assertFalse(result["auth_ok"])
        self.assertEqual(result["error_kind"], "token_unauthorized")
        self.assertNotIn(self.token, result["description"])

    def test_missing_permission_still_blocks(self):
        self.get.side_effect = [self.me(), self.response(200, {"ok": True, "result": {"status": "administrator", "can_post_messages": True, "can_edit_messages": True}})]
        self.assertEqual(health.check_telegram()["error_kind"], "chat_permission")

    def test_full_permissions_are_healthy(self):
        self.get.side_effect = [self.me(), self.response(200, {"ok": True, "result": {"status": "administrator", "can_post_messages": True, "can_edit_messages": True, "can_delete_messages": True}})]
        result = health.check_telegram()
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["auth_ok"] and result["chat_ok"])

    def test_encoded_secret_is_redacted(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "offline:token/example"
        self.assertNotIn("offline", health._safe_description(quote(os.environ["TELEGRAM_BOT_TOKEN"], safe="")))

    def test_previous_token_in_url_is_redacted(self):
        value = health._safe_description("https://api.telegram.org/botprevious-offline-credential/getMe")
        self.assertNotIn("previous-offline-credential", value)

    def test_persistence_redacts_external_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            health.write_status({"status": "error", "description": self.token}, path)
            self.assertNotIn(self.token, path.read_text())


class WorkflowDestinationTests(unittest.TestCase):
    """All active producers and their health gates must route to the same channel."""
    WORKFLOWS = ("auto_publish_v7.yml", "editorial_monitor.yml", "delivery_recovery.yml", "mobilization_digest.yml", "post_publication_monitor.yml")

    def test_confirmed_destination_is_consistent(self):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for name in self.WORKFLOWS:
            with self.subTest(workflow=name):
                text = (root / name).read_text(encoding="utf-8")
                destinations = [line.strip() for line in text.splitlines() if line.strip().startswith("TELEGRAM_CHANNEL_ID:")]
                self.assertTrue(destinations)
                self.assertTrue(all(line == 'TELEGRAM_CHANNEL_ID: "-1003918486965"' for line in destinations))
                self.assertNotIn("secrets.TELEGRAM_CHANNEL_ID", text)

    def test_expected_bot_identity_is_consistent(self):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for name in self.WORKFLOWS:
            with self.subTest(workflow=name):
                text = (root / name).read_text(encoding="utf-8")
                identities = [line.strip() for line in text.splitlines() if line.strip().startswith("TELEGRAM_EXPECTED_BOT_USERNAME:")]
                self.assertTrue(identities)
                self.assertTrue(all(line == 'TELEGRAM_EXPECTED_BOT_USERNAME: "SkySakhNewsPublisher_bot"' for line in identities))

    def test_credentials_stay_in_secrets(self):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for name in self.WORKFLOWS:
            with self.subTest(workflow=name):
                lines = (root / name).read_text(encoding="utf-8").splitlines()
                tokens = [line.strip() for line in lines if line.strip().startswith("TELEGRAM_BOT_TOKEN:")]
                self.assertTrue(tokens)
                self.assertTrue(all(line == "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" for line in tokens))


if __name__ == "__main__":
    unittest.main()
