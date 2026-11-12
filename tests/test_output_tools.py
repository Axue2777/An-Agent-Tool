"""实际生成并重新打开常用成果文件，不连接模型服务。"""
from io import BytesIO
from uuid import uuid4

from docx import Document
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader
from pptx import Presentation

import database
import document_parser
import output_tools
from tests.support import AppCase, SandboxCase


class TestOutputFiles(SandboxCase):
    def test_word_excel_pdf_and_code_are_openable(self):
        chat_id = uuid4()
        sections = [{"heading": "目的", "paragraphs": ["中文内容", "第二段"]}]
        word = output_tools.save_document("学习计划", sections, chat_id)
        sheet = output_tools.save_spreadsheet([{"name": "成绩", "rows": [
            ["姓名", "分数"], ["小明", 95], ["危险", "=1+1"]]}], chat_id)
        pdf = output_tools.save_pdf("学习计划", sections, chat_id)
        code = output_tools.save_text_file("demo.py", "print('hello')", chat_id)
        folder = self.records / str(chat_id) / "artifacts"
        def path(result):
            return folder / f"{result['download_url'].split('/')[-1]}.{result['filename'].split('.')[-1]}"
        self.assertIn("中文内容", [p.text for p in Document(path(word)).paragraphs])
        workbook = load_workbook(path(sheet), read_only=True)
        self.assertEqual(workbook["成绩"]["B2"].value, 95)
        self.assertEqual(workbook["成绩"]["B3"].value, "'=1+1")
        workbook.close()
        self.assertEqual(len(PdfReader(path(pdf)).pages), 1)
        self.assertEqual(path(code).read_text(encoding="utf-8"), "print('hello')")

    def test_generated_name_cannot_escape_artifact_directory(self):
        for name in ("../secret.py", "C:\\secret.py", "script.exe", "a/b.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                output_tools.save_text_file(name, "hello", uuid4())

    def test_excel_and_ppt_inputs_can_be_read(self):
        workbook = Workbook()
        workbook.active.title = "库存"
        workbook.active.append(["商品", "数量"])
        workbook.active.append(["键盘", 12])
        stream = BytesIO()
        workbook.save(stream)
        text = document_parser.parse_document(stream.getvalue(), ".xlsx")
        self.assertIn("键盘\t12", text)

        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        slide.shapes.title.text = "介绍页"
        stream = BytesIO()
        presentation.save(stream)
        self.assertIn("介绍页", document_parser.parse_document(stream.getvalue(), ".pptx"))


class TestOutputDownload(AppCase):
    def test_current_chat_can_download_generated_formats(self):
        database.create_conversation(self.chat_id)
        result = output_tools.save_document("计划", [{"heading": "第一步", "paragraphs": ["开始"]}], self.chat_id)
        response = self.api.get(result["download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0],
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(Document(BytesIO(response.content)).paragraphs[0].text, "计划")
        other_chat = result["download_url"].replace(str(self.chat_id), str(uuid4()))
        self.assertEqual(self.api.get(other_chat).status_code, 404)
