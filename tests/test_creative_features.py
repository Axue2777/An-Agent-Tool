"""新能力的隔离检查：不访问真实智谱服务，也不写入用户记录。"""
from io import BytesIO
from types import SimpleNamespace as N
from unittest.mock import patch
from uuid import uuid4

import httpx
from PIL import Image
from pptx import Presentation

import creative_tools
import database
from api_settings import Settings
from model_stream import request_stream_message
from tests.support import AppCase, SandboxCase


def sample_png():
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "skyblue").save(buffer, format="PNG")
    return buffer.getvalue()


class TestCreativeApi(AppCase):
    def test_persona_updates_only_selected_chat(self):
        database.create_conversation(self.chat_id)
        other = uuid4()
        database.create_conversation(other)
        result = self.api.patch(f"/chat/history/{self.chat_id}/assistant",
                                json={"persona": "耐心的老师"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(database.get_conversation(self.chat_id)["persona"], "耐心的老师")
        self.assertEqual(database.get_conversation(other)["persona"], "")

    def test_image_without_ocr_text_is_saved_and_listed(self):
        database.create_conversation(self.chat_id)
        with patch.object(self.main, "parse_document", return_value=""):
            response = self.api.post(f"/chat/upload/{self.chat_id}",
                                     files={"file": ("风景.png", sample_png(), "image/png")})
        self.assertEqual(response.status_code, 200)
        item = response.json()
        self.assertEqual(item["kind"], "image")
        self.assertTrue((self.records / str(self.chat_id) / "attachments" /
                         f"{item['file_id']}.png").is_file())
        listing = self.api.get(f"/chat/history/{self.chat_id}/files").json()
        self.assertEqual(listing["attachments"][0]["filename"], "风景.png")

    def test_vision_uses_only_selected_file_and_records_model(self):
        database.create_conversation(self.chat_id)
        image_id = uuid4()
        folder = self.records / str(self.chat_id) / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{image_id}.png").write_bytes(sample_png())
        database.save_attachment(self.chat_id, image_id, "风景.png", "image")
        with patch.object(self.main, "load_settings", return_value=Settings(zhipu_key="fake")), \
             patch.object(self.main, "analyze_image", return_value={
                 "description": "一片蓝天", "provider": "zhipu", "model": "glm-5.3-flash",
             }) as analyze:
            response = self.api.post(f"/chat/history/{self.chat_id}/analyze-image",
                                     json={"file_id": str(image_id), "question": "有什么？"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(analyze.call_args.args[0], str(image_id))
        answer = database.get_conversation(self.chat_id)["messages"][-1]
        self.assertEqual((answer["provider"], answer["model"]), ("zhipu", "glm-5.3-flash"))
        denied = self.api.post(f"/chat/history/{self.chat_id}/analyze-image",
                               json={"file_id": str(uuid4()), "question": "有什么？"})
        self.assertEqual(denied.status_code, 404)


class TestCreativeFiles(SandboxCase):
    def test_image_busy_is_reported_without_crashing_chat(self):
        def handler(request):
            return httpx.Response(429, json={"error": {"code": 1305}})
        actual_client = httpx.Client
        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return actual_client(*args, **kwargs)
        with patch.object(creative_tools.httpx, "Client", side_effect=client_factory):
            result = creative_tools.generate_image("蓝天", uuid4(), "fake-key")
        self.assertIn("HTTP 429", result["error"])
        self.assertIn("1305", result["error"])

    def test_presentation_is_openable_and_isolated(self):
        with patch.object(creative_tools, "RECORDS", self.records):
            result = creative_tools.save_presentation("学习计划", [
                {"title": "第一天", "bullets": ["Vue 基础", "组件"]},
                {"title": "第二天", "bullets": ["接口调用"]},
            ], uuid4())
        file_id = result["download_url"].split("/")[-1]
        chat_id = result["download_url"].split("/")[-2]
        deck = Presentation(self.records / chat_id / "artifacts" / f"{file_id}.pptx")
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].shapes[0].text, "第一天")

    def test_image_generation_saves_real_image_and_blocks_other_hosts(self):
        image_bytes = sample_png()
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"data": [{"url": "https://sfile.chatglm.cn/pic.png"}]})
            return httpx.Response(200, content=image_bytes, headers={"content-type": "image/png"})
        actual_client = httpx.Client
        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return actual_client(*args, **kwargs)
        with patch.object(creative_tools, "RECORDS", self.records), \
             patch.object(creative_tools.httpx, "Client", side_effect=client_factory):
            result = creative_tools.generate_image("蓝天", uuid4(), "fake-key")
        self.assertIn("image_url", result)
        self.assertEqual(len(requests), 2)
        self.assertTrue((self.records / result["image_url"].split("/")[-2] / "artifacts" /
                         f"{result['image_url'].split('/')[-1]}.png").is_file())


class TestThinkingStream(SandboxCase):
    def test_reasoning_is_separate_and_kept_for_tool_followup(self):
        class Stream:
            def __enter__(self):
                return iter([
                    N(choices=[N(delta=N(content=None, reasoning_content="先分析", tool_calls=None),
                                 finish_reason=None)]),
                    N(choices=[N(delta=N(content="答案", reasoning_content=None, tool_calls=None),
                                 finish_reason="stop")]),
                ])
            def __exit__(self, *args):
                pass
        client = N(chat=N(completions=N(create=lambda **kwargs: Stream())))
        events = []
        message = request_stream_message(client, [], [], "none", events.append,
                                         provider="deepseek", thinking=True)
        self.assertEqual(message.content, "答案")
        self.assertEqual(message.model_dump().get("reasoning_content"), "先分析")
        self.assertEqual([event["text"] for event in events
                          if event["type"] == "reasoning_delta"], ["先分析"])
