from io import BytesIO
from pypdf import PdfReader
from docx import Document
from ocr_utils import extract_image_text, extract_pdf_page_text
from docx.text.paragraph import Paragraph

# 统一提取不同格式的文字，返回给原有附件保存流程。
def parse_document(content: bytes, suffix: str) -> str:
    if suffix in {".txt", ".md"}:
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
                if not text:
                    raise ValueError(
                        f"第 {number} 页未识别到文字，可能为空白页或图片不清晰"
                    )
                text = "[本页文字由 OCR 识别，可能存在错字]\n" + text           
        return "\n\n".join(parts)

    if suffix == ".docx":
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

    raise ValueError("不支持的文件格式")