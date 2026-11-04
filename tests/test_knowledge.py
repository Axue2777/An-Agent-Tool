"""会话资料库隔离、库存 CSV、角色和接口测试；不访问付费模型。"""
import unittest
from uuid import uuid4

import database
from knowledge_store import lookup_inventory, search_chunks
from tests.support import AppCase


class TestKnowledgeApi(AppCase):
    def test_custom_title_and_persona_reach_agent(self):
        response = self.api.post("/chat/history", json={
            "title": "店员助手", "persona": "回答时保持简洁",
        })
        self.assertEqual(response.status_code, 201)
        chat = response.json()
        self.assertEqual(chat["title"], "店员助手")
        self.assertEqual(chat["persona"], "回答时保持简洁")
        self.chat_id = chat["id"]
        self.assertEqual(self.api.post("/chat", json=self.request("你好")).status_code, 200)
        self.assertEqual(self.agent.call_args.kwargs["persona"], "回答时保持简洁")
        self.assertEqual(database.get_conversation(self.chat_id)["title"], "店员助手")

    def test_inventory_zero_unknown_and_conversation_isolation(self):
        first = uuid4()
        second = uuid4()
        database.create_conversation(first)
        database.create_conversation(second)
        response = self.api.post(f"/chat/history/{first}/knowledge", files={
            "file": ("stock.csv", "product_name,stock\n机械键盘,12\n无线鼠标,0\n".encode()),
        })
        self.assertEqual(response.status_code, 201)
        file_id = response.json()["id"]
        self.assertEqual(lookup_inventory(first, "机械键盘")["stock"], 12)
        self.assertEqual(lookup_inventory(first, "无线鼠标")["stock"], 0)
        self.assertFalse(lookup_inventory(second, "机械键盘")["found"])
        self.assertFalse(lookup_inventory(first, "不存在")["found"])
        self.assertEqual(len(self.api.get(f"/chat/history/{first}/knowledge").json()["files"]), 1)
        self.assertEqual(self.api.get(f"/chat/history/{second}/knowledge").json()["files"], [])
        self.assertEqual(self.api.delete(f"/chat/history/{second}/knowledge/{file_id}").status_code, 404)
        self.assertEqual(self.api.delete(f"/chat/history/{first}/knowledge/{file_id}").status_code, 200)
        self.assertFalse(lookup_inventory(first, "机械键盘")["found"])

    def test_document_search_and_delete(self):
        chat_id = uuid4()
        database.create_conversation(chat_id)
        response = self.api.post(f"/chat/history/{chat_id}/knowledge", files={
            "file": ("guide.md", "Vue 计算属性会缓存结果。".encode(), "text/markdown"),
        })
        self.assertEqual(response.status_code, 201)
        file_id = response.json()["id"]
        matches = search_chunks(chat_id, "计算属性")["matches"]
        self.assertEqual(matches[0]["filename"], "guide.md")
        self.assertEqual(search_chunks(uuid4(), "计算属性")["matches"], [])
        self.api.delete(f"/chat/history/{chat_id}/knowledge/{file_id}")
        self.assertEqual(search_chunks(chat_id, "计算属性")["matches"], [])

    def test_invalid_csv_does_not_save_partial_data(self):
        chat_id = uuid4()
        database.create_conversation(chat_id)
        response = self.api.post(f"/chat/history/{chat_id}/knowledge", files={
            "file": ("bad.csv", b"product_name,stock\nkeyboard,12\nmouse,-1\n"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.api.get(f"/chat/history/{chat_id}/knowledge").json()["files"], [])
        self.assertFalse(lookup_inventory(chat_id, "keyboard")["found"])


if __name__ == "__main__":
    unittest.main()
