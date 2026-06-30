import fitz  # PyMuPDF
import docx
import io
import logging
from typing import Tuple

logger = logging.getLogger("airag.parser")

class DocumentParser:
    @staticmethod
    def parse_pdf(file_bytes: bytes) -> Tuple[str, int]:
        """
        解析 PDF 檔案位元組，提取純文字與頁數。
        """
        text = []
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page_count = doc.page_count
            for page in doc:
                text.append(page.get_text())
            doc.close()
            return "\n".join(text).strip(), page_count
        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            raise ValueError(f"PDF 解析失敗: {str(e)}")

    @staticmethod
    def parse_docx(file_bytes: bytes) -> Tuple[str, int]:
        """
        解析 DOCX 檔案位元組，提取純文字。
        """
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            text = []
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text.append(paragraph.text)
            # 讀取表格中的文字
            for table in doc.tables:
                for row in table.rows:
                    row_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_text:
                        text.append(" | ".join(row_text))
            
            return "\n".join(text).strip(), 1  # Word 文件頁數通常以 1 代替或估算
        except Exception as e:
            logger.error(f"Error parsing DOCX: {e}")
            raise ValueError(f"DOCX 解析失敗: {str(e)}")

    @staticmethod
    def parse_text(file_bytes: bytes) -> Tuple[str, int]:
        """
        解析純文字/Markdown 檔案。
        """
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = file_bytes.decode("big5", errors="ignore")
            except Exception as e:
                logger.error(f"Error decoding text: {e}")
                raise ValueError(f"編碼解析失敗，請確認檔案使用 UTF-8 或 Big5 編碼: {str(e)}")
        return text.strip(), 1

    @classmethod
    def parse_file(cls, filename: str, file_bytes: bytes) -> Tuple[str, int, int]:
        """
        依據副檔名自動分流解析，回傳 (純文字, 頁數, 字元數)。
        """
        ext = filename.split(".")[-1].lower()
        if ext == "pdf":
            text, pages = cls.parse_pdf(file_bytes)
        elif ext in ["docx", "doc", "dotx"]:
            from services.word_parent_child_chunker import parse_docx_to_markdown, parse_doc_to_markdown
            if ext in ["docx", "dotx"]:
                text = parse_docx_to_markdown(file_bytes)
            else:
                text = parse_doc_to_markdown(file_bytes, filename)
            pages = 1
        elif ext in ["txt", "md", "markdown", "4gl", "4fd"]:
            text, pages = cls.parse_text(file_bytes)
        else:
            raise ValueError(f"目前不支援 .{ext} 的檔案格式。支援的格式有 PDF, DOCX, DOC, DOTX, TXT, MD, 4GL, 4FD")
        
        return text, pages, len(text)

