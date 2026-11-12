import os
import httpx
import uvicorn
import traceback
import json
from queue import Queue, Empty
from runtime_paths import ENV_PATH, RESOURCE_ROOT
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
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv
from document_parser import parse_document, DOCUMENT_SUFFIXES
from knowledge_store import add_document, add_inventory_csv, list_files, delete_file
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from database import (
    init_db,
    save_user_message,
    mark_user_message_failed,
    save_assistant_message,
    list_conversations,
    get_conversation,
    create_conversation,
    rename_conversation,
    delete_conversation,
    get_recent_messages,
    update_persona, save_attachment, list_attachments, delete_attachment,
)
from creative_tools import analyze_image
from api_settings import (
    router as settings_router,
    load_settings,
    require_chat,
    model_name,
    search_key,
    create_chat_client,
    describe_chat_error,
)

app = FastAPI()

# 设置接口必须注册在末尾的静态页面挂载之前。
app.include_router(settings_router)
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

# 只检查服务能否响应，不调用模型、不读取聊天记录。
@app.get("/health", tags=["运行状态"])
def health_check():
    return {"status": "ok", "service": "agent-workspace"}

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
# 密钥配置属于用户数据，不作为前端资源提供。
load_dotenv(ENV_PATH, override=True)


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
    # 思考模式目前仅在 DeepSeek 服务上开启；其他服务仍可正常聊天。
    thinking: bool = False
    # 附件编号单独传递，避免把技术编号塞到用户的聊天输入框。
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=20)

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

# 创建聊天时允许用户设置标题和角色；旧客户端不传请求体仍可使用。
class CreateChatRequest(BaseModel):
    title: str | None = Field(default=None, max_length=60)
    persona: str = Field(default="", max_length=2000)
    assistant_name: str = Field(default="助手", min_length=1, max_length=30)
# 限制重命名请求的标题长度。
class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)


class PersonaRequest(BaseModel):
    persona: str = Field(default="", max_length=2000)
    assistant_name: str = Field(default="助手", min_length=1, max_length=30)


# 不传请求体时仍创建普通聊天；传入标题和角色时一起保存。
@app.post("/chat/history", tags=["聊天历史"], status_code=201)
def create_chat(request: CreateChatRequest | None = None):
    request = request or CreateChatRequest()
    title = request.title.strip() if request.title else None
    name = request.assistant_name.strip()
    if not name:
        raise HTTPException(422, "助手名字不能为空")
    return create_conversation(uuid4(), title=title, persona=request.persona.strip(), assistant_name=name)


# 更新指定会话的标题。
@app.patch("/chat/history/{conversation_id}", tags=["聊天历史"])
def rename_chat(conversation_id: UUID, request: RenameChatRequest):
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")
    if not rename_conversation(conversation_id, title):
        raise HTTPException(status_code=404, detail="聊天记录不存在")
    return {"id": str(conversation_id), "title": title}


@app.patch("/chat/history/{conversation_id}/assistant", tags=["聊天历史"])
def change_assistant(conversation_id: UUID, request: PersonaRequest):
    """当前聊天的助手设定可随时修改，下一条消息起生效。"""
    persona = request.persona.strip()
    name = request.assistant_name.strip()
    if not name:
        raise HTTPException(422, "助手名字不能为空")
    if not update_persona(conversation_id, persona, name):
        raise HTTPException(404, "聊天记录不存在")
    append_record(conversation_id, "助手设定", f"名字：{name}\n\n{persona or '恢复默认助手'}")
    return {"id": str(conversation_id), "persona": persona, "assistant_name": name}


# 删除数据库中的会话和消息，保留磁盘上的 Markdown 文件。
@app.delete("/chat/history/{conversation_id}", tags=["聊天历史"])
def delete_chat(conversation_id: UUID):
    if not delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="聊天记录不存在")
    return {"deleted": True, "id": str(conversation_id)}

# 普通 HTTP 请求不传回调；事件流接口通过它接收进度。
# 统一处理聊天、工具调用和 Markdown 记录，供两个接口复用。
def process_chat(request: ChatRequest, on_event=None, stop_event=None, settings=None):
    if request.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="最后一条必须是用户消息")
    # 一轮聊天使用同一份配置，生成中途保存设置不会混用不同的密钥。
    config = settings if settings is not None else load_settings()
    require_chat(config)
    # 即使旧设置曾开启搜索，DeepSeek 会话也不能获得智谱搜索工具。
    use_search = config.provider == "zhipu" and request.web_search and config.search_enabled
    if use_search and not search_key(config):
        raise HTTPException(422, "请在 API 设置中填写智谱密钥，或关闭联网搜索。")
    conversation_id = request.conversation_id or uuid4()
    chat_info = get_conversation(conversation_id)
    persona = chat_info["persona"] if chat_info else ""
    assistant_name = chat_info["assistant_name"] if chat_info else "助手"
    # 只追加本轮最新消息，不将浏览器提交的整段历史重复写库。
    message_id = save_user_message(conversation_id, request.messages[-1].content)
    append_record(conversation_id, "用户", request.messages[-1].content)
    # 只记录服务、模型和密钥来源说明，绝不记录密钥正文。
    search_note = "关闭"
    if use_search:
        search_note = "智谱，使用聊天密钥"
    append_record(
        conversation_id,
        "API 使用说明",
        f"聊天：{config.provider} / {model_name(config)}\n\n搜索权限：{search_note}。"
        "是否实际调用搜索，以后续工具记录为准。",
    )
    # 最新用户消息在上方已经入库，这里读取时自然包含本次问题。
    thinking = request.thinking and config.provider == "deepseek"
    history = get_recent_messages(conversation_id, include_reasoning=thinking)
    allowed_files = {str(file["id"]): file for file in list_attachments(conversation_id)}
    attached = [allowed_files[str(file_id)] for file_id in request.attachment_ids
                if str(file_id) in allowed_files]
    if len(attached) != len(request.attachment_ids):
        mark_user_message_failed(message_id)
        raise HTTPException(422, "附件不属于当前聊天，请重新选择")
    # 暂存当前轮文字，取消时只写入 Markdown，不作为完整回答入库。
    partial_reply = []
    reasoning_parts = []

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
        elif event_type == "reasoning_delta":
            reasoning_parts.append(event["text"])
        # checkpoint 仅供后端检查，不发送到网页。
        if event_type != "checkpoint" and on_event:
            on_event(event)
    try:
        # 每轮新建客户端，结束或报错时自动关闭，避免复用过期配置。
        with create_chat_client(config) as current_client:
            reply, tool_steps = run_agent(
                current_client, history, conversation_id,
                on_event=emit,
                web_search=use_search,
                model=model_name(config),
                provider=config.provider,
                search_api_key=search_key(config) if use_search else "",
                persona=persona,
                assistant_name=assistant_name,
                thinking=thinking,
                image_api_key=config.zhipu_key.get_secret_value(),
                attachment_refs=attached,
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
        mark_user_message_failed(message_id)
        traceback.print_exc()

        # Markdown 记录异常类型，网页继续显示简洁提示。
        append_record(
            conversation_id,
            "错误",
            f"Agent 执行失败：{type(error).__name__}",
        )
        # 供应商超时、限流等已知错误给出可操作提示；未知内部错误仍不暴露细节。
        detail = describe_chat_error(error, config)
        raise HTTPException(
            status_code=429 if getattr(error, "status_code", None) == 429 else 502,
            detail=detail or "Agent 执行失败，请查看后端终端",
        ) from error
    # Agent 已成功返回，再保存完整回答和工具步骤。
    reasoning = "".join(reasoning_parts)
    tool_failed = any(isinstance(step.get("result"), dict)
                      and step["result"].get("error") for step in tool_steps)
    if tool_failed:
        mark_user_message_failed(message_id)
    save_assistant_message(conversation_id, reply, tool_steps,
                           reasoning=reasoning, provider=config.provider,
                           model=model_name(config), failed=tool_failed)
    if reasoning:
        append_record(conversation_id, "思考过程", reasoning)
    append_record(conversation_id, "助手", reply)
        # 工具步骤单独返回，方便前端展示。
    return {
        "reply": reply,
        "conversation_id": str(conversation_id),
        "tool_steps": tool_steps,
        "reasoning": reasoning,
        "provider": config.provider,
        "model": model_name(config),
    }

# 普通聊天接口：等待任务完成后，一次返回完整结果。
@app.post("/chat", tags=["AI操作"])
def chat(request: ChatRequest):
    return process_chat(request)

# 根据合法的会话编号和文件编号下载报告。
@app.get("/chat/files/{conversation_id}/{file_id}",tags=["AI操作"])
def download_report(conversation_id: UUID, file_id: UUID):
    folder = RECORDS / str(conversation_id) / "artifacts"
    for suffix, media, filename in (
        (".md", "text/markdown", "report.md"),
        (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "presentation.pptx"),
        (".png", "image/png", "generated.png"),
        (".jpg", "image/jpeg", "generated.jpg"),
        (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document.docx"),
        (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "spreadsheet.xlsx"),
        (".pdf", "application/pdf", "document.pdf"),
        *((f".{ext}", "text/plain; charset=utf-8", f"file.{ext}") for ext in
          ("txt", "csv", "json", "py", "js", "ts", "vue", "html", "css", "xml", "yaml", "yml", "sql")),
    ):
        path = folder / f"{file_id}{suffix}"
        if path.is_file():
            return FileResponse(path, media_type=media, filename=filename,
                                content_disposition_type="inline" if suffix in {".png", ".jpg"} else "attachment")
    raise HTTPException(status_code=404, detail="成果文件不存在")

if __name__ == "__main__":
    # 开发时监视项目文件，保存后自动重载，避免继续运行旧版工具代码。
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

# 资料库与普通附件分开：资料库可被当前聊天的 Agent 主动检索。
@app.post("/chat/history/{conversation_id}/knowledge", status_code=201)
async def upload_knowledge(conversation_id: UUID, file: UploadFile = File(...)):
    if get_conversation(conversation_id) is None:
        raise HTTPException(404, "聊天不存在")
    filename = " ".join((file.filename or "资料").split())[:120]
    suffix = Path(filename).suffix.lower()
    if suffix not in DOCUMENT_SUFFIXES - {".png", ".jpg", ".jpeg"}:
        raise HTTPException(400, "资料库不支持这种文件格式")
    try:
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(413, "资料不能超过 10 MB")
        try:
            if suffix == ".csv":
                result = await run_in_threadpool(add_inventory_csv, conversation_id, filename, content)
            else:
                text = await run_in_threadpool(parse_document, content, suffix)
                result = await run_in_threadpool(add_document, conversation_id, filename, text)
            append_record(conversation_id, "资料库上传",
                          f"名称：{filename}\n\n类型：{result['kind']}\n\n编号：{result['id']}")
            return result
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except Exception:
            raise HTTPException(400, "资料解析或保存失败") from None
    finally:
        await file.close()


@app.get("/chat/history/{conversation_id}/knowledge")
def knowledge_list(conversation_id: UUID):
    if get_conversation(conversation_id) is None:
        raise HTTPException(404, "聊天不存在")
    return {"files": list_files(conversation_id)}


@app.delete("/chat/history/{conversation_id}/knowledge/{file_id}")
def knowledge_delete(conversation_id: UUID, file_id: UUID):
    if not delete_file(conversation_id, file_id):
        raise HTTPException(404, "资料不存在")
    append_record(conversation_id, "资料库删除", f"编号：{file_id}")
    return {"deleted": True}


# 分别列出聊天附件和资料库文件，页面能展示哪些已上传。
@app.get("/chat/history/{conversation_id}/files", tags=["聊天历史"])
def conversation_files(conversation_id: UUID):
    if get_conversation(conversation_id) is None:
        raise HTTPException(404, "聊天不存在")
    return {"attachments": list_attachments(conversation_id),
            "knowledge": list_files(conversation_id)}


@app.delete("/chat/history/{conversation_id}/attachments/{file_id}", tags=["聊天历史"])
def remove_attachment(conversation_id: UUID, file_id: UUID):
    # 先验证数据库归属，再删除当前聊天的文件；不接受客户端传入文件路径。
    if not delete_attachment(conversation_id, file_id):
        raise HTTPException(404, "当前聊天没有这个附件")
    folder = RECORDS / str(conversation_id) / "attachments"
    for suffix in (".txt", ".png", ".jpg", ".jpeg"):
        (folder / f"{file_id}{suffix}").unlink(missing_ok=True)
    append_record(conversation_id, "删除附件", f"编号：{file_id}")
    return {"deleted": True}


class VisionRequest(BaseModel):
    file_id: UUID
    question: str = Field(default="请描述这张图片的内容。", min_length=1, max_length=2000)


@app.post("/chat/history/{conversation_id}/analyze-image", tags=["AI操作"])
def analyze_uploaded_image(conversation_id: UUID, request: VisionRequest):
    """仅响应页面上针对具体文件的识图按钮；用户已明确选择发送给智谱。"""
    if get_conversation(conversation_id) is None:
        raise HTTPException(404, "聊天不存在")
    selected = next((item for item in list_attachments(conversation_id)
                     if item["id"] == str(request.file_id) and item["kind"] == "image"), None)
    if selected is None:
        raise HTTPException(404, "当前聊天没有这张图片")
    config = load_settings()
    api_key = config.zhipu_key.get_secret_value()
    if not api_key:
        raise HTTPException(422, "请先在 API 设置中填写智谱标准 API 密钥")
    try:
        result = analyze_image(str(request.file_id), request.question, conversation_id, api_key)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(502, f"智谱识图失败：{type(error).__name__}") from None
    if not result["description"].strip():
        raise HTTPException(502, "智谱识图没有返回内容")
    # 成功后才保存问答，避免把失败请求误记为已理解图片。
    user_text = f"识图：{selected['filename']}（{request.file_id}）\n{request.question}"
    save_user_message(conversation_id, user_text)
    save_assistant_message(conversation_id, result["description"], [],
                           provider="zhipu", model=result["model"])
    append_record(conversation_id, "用户", user_text)
    append_record(conversation_id, "API 使用说明", f"识图：智谱 / {result['model']}")
    append_record(conversation_id, "助手", result["description"])
    return {"reply": result["description"], "provider": "zhipu", "model": result["model"]}


# 接收当前聊天的文本附件，限制格式、大小和编码。
@app.post("/chat/upload/{conversation_id}",tags=["AI操作"])
async def upload_file(
    conversation_id: UUID,
    file: UploadFile = File(...),
):
    try:
        filename = file.filename or "attachment.txt"
        suffix = Path(filename).suffix.lower()

        # 同时支持文档和图片；图片保留原图，供用户主动点击识图。
        if suffix not in DOCUMENT_SUFFIXES:
            raise HTTPException(status_code=400, detail="不支持这种文件格式；可选择文本、代码、PDF、Word、Excel、PPT 或图片")
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件不能超过 10 MB")

        is_image = suffix in {".png", ".jpg", ".jpeg"}
        if is_image:
            try:
                with Image.open(BytesIO(content)) as image:
                    image.verify()
                with Image.open(BytesIO(content)) as image:
                    if image.width * image.height > 40_000_000:
                        raise ValueError("图片像素过大")
                    expected_format = "PNG" if suffix == ".png" else "JPEG"
                    if image.format != expected_format:
                        raise ValueError("图片格式与扩展名不匹配")
            except (UnidentifiedImageError, OSError, ValueError) as error:
                raise HTTPException(400, f"无效图片：{error}") from None
        # 图片 OCR 即使没有识别出文字，也保留原图供视觉模型分析。
        try:
            text = await run_in_threadpool(parse_document, content, suffix)
        except ValueError as error:
            if is_image:
                text = ""
            else:
                raise HTTPException(status_code=400, detail=str(error)) from None
        except Exception as error:
            if is_image:
                text = ""
            else:
                print(f"Agent 执行失败：{type(error).__name__}")
                raise HTTPException(status_code=400, detail="解析失败，请检查文件是否完整") from None
        if not is_image and not text.strip():
            raise HTTPException(status_code=400, detail="没有提取到可用文字")
        if get_conversation(conversation_id) is None:
            raise HTTPException(404, "聊天不存在")

        # 使用程序生成的编号保存，避免同名覆盖和文件路径问题。
        file_id = uuid4()
        folder = RECORDS / str(conversation_id) / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        if is_image:
            (folder / f"{file_id}{suffix}").write_bytes(content)
        if text.strip():
            (folder / f"{file_id}.txt").write_text(text, encoding="utf-8")
        save_attachment(conversation_id, file_id, " ".join(filename.split())[:120],
                        "image" if is_image else "document")

        # 聊天记录中留下上传事件，正文单独保存。
        append_record(conversation_id, "上传附件", f"名称：{filename}\n\n编号：{file_id}")
        return {
            "file_id": str(file_id),
            "filename": filename,
            "characters": len(text),
            "kind": "image" if is_image else "document",
        }
    finally:
        # 无论成功还是失败，都关闭上传文件。
        await file.close()

# 用事件流返回进度；最终结果仍包含回答、会话编号和执行记录。
@app.post("/chat/stream", tags=["AI操作"])
def stream_chat(request: ChatRequest):
    config = load_settings()
    require_chat(config)
    if config.provider == "zhipu" and request.web_search and config.search_enabled and not search_key(config):
        raise HTTPException(422, "请在 API 设置中填写智谱密钥，或关闭联网搜索。")
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
                settings=config,
            )
            events.put({"type": "done", "data": result})
        except TaskCancelled:
            events.put({"type": "cancelled", "task_id": task_id})
        except HTTPException as error:
            events.put({"type": "error", "message": str(error.detail)})
        except Exception:
            traceback.print_exc()
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

# 只公开前端构建目录，不公开项目源码、密钥或聊天记录。
frontend_dist = RESOURCE_ROOT / "fronted" / "dist"

if (frontend_dist / "index.html").is_file():
    # 必须放在所有 API 路由之后，避免根路径挂载挡住聊天接口。
    app.mount(
        "/",
        StaticFiles(directory=frontend_dist, html=True),
        name="frontend",
    )
