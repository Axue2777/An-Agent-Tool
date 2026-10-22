import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import dev


class TestDevLauncher(unittest.TestCase):
    # 新解释器中验证导入安全；即使回归，也不允许读取 .env 或启动服务。
    def test_import_has_no_startup_side_effects(self):
        probe = """
from unittest.mock import patch
with patch("dotenv.dotenv_values", side_effect=AssertionError("导入时读取了配置")), \\
     patch("subprocess.Popen", side_effect=AssertionError("导入时启动了进程")):
    import dev
print("SAFE_IMPORT")
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", probe],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "SAFE_IMPORT")

    # 模拟默认端口被占用，应该继续寻找下一个端口。
    def test_busy_port_is_skipped(self):
        with patch("dev.socket.socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.bind.side_effect = [OSError("端口被占用"), None]
            self.assertEqual(dev.find_available_port(8000), 8001)

    # 即使端口空闲，也不能选中明确排除的端口。
    def test_excluded_port_is_skipped(self):
        with patch("dev.socket.socket") as factory:
            result = dev.find_available_port(8000, excluded=(8000,))
            self.assertEqual(result, 8001)
            sock = factory.return_value.__enter__.return_value
            sock.bind.assert_called_once_with(("127.0.0.1", 8001))

    # 模拟服务返回正确标识，全程不请求真实接口。
    def test_health_check_accepts_expected_service(self):
        worker = Mock()
        worker.poll.return_value = None
        with patch("dev.build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"service":"agent-workspace"}'
            dev.wait_until_ready("http://127.0.0.1:8000/health", [worker])

    # 进程提前退出时应该报错，不能一直等待或误报成功。
    def test_exited_process_is_reported(self):
        worker = Mock()
        worker.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "提前退出"):
            dev.wait_until_ready("http://127.0.0.1:8000/health", [worker])
