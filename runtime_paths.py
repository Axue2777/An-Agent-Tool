import os
import sys
from pathlib import Path

# 程序资源：源码运行时是项目目录，打包后是包内资源目录。
RESOURCE_ROOT = Path(__file__).resolve().parent

# 打包后把可写数据放到用户目录，避免依赖安装目录或临时目录。
if getattr(sys, "frozen", False):
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or Path.home() / "AppData" / "Local"
    )
    DATA_ROOT = local_app_data / "AgentWorkspace"
else:
    DATA_ROOT = RESOURCE_ROOT

DB_PATH = DATA_ROOT / "agent.db"
RECORDS = DATA_ROOT / "records"
ENV_PATH = DATA_ROOT / ".env"