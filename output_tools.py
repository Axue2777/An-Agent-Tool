"""把模型编写的内容保存为可下载的常用文件格式。"""
import re
from pathlib import Path
from uuid import uuid4

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from xml.sax.saxutils import escape

from chat_records import RECORDS


TEXT_EXTENSIONS = {"txt", "md", "csv", "json", "py", "js", "ts", "vue",
                   "html", "css", "xml", "yaml", "yml", "sql"}


def _tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False}}}


DOCUMENT_TOOL = _tool("save_document", "制作可编辑 Word DOCX 文档。", {
    "title": {"type": "string"}, "sections": {"type": "array", "items": {
        "type": "object", "properties": {"heading": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}}},
        "required": ["heading", "paragraphs"], "additionalProperties": False}}},
    ["title", "sections"])

SPREADSHEET_TOOL = _tool("save_spreadsheet", "制作可编辑 Excel XLSX 表格。", {
    "sheets": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "rows": {"type": "array", "items": {
            "type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}}},
        "required": ["name", "rows"], "additionalProperties": False}}},
    ["sheets"])

PDF_TOOL = _tool("save_pdf", "制作可下载的 PDF 文档，支持中文正文。", {
    "title": {"type": "string"}, "sections": {"type": "array", "items": {
        "type": "object", "properties": {"heading": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}}},
        "required": ["heading", "paragraphs"], "additionalProperties": False}}},
    ["title", "sections"])

TEXT_FILE_TOOL = _tool("save_text_file", "保存代码、CSV、JSON、HTML 或普通文本文件。", {
    "filename": {"type": "string", "description": "文件名含扩展名，不含目录"},
    "content": {"type": "string"}}, ["filename", "content"])


def _folder(conversation_id):
    folder = RECORDS / str(conversation_id) / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _result(conversation_id, file_id, filename):
    return {"download_url": f"/chat/files/{conversation_id}/{file_id}",
            "filename": filename}


def _sections(title, sections):
    if not isinstance(title, str) or not title.strip() or len(title) > 150:
        raise ValueError("标题不能为空且不能超过 150 字")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 30:
        raise ValueError("需要 1 至 30 个章节")
    for item in sections:
        if not isinstance(item, dict) or set(item) != {"heading", "paragraphs"}:
            raise ValueError("每章必须包含 heading 和 paragraphs")
        heading, paragraphs = item["heading"], item["paragraphs"]
        if not isinstance(heading, str) or len(heading) > 150:
            raise ValueError("章节标题不能超过 150 字")
        if not isinstance(paragraphs, list) or len(paragraphs) > 30 or any(
            not isinstance(text, str) or len(text) > 5000 for text in paragraphs
        ):
            raise ValueError("每章最多 30 段，每段不超过 5000 字")


def save_document(title, sections, conversation_id):
    _sections(title, sections)
    document = Document()
    document.add_heading(title.strip(), 0)
    for item in sections:
        if item["heading"].strip():
            document.add_heading(item["heading"].strip(), level=1)
        for paragraph in item["paragraphs"]:
            document.add_paragraph(paragraph)
    file_id = uuid4()
    document.save(_folder(conversation_id) / f"{file_id}.docx")
    return _result(conversation_id, file_id, "document.docx")


def save_spreadsheet(sheets, conversation_id):
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= 10:
        raise ValueError("表格需要 1 至 10 个工作表")
    workbook = Workbook()
    workbook.remove(workbook.active)
    used_names = set()
    for spec in sheets:
        if not isinstance(spec, dict) or set(spec) != {"name", "rows"}:
            raise ValueError("工作表必须包含 name 和 rows")
        name, rows = spec["name"], spec["rows"]
        if not isinstance(name, str) or not name.strip() or len(name) > 31 or re.search(r"[\\/*?:\[\]]", name):
            raise ValueError("工作表名称不符合 Excel 规则")
        if name.casefold() in used_names:
            raise ValueError("工作表名称不能重复")
        used_names.add(name.casefold())
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError("每张表最多 2000 行")
        sheet = workbook.create_sheet(name)
        sheet.freeze_panes = "A2"
        for row in rows:
            if not isinstance(row, list) or len(row) > 30 or any(
                value is not None and type(value) not in (str, int, float, bool)
                or isinstance(value, str) and len(value) > 1000 for value in row
            ):
                raise ValueError("每行最多 30 列，每格文字不超过 1000 字")
            # 外部表格内容不作为公式执行；需要公式可在 Excel 中自行编辑。
            sheet.append(["'" + value if isinstance(value, str)
                          and value.lstrip().startswith(("=", "+", "-", "@"))
                          else value for value in row])
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="45377D")
            cell.fill = PatternFill("solid", fgColor="EAE4FF")
    file_id = uuid4()
    workbook.save(_folder(conversation_id) / f"{file_id}.xlsx")
    return _result(conversation_id, file_id, "spreadsheet.xlsx")


def save_pdf(title, sections, conversation_id):
    _sections(title, sections)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    body_style = ParagraphStyle("body-cn", fontName="STSong-Light", fontSize=11,
                                leading=18, textColor=colors.HexColor("#38405A"))
    title_style = ParagraphStyle("title-cn", parent=body_style, fontSize=20,
                                 leading=28, alignment=TA_CENTER, spaceAfter=20)
    heading_style = ParagraphStyle("heading-cn", parent=body_style, fontSize=15,
                                   leading=23, spaceBefore=18, spaceAfter=8)
    story = [Paragraph(escape(title.strip()), title_style)]
    for item in sections:
        if item["heading"].strip():
            story.append(Paragraph(escape(item["heading"].strip()), heading_style))
        for text in item["paragraphs"]:
            story.append(Paragraph(escape(text).replace("\n", "<br/>"), body_style))
            story.append(Spacer(1, 10))
    file_id = uuid4()
    output = _folder(conversation_id) / f"{file_id}.pdf"
    SimpleDocTemplate(str(output), pagesize=A4).build(story)
    return _result(conversation_id, file_id, "document.pdf")


def save_text_file(filename, content, conversation_id):
    if not isinstance(filename, str) or not re.fullmatch(r"[\w .()\-\u4e00-\u9fff]{1,100}", filename):
        raise ValueError("文件名只能包含普通文字，不能包含目录或特殊字符")
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in TEXT_EXTENSIONS:
        raise ValueError("不支持这个文本文件扩展名")
    if not isinstance(content, str) or not content.strip() or len(content) > 200000:
        raise ValueError("文件内容不能为空且不能超过 20 万字符")
    file_id = uuid4()
    (_folder(conversation_id) / f"{file_id}.{extension}").write_text(content, encoding="utf-8")
    return _result(conversation_id, file_id, filename)
