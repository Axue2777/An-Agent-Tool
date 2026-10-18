from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import UUID
from zoneinfo import ZoneInfo

RECORDS = Path(__file__).resolve().parent / "records"
print("聊天记录保存位置：", RECORDS)
lock = Lock()


def append_record(conversation_id: UUID, role: str, content: str):
    folder = RECORDS / str(conversation_id)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

    with lock:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "chat.md"
        with path.open("a", encoding="utf-8") as file:
            if file.tell() == 0:
                file.write(f"# 聊天记录\n\n会话编号：{conversation_id}\n")
            file.write(f"\n## {role}｜{now}\n\n{content}\n")