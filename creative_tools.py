"""识图、PPT 和生图；所有成果按聊天编号隔离保存。"""
import base64
from io import BytesIO
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from openai import OpenAI
from PIL import Image, UnidentifiedImageError
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from chat_records import RECORDS


PRESENTATION_TOOL = {"type": "function", "function": {
    "name": "save_presentation", "description": "制作可下载的 PPTX 演示文稿。",
    "parameters": {"type": "object", "properties": {
        "title": {"type": "string"},
        "slides": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "bullets"], "additionalProperties": False}}},
        "required": ["title", "slides"], "additionalProperties": False}}}

IMAGE_TOOL = {"type": "function", "function": {
    "name": "generate_image", "description": "使用智谱 glm-image 根据描述生成图片。",
    "parameters": {"type": "object", "properties": {
        "prompt": {"type": "string"}}, "required": ["prompt"],
        "additionalProperties": False}}}


def analyze_image(file_id, question, conversation_id, api_key):
    """只由用户明确点击识图按钮触发，读取被选中的一张图片。"""
    if not api_key:
        raise ValueError("请先配置智谱标准 API 密钥")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("识图问题不能为空且不能超过 2000 字")
    image_id = UUID(file_id)
    folder = RECORDS / str(conversation_id) / "attachments"
    path = next((folder / f"{image_id}{suffix}" for suffix in (".png", ".jpg", ".jpeg")
                 if (folder / f"{image_id}{suffix}").is_file()), None)
    if path is None:
        raise ValueError("当前聊天没有这张图片")
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    # 不把图片内容、密钥或 Base64 记录在 Markdown 日志里。
    with OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/",
                http_client=httpx.Client(trust_env=False, timeout=90), max_retries=0) as client:
        response = client.chat.completions.create(
            model="glm-5.3-flash",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]}],
        )
    return {"description": response.choices[0].message.content or "",
            "provider": "zhipu", "model": "glm-5.3-flash"}


def save_presentation(title, slides, conversation_id):
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("PPT 标题不能为空且不能超过 120 字")
    if not isinstance(slides, list) or not 1 <= len(slides) <= 30:
        raise ValueError("PPT 需要 1 至 30 页")
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for index, item in enumerate(slides, 1):
        if not isinstance(item, dict) or set(item) != {"title", "bullets"}:
            raise ValueError("每页必须包含 title 和 bullets")
        heading, bullets = item["title"], item["bullets"]
        if not isinstance(heading, str) or not heading.strip() or len(heading) > 120:
            raise ValueError("每页标题不能为空且不能超过 120 字")
        if not isinstance(bullets, list) or len(bullets) > 8 or any(
            not isinstance(point, str) or not point.strip() or len(point) > 250
            for point in bullets
        ):
            raise ValueError("每页最多 8 条要点，每条不超过 250 字")
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(247, 247, 255)
        box = slide.shapes.add_textbox(Inches(.9), Inches(.7), Inches(11.5), Inches(.9))
        heading_p = box.text_frame.paragraphs[0]
        heading_p.text = heading
        heading_p.font.size, heading_p.font.bold = Pt(32), True
        heading_p.font.color.rgb = RGBColor(59, 60, 112)
        body = slide.shapes.add_textbox(Inches(1), Inches(1.9), Inches(11.3), Inches(4.7))
        for point_index, point in enumerate(bullets):
            paragraph = body.text_frame.paragraphs[0] if point_index == 0 else body.text_frame.add_paragraph()
            paragraph.text = "✦  " + point
            paragraph.font.size = Pt(21)
            paragraph.font.color.rgb = RGBColor(65, 70, 96)
            paragraph.space_after = Pt(17)
        footer = slide.shapes.add_textbox(Inches(11.9), Inches(7), Inches(.5), Inches(.3))
        footer.text_frame.paragraphs[0].text = str(index)
    file_id = uuid4()
    folder = RECORDS / str(conversation_id) / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    deck.save(folder / f"{file_id}.pptx")
    return {"download_url": f"/chat/files/{conversation_id}/{file_id}",
            "slides": len(slides), "title": title, "filename": "presentation.pptx"}


def generate_image(prompt, conversation_id, api_key):
    if not api_key:
        return {"error": "请先配置智谱标准 API 密钥"}
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
        raise ValueError("生图描述不能为空且不能超过 1000 字")
    try:
        with httpx.Client(trust_env=False, timeout=120, follow_redirects=False) as client:
            response = client.post(
                "https://open.bigmodel.cn/api/paas/v4/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "glm-image", "prompt": prompt, "size": "1280x1280"},
            )
            if response.status_code != 200:
                try:
                    issue = response.json().get("error", {})
                    code = issue.get("code", "") if isinstance(issue, dict) else ""
                except ValueError:
                    code = ""
                code = str(code) if str(code).isdigit() and len(str(code)) <= 6 else ""
                hint = "服务繁忙或达到调用限制，请稍后再试" if response.status_code == 429 else "请检查额度、模型权限或服务状态"
                return {"error": f"智谱生图 HTTP {response.status_code}{f'（{code}）' if code else ''}：{hint}"}
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            remote = items[0].get("url", "") if isinstance(items, list) and items and isinstance(items[0], dict) else ""
            parts = urlsplit(remote)
            host = (parts.hostname or "").lower()
            # 仅下载智谱图片域名，避免上游 URL 指向内网。
            if parts.scheme != "https" or parts.username or parts.password or not (
                host.endswith(".bigmodel.cn") or host.endswith(".chatglm.cn")
            ):
                return {"error": "智谱返回了不支持的图片地址，未保存"}
            with client.stream("GET", remote) as image_response:
                image_response.raise_for_status()
                content = bytearray()
                for chunk in image_response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 15 * 1024 * 1024:
                        return {"error": "图片超过 15 MB，未保存"}
    except httpx.TimeoutException:
        return {"error": "智谱生图或图片下载超时，请稍后重试"}
    except httpx.HTTPError:
        return {"error": "智谱生图连接或图片下载失败，请检查网络与服务状态"}
    except (ValueError, KeyError, TypeError):
        return {"error": "智谱生图响应格式异常，未保存图片"}
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            suffix = {"PNG": ".png", "JPEG": ".jpg"}.get(image.format)
    except (UnidentifiedImageError, OSError):
        suffix = None
    if suffix is None:
        return {"error": "智谱返回的文件不是有效的 PNG/JPEG"}
    file_id = uuid4()
    folder = RECORDS / str(conversation_id) / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{file_id}{suffix}").write_bytes(content)
    return {"image_url": f"/chat/files/{conversation_id}/{file_id}",
            "provider": "zhipu", "model": "glm-image",
            "filename": f"generated{suffix}"}
