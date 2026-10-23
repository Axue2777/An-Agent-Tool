import os
import shutil
import socket
import subprocess
import sys
import time
import json
import argparse
from urllib.request import build_opener, ProxyHandler
from pathlib import Path
from importlib.util import find_spec

# 始终按脚本位置查找文件，不受终端当前目录影响。
ROOT = Path(__file__).resolve().parent

# 从首选端口开始寻找，最多尝试附近的 100 个端口。
def find_available_port(preferred, excluded=()):
    for port in range(preferred, min(preferred + 100, 65536)):
        if port in excluded:
            continue

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue

        # 离开 with 后释放端口，供后续服务使用。
        return port

    raise SystemExit(f"端口 {preferred} 附近没有可用端口。")

# 等待健康接口响应；进程提前退出或等待超时就报错。
def wait_until_ready(url, processes, timeout=45):
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))

    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("启动进程提前退出，请查看上方日志。")
        try:
            with opener.open(url, timeout=1) as response:
                data = json.loads(response.read(1024))
                if isinstance(data, dict) and data.get("service") == "agent-workspace":
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.3)

    raise RuntimeError(f"等待服务就绪超时：{url}")

def main():
    """检查本机配置并管理前后端进程；导入模块时不执行。"""

    # 先解析参数，后面的启动逻辑才能使用 args。
    parser = argparse.ArgumentParser(description="启动 Agent 开发环境")
    parser.add_argument("--desktop", action="store_true", help="打开桌面窗口")
    args = parser.parse_args()

    electron_exe = ROOT / "node_modules/electron/dist/electron.exe"
    if args.desktop and not electron_exe.is_file():
        raise SystemExit("未安装 Electron，请在项目根目录安装。")

    # 原有的依赖检查、配置检查和启动代码继续放在这里，不要删除。
    # 先检查后端依赖，避免缺包时直接出现长串报错。
    modules = (
        "fastapi", "uvicorn", "openai", "httpx", "pydantic",
        "dotenv", "multipart", "pypdf", "docx", "PIL",
        "pytesseract", "pypdfium2", "tzdata",
    )
    missing = [name for name in modules if find_spec(name) is None]
    if missing:
        raise SystemExit(f"缺少后端依赖：{', '.join(missing)}")

    # Node 用于运行 Vue；Vite 文件存在表示已安装前端工具。
    if not shutil.which("node"):
        raise SystemExit("未找到 Node.js，安装后请重新打开 VS Code。")
    if not (ROOT / "fronted/node_modules/vite/bin/vite.js").is_file():
        raise SystemExit("前端依赖未安装，请运行：npm.cmd ci --prefix fronted")

    # 使用现有 dotenv 解析配置；与后端一致，文件配置优先。
    from dotenv import dotenv_values

    settings = dict(os.environ)
    for name, value in dotenv_values(ROOT / ".env").items():
        if value is not None:
            settings[name] = value

    # 只检查是否填写，不打印密钥，也不请求收费接口。
    if not (settings.get("DEEPSEEK_API_KEY") or "").strip():
        raise SystemExit("未配置 DEEPSEEK_API_KEY，请填写并保存根目录 .env。")
    if not (settings.get("ZHIPU_API_KEY") or "").strip():
        print("提醒：未配置智谱密钥，联网搜索不可用，普通聊天不受影响。")




    backend_port = find_available_port(8000)
    frontend_port = find_available_port(5173, excluded=(backend_port,))

    # 后续启动的 Vite 会继承这个变量，不需要手动修改代理端口。
    os.environ["AGENT_API_TARGET"] = f"http://127.0.0.1:{backend_port}"

    print(f"计划使用后端地址：http://127.0.0.1:{backend_port}")
    print(f"计划使用前端地址：http://127.0.0.1:{frontend_port}")

    # 用参数列表启动，项目路径包含中文或空格时也不需要手动拼接引号。
    commands = [
        (
            [sys.executable, "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(backend_port), "--reload"],
            ROOT,
        ),
        (
            [shutil.which("node"),
             str(ROOT / "fronted/node_modules/vite/bin/vite.js"),
             "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
            ROOT / "fronted",
        ),
    ]

    processes = []
    desktop_process = None
    try:
        for command, directory in commands:
            # Windows 独立进程组，让主脚本统一负责退出清理。
            process = subprocess.Popen(
                command,
                cwd=directory,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            processes.append(process)

        # 先确认后端，再通过前端代理确认整条请求链路。
        wait_until_ready(f"http://127.0.0.1:{backend_port}/health", processes)
        wait_until_ready(f"http://127.0.0.1:{frontend_port}/health", processes)
                # 服务就绪后再打开窗口，并传入本次实际端口。
        if args.desktop:
            desktop_env = os.environ.copy()
            desktop_env["AGENT_FRONTEND_URL"] = f"http://127.0.0.1:{frontend_port}"
            desktop_env.pop("ELECTRON_RUN_AS_NODE", None)
            desktop_process = subprocess.Popen(
                [str(electron_exe), str(ROOT)],
                cwd=ROOT, env=desktop_env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            processes.append(desktop_process)
        print(f"启动就绪：http://127.0.0.1:{frontend_port}")
        print("按 Ctrl+C 停止本次启动的前后端。")

        # 任意启动进程退出时，结束本次运行并清理另一个进程。
        while True:
            # 关闭桌面窗口属于正常退出，随后进入 finally 清理。
            if desktop_process is not None and desktop_process.poll() is not None:
                if desktop_process.returncode != 0:
                    raise RuntimeError(f"桌面进程异常退出：{desktop_process.returncode}")
                break
            # 前后端意外退出时，仍按启动失败处理。
            if any(p.poll() is not None for p in processes if p is not desktop_process):
                raise RuntimeError("前后端进程已退出，请查看上方日志。")
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n正在关闭本次启动的服务……")
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"启动失败：{error}")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                # Windows 按本次 PID 关闭进程树，包括热重载产生的子进程。
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                )
                process.wait()
        print("本次启动的进程已清理。")

# 只有直接运行文件时才启动服务。
if __name__ == "__main__":
    main()