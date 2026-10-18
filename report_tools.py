from uuid import uuid4
from chat_records import RECORDS

# 向模型声明报告工具，由模型编写 Markdown 正文。
REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "save_report",
        "description": "将 Markdown 正文保存为可下载的报告文件。",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
    },
}


# 按会话保存成果，随机文件名避免覆盖之前的报告。
def save_report(content, conversation_id):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("报告正文不能为空")
    if len(content) > 100000:
        raise ValueError("报告正文过长")
    file_id = uuid4()
    folder = RECORDS / str(conversation_id) / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{file_id}.md"
    path.write_text(content, encoding="utf-8")
    return {"download_url": f"/chat/files/{conversation_id}/{file_id}"}