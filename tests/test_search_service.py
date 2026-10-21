"""MockTransport 模拟搜索供应商，验证错误处理和结果清洗。"""
import json
import os
from contextlib import contextmanager
from unittest.mock import patch
import httpx
import search_tools
from tests.support import SandboxCase

REAL_CLIENT = httpx.Client


class TestSearchService(SandboxCase):
    @contextmanager
    def provider(self, payload=None, status=200, failure=None):
        requests = []
        def handler(request):
            requests.append(request)
            if failure:
                raise failure
            return httpx.Response(status, json=payload)
        def factory(*args, **kwargs):
            return REAL_CLIENT(transport=httpx.MockTransport(handler), trust_env=False)
        with (
            patch.dict(os.environ, {"ZHIPU_API_KEY": "test-only-key"}),
            patch.object(search_tools.httpx, "Client", side_effect=factory),
        ):
            yield requests

    def test_request_and_normalized_results(self):
        payload = {"search_result": [{"title": "Vue 文档", "link": "https://example.com/vue",
                                     "content": "摘要", "publish_date": "2026-01-01"}]}
        with self.provider(payload) as requests:
            result = search_tools.search_web("  Vue  ")
        self.assertEqual(result["query"], "Vue")
        self.assertEqual(result["sources"][0]["url"], "https://example.com/vue")
        body = json.loads(requests[0].content)
        self.assertEqual(body["search_query"], "Vue")
        self.assertEqual(body["count"], 5)

    def test_missing_key_does_not_create_client(self):
        with patch.dict(os.environ, {"ZHIPU_API_KEY": ""}), patch.object(search_tools.httpx, "Client") as client:
            self.assertIn("error", search_tools.search_web("Vue"))
        client.assert_not_called()

    def test_query_validation(self):
        for query in ("", " ", "x" * 501, None, 1):
            with self.subTest(query_type=type(query).__name__), self.assertRaises(ValueError):
                search_tools.search_web(query)

    def test_unsafe_urls_filtered_and_text_truncated(self):
        payload = {"search_result": [
            {"link": "javascript:alert(1)"}, {"link": "file:///secret"},
            {"link": "https://example.com", "title": "t" * 300, "content": "x" * 3000},
        ]}
        with self.provider(payload):
            sources = search_tools.search_web("Vue")["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(len(sources[0]["title"]), 200)
        self.assertEqual(len(sources[0]["snippet"]), 2000)

    def test_empty_results_are_not_errors(self):
        with self.provider({"search_result": []}):
            self.assertEqual(search_tools.search_web("Vue")["sources"], [])

    def test_http_errors_do_not_leak_provider_body(self):
        for status in (401, 429, 500):
            with self.subTest(status=status), self.provider({"private": "private-response-body"}, status):
                result = search_tools.search_web("Vue")
                self.assertIn(str(status), result["error"])
                self.assertNotIn("private-response-body", json.dumps(result))
                self.assertNotIn("test-only-key", json.dumps(result))

    def test_timeout_returns_structured_error(self):
        with self.provider(failure=httpx.ReadTimeout("simulated")):
            self.assertIn("error", search_tools.search_web("Vue"))

    def test_missing_result_list_returns_error(self):
        with self.provider({"unexpected": []}):
            self.assertIn("error", search_tools.search_web("Vue"))

    def test_non_object_payload_returns_error_instead_of_crashing(self):
        # JSON 中的数组、空值、数字和字符串都不能当作结果对象使用。
        for payload in ([], None, 1, False, "unexpected"):
            with self.subTest(payload=payload), self.provider(payload):
                self.assertIn("error", search_tools.search_web("Vue"))

    def test_non_object_result_item_is_handled(self):
        with self.provider({"search_result": [None]}):
            result = search_tools.search_web("Vue")
        self.assertTrue("error" in result or result.get("sources") == [])

    def test_bad_items_do_not_discard_valid_results(self):
        payload = {"search_result": [
            None, 123, {"link": ["https://example.com"]},
            {"link": "https://[invalid"},
            {"link": "https://example.com/vue", "title": "Vue", "content": "有效摘要"},
        ]}
        with self.provider(payload):
            result = search_tools.search_web("Vue")
        self.assertNotIn("error", result)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["title"], "Vue")

    def test_non_string_text_fields_use_safe_defaults(self):
        with self.provider({"search_result": [{
            "link": "https://example.com", "title": 123,
            "content": {"bad": True}, "publish_date": [],
        }]}):
            source = search_tools.search_web("Vue")["sources"][0]
        self.assertEqual(source["title"], "未命名网页")
        self.assertEqual(source["snippet"], "")
        self.assertIsNone(source["published_date"])

    def test_incomplete_and_credential_urls_are_filtered(self):
        with self.provider({"search_result": [
            {"link": "https:///missing-host"},
            {"link": "https://user:password@example.com"},
            {"link": "https://example.com/valid"},
        ]}):
            sources = search_tools.search_web("Vue")["sources"]
        self.assertEqual([source["url"] for source in sources], ["https://example.com/valid"])

