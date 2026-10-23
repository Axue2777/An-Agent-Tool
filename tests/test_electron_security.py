"""由 Python 测试入口调用 Node，验证桌面安全规则。"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestElectronSecurity(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "未安装 Node，无法检查桌面规则")
    def test_node_security_suite(self):
        # 参数列表不经过命令行字符串拼接，兼容中文和空格路径。
        result = subprocess.run(
            ["node", "--test", "tests/test_electron_security.cjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )

        # 保存 Node 的完整结果，GitHub 会随其他报告一起上传。
        artifacts = ROOT / "tests" / "_artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "electron-security.tap").write_text(
            result.stdout + result.stderr, encoding="utf-8",
        )

        # Node 失败时，Python 测试也必须失败。
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)