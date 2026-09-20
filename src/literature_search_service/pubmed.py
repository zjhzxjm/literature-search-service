"""Stream PubMed FTP XML events without fetching external DTDs.

Consumers must exhaust the iterator before marking a file successful: malformed
XML or a damaged gzip footer can fail after earlier records have been yielded.
This is a core-field parser, not a full PubMed DTD validator.
"""

import gzip
import re
from pathlib import Path
from typing import BinaryIO, Iterator
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import iterparse

from .contracts import AbstractSection, Article, Delete, Upsert


class PubMedParseError(ValueError):
    """Input cannot be interpreted under the supported core-field contract."""


def _text(element: Element | None) -> str:
    return "" if element is None else "".join(element.itertext()).strip()


def _pmid(element: Element | None) -> tuple[str, str]:
    value = _text(element)
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise PubMedParseError("Missing or invalid PMID")
    version = element.get("Version", "")
    if not re.fullmatch(r"[1-9][0-9]*", version):
        raise PubMedParseError("Missing or invalid PMID Version")
    return value, version


def _article(element: Element) -> Article:
    citation = element.find("MedlineCitation")
    if citation is None:
        raise PubMedParseError("Missing MedlineCitation")
    pmid, version = _pmid(citation.find("PMID"))
    article = citation.find("Article")
    if article is None or article.find("ArticleTitle") is None:
        raise PubMedParseError("Missing Article or ArticleTitle")
    # Empty titles are preserved; absent titles are structural errors.
    sections = tuple(
        AbstractSection(_text(part), part.get("Label"), part.get("NlmCategory"))
        for part in article.findall("Abstract/AbstractText")
    )
    copyright_node = article.find("Abstract/CopyrightInformation")
    return Article(
        pmid, version, _text(article.find("ArticleTitle")), sections,
        None if copyright_node is None else _text(copyright_node),
    )


def iter_events(stream: BinaryIO) -> Iterator[Upsert | Delete]:
    """Yield top-level records in source order; keep at most one record tree.

    XML wrappers and MathML retain textual content in document order. No formula
    interpretation is attempted. OtherAbstract is not added to the main abstract.
    Unknown top-level records fail explicitly rather than being silently dropped.
    """
    context = iterparse(stream, events=("start", "end"), forbid_entities=True,
                        forbid_external=True)
    root = None
    depth = 0
    number = 0
    for event, element in context:
        if event == "start":
            depth += 1
            if root is None:
                root = element
                if root.tag != "PubmedArticleSet":
                    raise PubMedParseError("Expected PubmedArticleSet root")
            continue
        if depth == 2:
            number += 1
            if element.tag == "PubmedArticle":
                result = Upsert(number, _article(element))
            elif element.tag == "DeleteCitation":
                children = list(element)
                if not children or any(child.tag != "PMID" for child in children):
                    raise PubMedParseError("Invalid DeleteCitation children")
                result = Delete(number, tuple(_pmid(child)[0] for child in children))
            else:
                raise PubMedParseError(f"Unsupported top-level record: {element.tag}")
            root.remove(element)
            element.clear()
            yield result
        depth -= 1


def read_events(path: str | Path) -> Iterator[Upsert | Delete]:
    """Read XML or .gz; this function does not verify the source MD5."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        yield from iter_events(stream)
