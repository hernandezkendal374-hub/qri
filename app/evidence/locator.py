from dataclasses import dataclass

from app.parsing.base import ParsedDocument


class EvidenceNotFoundError(ValueError):
    pass


@dataclass(slots=True)
class EvidenceLocation:
    page_number: int
    paragraph_index: int
    start_offset: int
    end_offset: int
    source_text: str


class EvidenceLocator:
    def __init__(self, document: ParsedDocument) -> None:
        self.document = document

    def locate(self, source_text: str) -> EvidenceLocation:
        if not source_text.strip():
            raise EvidenceNotFoundError("Evidence quote is empty")
        for page in self.document.pages:
            local_start = page.text.find(source_text)
            if local_start < 0:
                continue
            start = page.start_offset + local_start
            end = start + len(source_text)
            if self.document.text[start:end] != source_text:
                raise EvidenceNotFoundError("Page and document offsets do not agree")
            paragraph = page.text[:local_start].count("\n\n")
            return EvidenceLocation(
                page_number=page.page_number,
                paragraph_index=paragraph,
                start_offset=start,
                end_offset=end,
                source_text=source_text,
            )
        raise EvidenceNotFoundError("Quote does not occur verbatim in parsed full text")
