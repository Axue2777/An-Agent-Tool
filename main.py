import os
import httpx
import uvicorn
import traceback
import json
from queue import Queue, Empty
from threading import Thread, Event, Lock
from fastapi.responses import StreamingResponse
from fastapi import FastAPI,HTTPException,UploadFile, File
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from uuid import UUID, uuid4
from chat_records import append_record,RECORDS
from agent_tools import run_agent
from fastapi.responses import FileResponse
from pathlib import Path
from dotenv import load_dotenv
from document_parser import parse_document
from starlette.concurrency import run_in_threadpool
from database import (
    init_db,
    save_user_message,
    save_assistant_message,
    list_conversations,
    get_conversation,
    create_conversation,
    rename_conversation,
    delete_conversation,
    get_recent_messages,
)

app = FastAPI()

# 本地示例在应用导入时创建所需表，重新加载不会清空数据。
init_db()

# 保存正在运行的任务：任务编号对应一个停止信号。
active_tasks: dict[str, Event] = {}

# 保护任务列表，避免不同线程同时修改。
task_lock = Lock()


# 使用专门的异常区分“用户停止”和“程序出错”。
class TaskCancelled(Exception):
    pass


# 生成过程中主动检查；收到停止信号后退出后续执行。
def check_cancelled(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelled("用户停止生成")


# 前端点击停止后，调用此接口设置对应任务的停止信号。
@app.post("/chat/tasks/{task_id}/cancel", tags=["AI操作"], status_code=202)
def cancel_chat_task(task_id: UUID):
    with task_lock:
        stop_event = active_tasks.get(str(task_id))
        if stop_event is None:
            return {"status": "not_running"}

        stop_event.set()

    # 表示已经发出信号，不表示后台线程此刻已经退出。
    return {"status": "cancelling"}

# 从 main.py 所在目录加载配置，不受终端所在位置影响。
# 以项目 .env 配置为准，覆盖终端中可能残留的旧密钥。
load_dotenv(
    Path(__file__).resolve().parent / ".env",
    override=True,
)

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
    http_client=httpx.Client(trust_env=False, timeout=30.0),
    max_retries=0,
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)

    # 后端独立拒绝纯空白消息，正常内容保持原样，避免破坏 Markdown 缩进。
    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息内容不能为空白")
        return value


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    conversation_id: UUID | None = None
    # 默认保持原来的搜索能力，前端可以按请求关闭。
    web_search: bool = True

# 历史列表只返回会话信息，避免每次加载所有消息。
@app.get("/chat/history", tags=["聊天历史"])
def history_list():
    return {"conversations": list_conversations()}


# 用户选中一段聊天后，再取出它的完整消息。
@app.get("/chat/history/{conversation_id}", tags=["聊天历史"])
def history_detail(conversation_id: UUID):
    result = get_conversation(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="聊天记录不存在")
    return result

# 下载当前会话的原始 Markdown，包含聊天和工具执行记录。
@app.get("/chat/history/{conversation_id}/export", tags=["聊天历史"])
def export_chat(conversation_id: UUID):
    if get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="聊天不存在")

    path = RECORDS / str(conversation_id) / "chat.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="暂无可导出的记录")

    return FileResponse(
        path, media_type="text/markdown",
        filename=f"chat-{conversation_id}.md",
    )

# 限制重命名请求的标题长度。
class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)


# 新建会话，编号由后端生成，直接返回空会话详情。
@app.post("/chat/history", tags=["聊天历史"], status_code=201)
def create_chat():
    return create_conversation(uuid4())


# 更新指定会话的标题。
@app.patch("/chat/history/{conversation_id}", tags=["聊天历史"])
def rename_chat(conversation_id: UUID, request: RenameChatRequest):
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")
    if not rename_conversation(conversation_id, title):
        raise HTTPException(status_code=404, detail="聊天记录不存在")
    return {"id": str(conversation_id), "title": title}


# 删除数据库中的会话和消息，保留磁盘上的 Markdown 文件。
@app.delete("/chat/history/{conversation_id}", tags=["聊天历史"])
def delete_chat(conversation_id: UUID):
    if not delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="聊天记录不存在")
    return {"deleted": True, "id": str(conversation_id)}

# 普通 HTTP 请求不传回调；事件流接口通过它接收进度。
# 统一处理聊天、工具调用和 Markdown 记录，供两个接口复用。
def process_chat(request: ChatRequest, on_event=None, stop_event=None):
    if request.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="最后一条必须是用户消息")
    conversation_id = request.conversation_id or uuid4()
    # 只追加本轮最新消息，不将浏览器提交的整段历史重复写库。
    save_user_message(conversation_id, request.messages[-1].content)
    append_record(conversation_id, "用户", request.messages[-1].content)
    # 最新用户消息在上方已经入库，这里读取时自然包含本次问题。
    history = get_recent_messages(conversation_id)
    # 暂存当前轮文字，取消时只写入 Markdown，不作为完整回答入库。
    partial_reply = []

    # 统一处理生成事件，并在安全检查点响应停止信号。
    def emit(event):
        event_type = event["type"]
        # 工具已执行完时，先允许它记录真实结果，再停止后续步骤。
        if event_type != "tool_end":
            check_cancelled(stop_event)
        if event_type in {"round_start", "tool_start"}:
            partial_reply.clear()
        elif event_type == "text_delta":
            partial_reply.append(event["text"])
        # checkpoint 仅供后端检查，不发送到网页。
        if event_type != "checkpoint" and on_event:
            on_event(event)
    try:
      # 接收最终回答和本轮执行步骤。
        reply, tool_steps = run_agent(
            client, history, conversation_id,
            on_event=emit,
            web_search=request.web_search,
        )
        # 完整回答入库前，再检查一次是否收到停止请求。
        check_cancelled(stop_event)
    except Exception as error:
        # 用户取消不当作服务器错误，也不保存成完整助手回答。
        if isinstance(error, TaskCancelled) or (
            stop_event is not None and stop_event.is_set()
        ):
            if partial_reply:
                append_record(
                    conversation_id, "助手（已停止，内容不完整）",
                    "".join(partial_reply),
                )
            append_record(conversation_id, "状态", "用户停止生成")
            # 保存停止提示，刷新后仍显示；不保存为完整生成结果。
            save_assistant_message(conversation_id, "对话内容被主动停止", [])
            append_record(conversation_id, "助手", "对话内容被主动停止")
            raise TaskCancelled("用户停止生成") from error
        # 将具体出错位置打印到后端终端，便于定位。
        traceback.print_exc()

        # Markdown 记录异常类型，网页继续显示简洁提示。
        append_record(
            conversation_id,
            "错误",
            f"Agent 执行失败：{type(error).__name__}",
        )
        raise HTTPException(
            status_code=502,
            detail="Agent 执行失败，请查看后端终端",
        ) from error
    # Agent 已成功返回，再保存完整回答和工具步骤。
    save_assistant_message(conversation_id, reply, tool_steps)
    append_record(conversation_id, "助手", reply)
        # 工具步骤单独返回，方便前端展示。
    return {
        "reply": reply,
        "conversation_id": str(conversation_id),
        "tool_steps": tool_steps,
    }

# 普通聊天接口：等待任务完成后，一次返回完整结果。
@app.post("/chat", tags=["AI操作"])
def chat(request: ChatRequest):
    return process_chat(request)

# 根据合法的会话编号和文件编号下载报告。
@app.get("/chat/files/{conversation_id}/{file_id}",tags=["AI操作"])
def download_report(conversation_id: UUID, file_id: UUID):
    path = RECORDS / str(conversation_id) / "artifacts" / f"{file_id}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="报告不存在")
    return FileResponse(path, media_type="text/markdown", filename="report.md")

if __name__ == "__main__":
    # 开发时监视项目文件，保存后自动重载，避免继续运行旧版工具代码。
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

# 接收当前聊天的文本附件，限制格式、大小和编码。
@app.post("/chat/upload/{conversation_id}",tags=["AI操作"])
async def upload_file(
    conversation_id: UUID,
    file: UploadFile = File(...),
):
    try:
        filename = file.filename or "attachment.txt"
        suffix = Path(filename).suffix.lower()

        # 第一版只支持 UTF-8 编码的文本和 Markdown。
                # 扩展格式，限制上传文件不超过 10 MB。
        if suffix not in {".txt", ".md", ".pdf", ".docx",".png",".jpg",".jpeg"}:
            raise HTTPException(status_code=400, detail="只支持 txt、md、pdf、docx")
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件不能超过 10 MB")

        # 在线程中解析，避免阻塞其他异步请求。
        try:
            text = await run_in_threadpool(parse_document, content, suffix)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail="解析失败，请检查文件是否完整")
        if not text.strip():
            raise HTTPException(status_code=400, detail="没有提取到可用文字")

        # 使用程序生成的编号保存，避免同名覆盖和文件路径问题。
        file_id = uuid4()
        folder = RECORDS / str(conversation_id) / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{file_id}.txt"
        path.write_text(text, encoding="utf-8")

        # 聊天记录中留下上传事件，正文单独保存。
        append_record(conversation_id, "上传附件", f"名称：{filename}\n\n编号：{file_id}")
        return {
            "file_id": str(file_id),
            "filename": filename,
            "characters": len(text),
        }
    finally:
        # 无论成功还是失败，都关闭上传文件。
        await file.close()

# 用事件流返回进度；最终结果仍包含回答、会话编号和执行记录。
@app.post("/chat/stream", tags=["AI操作"])
def stream_chat(request: ChatRequest):
    events = Queue()
    task_id = str(uuid4())
    stop_event = Event()

    # 后台执行聊天，分别报告完成、主动取消和运行错误。
    def worker():
        try:
            result = process_chat(
                request,
                on_event=events.put,
                stop_event=stop_event,
            )
            events.put({"type": "done", "data": result})
        except TaskCancelled:
            events.put({"type": "cancelled", "task_id": task_id})
        except Exception:
            events.put({"type": "error", "message": "任务失败，请查看后端终端"})
        finally:
            with task_lock:
                active_tasks.pop(task_id, None)
            events.put(None)

    # 登记任务，再把编号通过 start 事件交给前端。
    def generate():
        with task_lock:
            active_tasks[task_id] = stop_event
        try:
            Thread(target=worker, daemon=True).start()
            start = {"type": "start", "task_id": task_id}
            yield f"data: {json.dumps(start, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = events.get(timeout=10)
                except Empty:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            # 生成器退出时发出停止信号，并清理登记。
            stop_event.set()
            with task_lock:
                active_tasks.pop(task_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
