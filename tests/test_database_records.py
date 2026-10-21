"""数据库与 Markdown 的隔离回归测试，不接触 agent.db 或真实 records。"""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
import chat_records
import database as db
from tests.support import SandboxCase


class TestDatabase(SandboxCase):
    def test_create_empty_and_reinitialize(self):
        chat_id = uuid4()
        chat = db.create_conversation(chat_id)
        self.assertEqual(chat["messages"], [])
        self.assertEqual(chat["title"], "新建聊天")
        db.init_db()
        self.assertIsNotNone(db.get_conversation(chat_id))

    def test_first_message_normalizes_and_truncates_title(self):
        chat_id = uuid4()
        db.create_conversation(chat_id)
        text = "  第一行\n 第二行  " + "长" * 50
        db.save_user_message(chat_id, text)
        self.assertEqual(db.get_conversation(chat_id)["title"], " ".join(text.split())[:30])

    def test_later_message_does_not_rename(self):
        chat_id = uuid4()
        db.save_user_message(chat_id, "首次问题")
        db.save_user_message(chat_id, "后续问题")
        self.assertEqual(db.get_conversation(chat_id)["title"], "首次问题")

    def test_manual_title_before_first_message_survives(self):
        chat_id = uuid4()
        db.create_conversation(chat_id)
        db.rename_conversation(chat_id, "手动命名")
        db.save_user_message(chat_id, "首次问题")
        self.assertEqual(db.get_conversation(chat_id)["title"], "手动命名")

    def test_default_text_first_title_is_not_renamed_later(self):
        chat_id = uuid4()
        db.save_user_message(chat_id, "新建聊天")
        db.save_user_message(chat_id, "不能覆盖第一个标题")
        self.assertEqual(db.get_conversation(chat_id)["title"], "新建聊天")

    def test_messages_and_tool_metadata_roundtrip(self):
        chat_id = uuid4()
        steps = [{"name": "get_stock", "arguments": '{"商品":"键盘"}',
                  "result": {"stock": 12}, "duration_ms": 0}]
        db.save_user_message(chat_id, "问题")
        db.save_assistant_message(chat_id, "**回答**", steps)
        messages = db.get_conversation(chat_id)["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertEqual(messages[-1]["tool_steps"], steps)

    def test_separate_conversations_and_missing_id(self):
        first, second = uuid4(), uuid4()
        db.save_user_message(first, "A")
        db.save_user_message(second, "B")
        self.assertEqual(db.get_conversation(first)["messages"][0]["content"], "A")
        self.assertIsNone(db.get_conversation(uuid4()))

    def test_recent_history_order_and_no_database_deletion(self):
        chat_id = uuid4()
        for number in range(15):
            db.save_user_message(chat_id, f"问题{number}")
            db.save_assistant_message(chat_id, f"回答{number}", [])
        recent = db.get_recent_messages(chat_id)
        self.assertLessEqual(len(recent), 21)
        self.assertEqual(recent[0]["role"], "user")
        self.assertEqual(recent[-1]["content"], "回答14")
        self.assertEqual(len(db.get_conversation(chat_id)["messages"]), 30)

    def test_list_sorted_by_updated_timestamp(self):
        first, second = uuid4(), uuid4()
        with patch.object(db, "now", side_effect=["2026-01-01", "2026-01-02", "2026-01-03"]):
            db.create_conversation(first)
            db.create_conversation(second)
            db.rename_conversation(first, "最新")
        self.assertEqual([c["id"] for c in db.list_conversations()], [str(first), str(second)])

    def test_delete_only_target_and_unknown_returns_false(self):
        first, second = uuid4(), uuid4()
        db.save_user_message(first, "A")
        db.save_assistant_message(first, "答", [])
        db.save_user_message(second, "B")
        self.assertTrue(db.delete_conversation(first))
        self.assertIsNone(db.get_conversation(first))
        self.assertIsNotNone(db.get_conversation(second))
        self.assertFalse(db.delete_conversation(first))

    def test_sql_like_title_is_plain_data(self):
        chat_id = uuid4()
        db.create_conversation(chat_id)
        title = "x'; DROP TABLE messages; --"
        db.rename_conversation(chat_id, title)
        db.save_user_message(chat_id, "仍然可以写入")
        self.assertEqual(db.get_conversation(chat_id)["title"], title)

    def test_concurrent_writes_do_not_lose_messages(self):
        chat_id = uuid4()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda n: db.save_user_message(chat_id, f"问题{n}"), range(8)))
        self.assertEqual(len(db.get_conversation(chat_id)["messages"]), 8)


class TestMarkdownRecords(SandboxCase):
    def test_header_only_once_and_unicode_preserved(self):
        chat_id = uuid4()
        chat_records.append_record(chat_id, "用户", "你好")
        chat_records.append_record(chat_id, "助手", "**回答**")
        text = (self.records / str(chat_id) / "chat.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("# 聊天记录\n"), 1)
        self.assertIn("你好", text)
        self.assertIn("**回答**", text)

    def test_concurrent_append_keeps_every_record(self):
        chat_id = uuid4()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda n: chat_records.append_record(chat_id, "工具", f"[记录{n}]"), range(8)))
        text = (self.records / str(chat_id) / "chat.md").read_text(encoding="utf-8")
        for number in range(8):
            self.assertEqual(text.count(f"[记录{number}]"), 1)

