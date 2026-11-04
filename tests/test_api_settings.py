"""Isolated settings tests: no real vault, .env file, database or paid API."""
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import APITimeoutError
import api_settings as settings


class MemoryVault:
    def __init__(self):
        self.value = None

    def get_password(self, service, username):
        return self.value

    def set_password(self, service, username, value):
        self.value = value


class TestApiSettings(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault()
        self.vault_patch = patch.object(settings, "_vault", return_value=self.vault)
        self.vault_patch.start()
        self.addCleanup(self.vault_patch.stop)
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.network = patch("httpx.HTTPTransport.handle_request",
                             side_effect=AssertionError("Real network is forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        app = FastAPI()
        app.include_router(settings.router)
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)

    def payload(self, **changes):
        data = {"revision": settings.load_settings().revision,
                "provider": "deepseek", "deepseek_model": "deepseek-flash",
                "zhipu_model": "glm-4.7-flash", "search_enabled": False,
                "share_chat_key": False}
        data.update(changes)
        return data

    def save(self, **changes):
        return self.client.post("/chat/settings", json=self.payload(**changes))

    def test_empty_setup_can_open(self):
        response = self.client.get("/chat/settings")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["chat_configured"])

    def test_save_does_not_echo_keys_or_call_model(self):
        with patch.object(settings, "create_chat_client") as create:
            response = self.save(deepseek_key="private-ds-sentinel")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-ds-sentinel", response.text)
        create.assert_not_called()
        response = self.client.get("/chat/settings")
        self.assertNotIn("private-ds-sentinel", response.text)
        self.assertNotIn("deepseek_key", response.json())

    def test_deepseek_cannot_enable_search(self):
        response = self.save(search_enabled=True)
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.vault.value)

    def test_zhipu_search_uses_chat_key(self):
        response = self.save(provider="zhipu", share_chat_key=False,
                             search_enabled=True, zhipu_key="glm-secret")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(settings.search_key(settings.load_settings()), "glm-secret")
        self.assertTrue(response.json()["share_chat_key"])

    def test_legacy_independent_search_key_is_ignored(self):
        self.save(provider="zhipu", zhipu_key="chat-secret", search_key="search-secret")
        config = settings.load_settings()
        self.assertEqual(settings.chat_key(config), "chat-secret")
        self.assertEqual(settings.search_key(config), "chat-secret")

    def test_old_deepseek_settings_cannot_expose_search(self):
        old = settings.Settings(provider="deepseek", search_enabled=True,
                                search_key="legacy-search-key")
        self.assertEqual(settings.search_key(old), "")
        self.assertFalse(settings.public_settings(old)["search_enabled"])
        self.assertFalse(settings.public_settings(old)["search_configured"])

    def test_deepseek_search_test_is_rejected_before_network(self):
        self.save(deepseek_key="ds-secret")
        response = self.client.post("/chat/settings/test", json={"kind": "search"})
        self.assertEqual(response.status_code, 422)

    def test_zhipu_busy_error_is_not_reported_as_balance_problem(self):
        class Busy(Exception):
            status_code = 429
            body = {"error": {"code": "1305"}}

        self.save(provider="zhipu", zhipu_key="zhipu-key")
        with patch.object(settings, "create_chat_client", side_effect=Busy()):
            response = self.client.post("/chat/settings/test", json={"kind": "chat"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("模型当前繁忙", response.json()["detail"])
        self.assertNotIn("余额", response.text)

    def test_streaming_errors_have_safe_specific_messages(self):
        config = settings.Settings(provider="zhipu")
        timeout = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        self.assertIn("超时", settings.describe_chat_error(timeout, config))

        class Busy(Exception):
            status_code = 429
            body = {"error": {"code": "1305", "message": "private-provider-detail"}}

        message = settings.describe_chat_error(Busy(), config)
        self.assertIn("繁忙", message)
        self.assertNotIn("private-provider-detail", message)

    def test_omitted_key_keeps_secret(self):
        self.save(deepseek_key="keep-me")
        self.save()
        self.assertEqual(settings.chat_key(settings.load_settings()), "keep-me")

    def test_clear_does_not_restore_legacy_environment_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "legacy-secret"}):
            self.save(deepseek_key="")
            self.assertEqual(settings.chat_key(settings.load_settings()), "")

    def test_invalid_input_does_not_echo_secret(self):
        payload = self.payload(deepseek_key="private-secret", provider={"wrong": True})
        response = self.client.post("/chat/settings", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private-secret", response.text)

    def test_cross_origin_write_is_rejected(self):
        response = self.client.post("/chat/settings", json=self.payload(),
                                    headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_exact_dev_frontend_origin_can_save_settings(self):
        with patch.dict(os.environ, {"AGENT_SETTINGS_ORIGIN": "http://127.0.0.1:5175"}):
            response = self.client.post(
                "/chat/settings", json=self.payload(deepseek_key="dev-key"),
                headers={"Origin": "http://127.0.0.1:5175"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(settings.chat_key(settings.load_settings()), "dev-key")

    def test_other_local_port_remains_blocked(self):
        with patch.dict(os.environ, {"AGENT_SETTINGS_ORIGIN": "http://127.0.0.1:5175"}):
            response = self.client.post(
                "/chat/settings", json=self.payload(),
                headers={"Origin": "http://127.0.0.1:5176"},
            )
        self.assertEqual(response.status_code, 403)

    def test_unknown_hostname_is_rejected(self):
        response = self.client.get("/chat/settings", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_stale_revision_does_not_overwrite_new_settings(self):
        old = self.payload(deepseek_key="stale-key")
        self.save(deepseek_key="new-key")
        response = self.client.post("/chat/settings", json=old)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(settings.chat_key(settings.load_settings()), "new-key")

    def test_existing_request_snapshot_does_not_change(self):
        self.save(deepseek_key="first-key")
        snapshot = settings.load_settings()
        self.save(deepseek_key="second-key")
        self.assertEqual(settings.chat_key(snapshot), "first-key")
        self.assertEqual(settings.chat_key(settings.load_settings()), "second-key")

    def test_vault_failure_is_reported_without_details(self):
        with patch.object(settings, "_vault", side_effect=RuntimeError("private-secret")):
            response = self.client.get("/chat/settings")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-secret", response.text)

    def test_large_input_is_rejected(self):
        response = self.client.post("/chat/settings", content=json.dumps({"data": "x" * 9000}),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_test_button_is_mocked_no_paid_api(self):
        with patch.object(settings, "_test_connection", return_value={"ok": True}) as test:
            response = self.client.post("/chat/settings/test", json={"kind": "chat"})
        self.assertEqual(response.status_code, 200)
        test.assert_called_once_with("chat")


if __name__ == "__main__":
    unittest.main()
