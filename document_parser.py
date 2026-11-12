from io import BytesIO
from pypdf import PdfReader
from docx import Document
from ocr_utils import extract_image_text, extract_pdf_page_text
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from pptx import Presentation
from zipfile import ZipFile


TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts",
                 ".vue", ".html", ".css", ".xml", ".yaml", ".yml", ".sql"}
DOCUMENT_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx", ".xlsx", ".pptx",
                                     ".png", ".jpg", ".jpeg"}


def _check_office_archive(content):
    # Office 文件内部是 ZIP；先限制解压后的总量，避免很小的压缩包占满内存。
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(item.file_size for item in entries) > 100 * 1024 * 1024:
            raise ValueError("Office 文件展开后过大")

# 统一提取不同格式的文字，返回给原有附件保存流程。
def parse_document(content: bytes, suffix: str) -> str:
    if suffix in TEXT_SUFFIXES:
        return content.decode("utf-8-sig")
    # 图片附件直接通过 OCR 提取文字。
    if suffix in {".png", ".jpg", ".jpeg"}:
        return extract_image_text(content)
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请先解除密码")
        if len(reader.pages) > 100:
            raise ValueError("第一版最多支持 100 页 PDF")

        # 标记页码，方便模型说明内容来源。
        parts = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            # 避免将未读到文字的页面当作已成功理解。
            # 当前页没有可提取文字时，转为图片进行识别。
            if not text.strip():
                text = extract_pdf_page_text(content, number - 1)
                if not text.strip():
                    raise ValueError(
                        f"第 {number} 页未识别到文字，可能为空白页或图片不清晰"
                    )
                text = "[本页文字由 OCR 识别，可能存在错字]\n" + text
            # 文本页和 OCR 页都加入结果，保持原始顺序并保留页码。
            parts.append(f"## 第 {number} 页\n\n{text}")
        return "\n\n".join(parts)

    if suffix == ".docx":
        _check_office_archive(content)
        document = Document(BytesIO(content))
        parts = []
        # 按正文顺序读取段落和顶层表格。
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                parts.append(block.text)
            else:
                for row in block.rows:
                    parts.append("\t".join(cell.text for cell in row.cells))
        return "\n\n".join(parts)

    if suffix == ".xlsx":
        _check_office_archive(content)
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            if len(workbook.worksheets) > 20:
                raise ValueError("Excel 最多读取 20 个工作表")
            parts = []
            for sheet in workbook.worksheets:
                lines = []
                for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    if number > 5000:
                        raise ValueError("Excel 每张表最多读取 5000 行")
                    lines.append("\t".join("" if value is None else str(value)
                                           for value in row[:30]))
                parts.append(f"## 工作表：{sheet.title}\n" + "\n".join(lines))
            return "\n\n".join(parts)
        finally:
            workbook.close()

    if suffix == ".pptx":
        _check_office_archive(content)
        presentation = Presentation(BytesIO(content))
        if len(presentation.slides) > 100:
            raise ValueError("PPT 最多读取 100 页")
        parts = []
        for number, slide in enumerate(presentation.slides, start=1):
            texts = []
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text.strip():
                    texts.append(shape.text)
                if shape.has_table:
                    for row in shape.table.rows:
                        texts.append("\t".join(cell.text for cell in row.cells))
            parts.append(f"## 第 {number} 页\n" + "\n".join(texts))
        return "\n\n".join(parts)

    raise ValueError("不支持的文件格式")
