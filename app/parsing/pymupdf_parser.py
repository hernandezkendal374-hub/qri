from pathlib import Path

import pymupdf

from app.parsing.base import DocumentParser, ParsedDocument, ParsedPage


class PyMuPDFParser(DocumentParser):
    version = f"pymupdf-{pymupdf.VersionBind}"

    def parse(self, path: Path) -> ParsedDocument:
        pages: list[ParsedPage] = []
        chunks: list[str] = []
        offset = 0
        with pymupdf.open(path) as document:
            if document.page_count == 0:
                raise ValueError("PDF has no pages")
            for index, page in enumerate(document):
                text = page.get_text("text").strip()
                if chunks:
                    chunks.append("\n\n")
                    offset += 2
                start = offset
                chunks.append(text)
                offset += len(text)
                pages.append(
                    ParsedPage(
                        page_number=index + 1,
                        text=text,
                        start_offset=start,
                        end_offset=offset,
                    )
                )
        combined = "".join(chunks)
        if not combined.strip():
            raise ValueError("PDF contains no extractable text")
        return ParsedDocument(text=combined, pages=pages, parser_version=self.version)
