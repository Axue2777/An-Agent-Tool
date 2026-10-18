from PIL import Image
import pytesseract

# 指定 OCR 程序的位置，避免依赖系统 PATH 设置。
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# 打开测试图片，同时启用简体中文和英语识别。
with Image.open("ocr_test.png") as image:
    text = pytesseract.image_to_string(
        image,
        lang="chi_sim+eng",
        timeout=30,
    )

# 打印实际识别结果，便于与原图核对。
print(text.strip() or "没有识别到文字")