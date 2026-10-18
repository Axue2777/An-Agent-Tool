from io import BytesIO
from PIL import Image, ImageOps
import pytesseract
import pypdfium2 as pdfium

# 使用已经独立验证成功的 Tesseract 安装路径。
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# 识别图片中的中英文，每张图片最多等待 30 秒。
def recognize_image(image):
    corrected = ImageOps.exif_transpose(image)
    try:
        return pytesseract.image_to_string(
            corrected, lang="chi_sim+eng", timeout=30
        ).strip()
    finally:
        corrected.close()


# 从上传的图片字节读取内容，自动处理手机照片的旋转信息。
def extract_image_text(content):
    with Image.open(BytesIO(content)) as image:
        return recognize_image(image)


# 将指定 PDF 页面渲染为图片，再执行 OCR。
def extract_pdf_page_text(content, page_index):
    with pdfium.PdfDocument(content) as document:
        with document[page_index] as page:
            with page.render(scale=2) as bitmap:
                with bitmap.to_pil() as image:
                    return recognize_image(image)