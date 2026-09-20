"""Internal records for the first implementation increment; not an HTTP schema."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AbstractSection:
    text: str
    label: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class Article:
    pmid: str
    pmid_version: str
    title: str
    sections: tuple[AbstractSection, ...]
    copyright: str | None = None

    @property
    def abstract(self) -> str:
        return " ".join(section.text for section in self.sections)


@dataclass(frozen=True)
class Upsert:
    record_number: int
    article: Article


@dataclass(frozen=True)
class Delete:
    record_number: int
    pmids: tuple[str, ...]


@dataclass(frozen=True)
class SearchHit:
    pmid: str
    rank: int
    score: float
    title: str
    abstract: str
    backend: str = "elasticsearch"
