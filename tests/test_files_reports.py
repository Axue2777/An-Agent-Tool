"""附件分段、会话路径隔离和报告写入测试。"""
from uuid import uuid4
import file_tools
import report_tools
from tests.support import SandboxCase


class TestAttachments(SandboxCase):
    def test_read_short_attachment(self):
        chat_id = uuid4()
        file_id = self.attachment(chat_id, "中文附件")
        result = file_tools.read_attachment(str(file_id), chat_id)
        self.assertEqual(result["content"], "中文附件")
        self.assertTrue(result["finished"])
        self.assertIsNone(result["next_offset"])

    def test_read_all_chunks_without_loss(self):
        chat_id = uuid4()
        text = "甲" * 8000 + "乙" * 8000 + "尾页"
        file_id = self.attachment(chat_id, text)
        parts, offset = [], 0
        while True:
            result = file_tools.read_attachment(str(file_id), chat_id, offset)
            self.assertLessEqual(len(result["content"]), 8000)
            parts.append(result["content"])
            if result["finished"]:
                break
            self.assertGreater(result["next_offset"], offset)
            offset = result["next_offset"]
        self.assertEqual("".join(parts), text)

    def test_exact_chunk_boundary_is_finished(self):
        chat_id = uuid4()
        file_id = self.attachment(chat_id, "a" * 8000)
        self.assertTrue(file_tools.read_attachment(str(file_id), chat_id)["finished"])

    def test_other_conversation_cannot_read_same_file(self):
        chat_id = uuid4()
        file_id = self.attachment(chat_id, "私有附件")
        result = file_tools.read_attachment(str(file_id), uuid4())
        self.assertIn("error", result)
        self.assertNotIn("content", result)

    def test_offset_and_file_id_validation(self):
        for offset in (-1, True, "0", 0.5, None):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                file_tools.read_attachment(str(uuid4()), uuid4(), offset)
        for value in ("../../secret", "not-a-uuid", 123, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                file_tools.read_attachment(value, uuid4())

    def test_eof_and_missing_file_are_errors(self):
        chat_id = uuid4()
        file_id = self.attachment(chat_id, "abc")
        for offset in (3, 4):
            self.assertIn("error", file_tools.read_attachment(str(file_id), chat_id, offset))
        self.assertIn("error", file_tools.read_attachment(str(uuid4()), chat_id))


class TestReports(SandboxCase):
    def test_report_saved_under_conversation_and_not_overwritten(self):
        chat_id = uuid4()
        first = report_tools.save_report("# 中文报告", chat_id)
        second = report_tools.save_report("# 第二份", chat_id)
        self.assertNotEqual(first["download_url"], second["download_url"])
        paths = list((self.records / str(chat_id) / "artifacts").glob("*.md"))
        self.assertEqual(len(paths), 2)
        self.assertIn("# 中文报告", [p.read_text(encoding="utf-8") for p in paths])
        self.assertTrue(first["download_url"].startswith(f"/chat/files/{chat_id}/"))

    def test_invalid_report_rejected_without_writing(self):
        for content in ("", "  ", None, 42, "a" * 100001):
            with self.subTest(content_type=type(content).__name__), self.assertRaises(ValueError):
                report_tools.save_report(content, uuid4())
        self.assertEqual(list(self.records.iterdir()), [])

