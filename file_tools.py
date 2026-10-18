from uuid import UUID
from chat_records import RECORDS

# 通过附件编号和字符位置，分段读取当前会话的资料。
READ_ATTACHMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "read_attachment",
        "description": "分段读取附件，每次最多返回 8000 字符。首次 offset 为 0。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "读取起点，继续读取时使用上次返回的 next_offset",
                },
            },
            "required": ["file_id"],
            "additionalProperties": False,
        },
    },
}


# 返回当前片段及下一段位置，明确区分“本段结束”和“全文结束”。
def read_attachment(file_id, conversation_id, offset=0):
    if not isinstance(file_id, str):
        raise ValueError("附件编号必须是字符串")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset 必须是非负整数")

    attachment_id = UUID(file_id)
    path = (
        RECORDS / str(conversation_id)
        / "attachments" / f"{attachment_id}.txt"
    )
    if not path.is_file():
        return {"error": "当前会话中没有这个附件"}

    text = path.read_text(encoding="utf-8")
    if offset >= len(text):
        return {"error": "读取位置超出文件范围"}

    end = min(offset + 8000, len(text))
    return {
        "file_id": str(attachment_id),
        "content": text[offset:end],
        "offset": offset,
        "total_characters": len(text),
        "next_offset": end if end < len(text) else None,
        "finished": end == len(text),
    }