"""通过 Node 内置测试器验证前端流解析，不需要启动网页。"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestFrontendStream(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "未安装 Node，前端解析检查未执行")
    def test_node_stream_suite(self):
        result = subprocess.run(
            ["node", "--test", "tests/test_chat_stream.mjs"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=45,
        )
        artifacts = ROOT / "tests" / "_artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "frontend-stream.tap").write_text(
            result.stdout + result.stderr, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

