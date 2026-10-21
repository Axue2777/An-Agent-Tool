"""测试隔离：临时数据库、临时文件，以及不读取真实密钥的 FastAPI 应用。"""
import importlib.util
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import chat_records
import database
import file_tools
import report_tools
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.records = self.root / "records"
        self.records.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(database, "DB_PATH", self.root / "agent.db"))
        for module in (chat_records, file_tools, report_tools):
            self.stack.enter_context(patch.object(module, "RECORDS", self.records))
        # 真实 HTTPTransport 被禁用；MockTransport 和 TestClient 不受影响。
        self.stack.enter_context(patch(
            "httpx.HTTPTransport.handle_request",
            side_effect=AssertionError("测试禁止访问真实网络"),
        ))
        database.init_db()

    def attachment(self, chat_id, text, file_id=None):
        file_id = file_id or uuid4()
        folder = self.records / str(chat_id) / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{file_id}.txt").write_text(text, encoding="utf-8")
        return file_id


class AppCase(SandboxCase):
    def setUp(self):
        super().setUp()
        # 导入 main 时先拦截环境加载、OpenAI 构造和数据库位置。
        name = f"_agent_checks_main_{uuid4().hex}"
        spec = importlib.util.spec_from_file_location(name, ROOT / "main.py")
        self.main = importlib.util.module_from_spec(spec)
        self.stack.enter_context(patch.dict(sys.modules, {name: self.main}))
        with (
            patch("dotenv.load_dotenv", return_value=False),
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-not-a-real-key"}),
            patch("openai.OpenAI") as constructor,
        ):
            spec.loader.exec_module(self.main)
            # main 构造参数中的 HTTP 客户端没有发起请求，及时关闭资源。
            constructor.call_args.kwargs["http_client"].close()
        self.agent = self.stack.enter_context(patch.object(
            self.main, "run_agent", return_value=("测试回答", []),
        ))
        self.stack.enter_context(patch.object(self.main.traceback, "print_exc"))
        self.api = self.stack.enter_context(TestClient(
            self.main.app, raise_server_exceptions=False,
        ))
        self.chat_id = uuid4()

    def request(self, text="你好", **extra):
        return {"messages": [{"role": "user", "content": text}],
                "conversation_id": str(self.chat_id), **extra}

    def events(self, response):
        import json
        return [json.loads(line[5:].strip())
                for line in response.text.splitlines() if line.startswith("data:")]

