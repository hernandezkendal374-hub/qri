import re
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
            local_end = local_start + len(source_text)
            if local_start < 0:
                # PDF extraction frequently inserts line breaks inside sentences.
                # Match only whitespace differences, then retain the exact local
                # PDF substring so stored evidence remains genuinely verbatim.
                tokens = source_text.split()
                if not tokens:
                    continue
                match = re.search(r"\s+".join(re.escape(token) for token in tokens), page.text)
                if not match:
                    continue
                local_start, local_end = match.span()
            start = page.start_offset + local_start
            end = page.start_offset + local_end
            verified_text = page.text[local_start:local_end]
            if self.document.text[start:end] != verified_text:
                raise EvidenceNotFoundError("Page and document offsets do not agree")
            paragraph = page.text[:local_start].count("\n\n")
            return EvidenceLocation(
                page_number=page.page_number,
                paragraph_index=paragraph,
                start_offset=start,
                end_offset=end,
                source_text=verified_text,
            )
        raise EvidenceNotFoundError("Quote does not occur verbatim in parsed full text")
