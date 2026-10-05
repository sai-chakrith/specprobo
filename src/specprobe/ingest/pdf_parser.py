import pdfplumber

from .base import TextBlock


class PdfTableParser:
    def parse(self, path: str) -> list[TextBlock]:
        blocks: list[TextBlock] = []
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text:
                    blocks.append(TextBlock(text, page_number))
        return blocks
