from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    text: str
    start_offset: int
    end_offset: int


@dataclass(slots=True)
class ParsedDocument:
    text: str
    pages: list[ParsedPage]
    parser_version: str


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """Parse a local document while preserving page-level offsets."""
