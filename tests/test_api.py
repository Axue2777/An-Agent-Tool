"""FastAPI 接口集成测试，数据库、文件和模型均已隔离。"""
from unittest.mock import patch
from uuid import UUID, uuid4
import database
import file_tools
import report_tools
from tests.support import AppCase


class TestChatApi(AppCase):
    def test_chat_saves_one_user_and_one_answer(self):
        response = self.api.post("/chat", json=self.request())
        self.assertEqual(response.status_code, 200)
        chat = database.get_conversation(self.chat_id)
        self.assertEqual([m["role"] for m in chat["messages"]], ["user", "assistant"])
        self.assertEqual(chat["messages"][-1]["content"], "测试回答")
        self.assertTrue((self.records / str(self.chat_id) / "chat.md").is_file())

    def test_client_history_not_saved_twice(self):
        payload = self.request()
        payload["messages"] = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": "新问题"},
        ]
        self.assertEqual(self.api.post("/chat", json=payload).status_code, 200)
        history = database.get_conversation(self.chat_id)["messages"]
        self.assertEqual([m["content"] for m in history], ["新问题", "测试回答"])

    def test_request_schema_rejects_bad_payloads(self):
        payloads = [
            {}, {"message": "旧接口字段"}, {"messages": []},
            self.request(""), self.request("x" * 10001),
            {"messages": [{"role": "system", "content": "不能注入系统角色"}]},
            {"messages": [{"role": "user", "content": "x"}] * 51},
            self.request(conversation_id="11"),
        ]
        for payload in payloads:
            with self.subTest(keys=list(payload)):
                self.assertEqual(self.api.post("/chat", json=payload).status_code, 422)
        self.agent.assert_not_called()

    def test_last_message_must_be_user(self):
        payload = {"messages": [{"role": "assistant", "content": "错误角色"}]}
        self.assertEqual(self.api.post("/chat", json=payload).status_code, 422)
        self.agent.assert_not_called()

    def test_whitespace_only_message_is_rejected(self):
        # 前端会 trim，但后端也应独立拒绝空白内容。
        response = self.api.post("/chat", json=self.request(" \n\t "))
        self.assertEqual(response.status_code, 422)
        self.agent.assert_not_called()

    def test_stream_rejects_whitespace_before_creating_task(self):
        # 两种聊天入口共用请求校验，空白请求不应触发模型或保存会话。
        for text in (" ", "\n\t", "\u3000"):
            with self.subTest(text=repr(text)):
                response = self.api.post("/chat/stream", json=self.request(text))
                self.assertEqual(response.status_code, 422)
        self.agent.assert_not_called()
        self.assertEqual(self.main.active_tasks, {})
        self.assertIsNone(database.get_conversation(self.chat_id))

    def test_validation_preserves_markdown_whitespace(self):
        text = "  保留缩进\n\n    print('hello')\n"
        self.assertEqual(self.api.post("/chat", json=self.request(text)).status_code, 200)
        saved = database.get_conversation(self.chat_id)["messages"][0]["content"]
        self.assertEqual(saved, text)

    def test_agent_failure_returns_502_without_false_assistant(self):
        self.agent.side_effect = RuntimeError("secret-internal-detail")
        response = self.api.post("/chat", json=self.request())
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-internal-detail", response.text)
        self.assertEqual(len(database.get_conversation(self.chat_id)["messages"]), 1)
        record = (self.records / str(self.chat_id) / "chat.md").read_text(encoding="utf-8")
        self.assertIn("RuntimeError", record)

    def test_web_switch_reaches_agent(self):
        self.api.post("/chat", json=self.request(web_search=False))
        self.assertFalse(self.agent.call_args.kwargs["web_search"])


class TestHistoryApi(AppCase):
    def test_create_list_rename_detail_delete(self):
        response = self.api.post("/chat/history")
        self.assertEqual(response.status_code, 201)
        chat_id = response.json()["id"]
        UUID(chat_id)
        self.assertEqual(len(self.api.get("/chat/history").json()["conversations"]), 1)
        response = self.api.patch(f"/chat/history/{chat_id}", json={"title": "  手动标题  "})
        self.assertEqual(response.json()["title"], "手动标题")
        self.assertEqual(self.api.get(f"/chat/history/{chat_id}").json()["title"], "手动标题")
        self.assertEqual(self.api.delete(f"/chat/history/{chat_id}").status_code, 200)
        self.assertEqual(self.api.get(f"/chat/history/{chat_id}").status_code, 404)

    def test_invalid_uuid_and_unknown_chat(self):
        self.assertEqual(self.api.get("/chat/history/11").status_code, 422)
        self.assertEqual(self.api.get(f"/chat/history/{uuid4()}").status_code, 404)
        self.assertEqual(self.api.delete(f"/chat/history/{uuid4()}").status_code, 404)

    def test_rename_validation(self):
        database.create_conversation(self.chat_id)
        for title in ("", "   ", "x" * 61):
            with self.subTest(length=len(title)):
                response = self.api.patch(f"/chat/history/{self.chat_id}", json={"title": title})
                self.assertEqual(response.status_code, 422)

    def test_export_file_and_missing_record(self):
        database.create_conversation(self.chat_id)
        endpoint = f"/chat/history/{self.chat_id}/export"
        self.assertEqual(self.api.get(endpoint).status_code, 404)
        self.api.post("/chat", json=self.request("导出测试"))
        response = self.api.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("导出测试", response.text)
        self.assertIn("测试回答", response.text)

    def test_delete_keeps_markdown_but_export_is_404(self):
        self.api.post("/chat", json=self.request())
        self.api.delete(f"/chat/history/{self.chat_id}")
        self.assertTrue((self.records / str(self.chat_id) / "chat.md").exists())
        self.assertEqual(self.api.get(f"/chat/history/{self.chat_id}/export").status_code, 404)


class TestUploadDownloadApi(AppCase):
    def test_utf8_upload_is_readable_and_original_name_not_used_as_path(self):
        database.create_conversation(self.chat_id)
        response = self.api.post(f"/chat/upload/{self.chat_id}", files={
            "file": ("../中文资料.md", "# 中文资料".encode(), "text/markdown"),
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        UUID(data["file_id"])
        result = file_tools.read_attachment(data["file_id"], self.chat_id)
        self.assertEqual(result["content"], "# 中文资料")
        self.assertEqual(data["characters"], len("# 中文资料"))
        self.assertFalse((self.records / "中文资料.md").exists())

    def test_empty_bad_format_and_bad_encoding_are_400(self):
        for filename, data in (("empty.txt", b""), ("script.exe", b"exe"), ("bad.txt", b"\xff\xfe"), ("bad.docx", b"broken")):
            with self.subTest(filename=filename):
                response = self.api.post(f"/chat/upload/{self.chat_id}", files={"file": (filename, data)})
                self.assertEqual(response.status_code, 400)

    def test_oversized_upload_rejected_before_parser(self):
        with patch.object(self.main, "parse_document") as parse:
            response = self.api.post(f"/chat/upload/{self.chat_id}", files={"file": ("huge.txt", b"x" * (10 * 1024 * 1024 + 1))})
        self.assertEqual(response.status_code, 413)
        parse.assert_not_called()

    def test_upload_parser_errors_are_safe(self):
        with patch.object(self.main, "parse_document", side_effect=RuntimeError("private-internal")):
            response = self.api.post(f"/chat/upload/{self.chat_id}", files={"file": ("image.png", b"fake")})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("private-internal", response.text)

    def test_report_download_and_conversation_isolation(self):
        result = report_tools.save_report("# 报告", self.chat_id)
        endpoint = result["download_url"]
        response = self.api.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "# 报告")
        other = endpoint.replace(str(self.chat_id), str(uuid4()))
        self.assertEqual(self.api.get(other).status_code, 404)
        self.assertEqual(self.api.get(f"/chat/files/{self.chat_id}/bad-id").status_code, 422)

