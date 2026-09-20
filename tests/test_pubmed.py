import gzip
import io
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest
from defusedxml.common import EntitiesForbidden
from literature_search_service.pubmed import read_events, iter_events, PubMedParseError
from literature_search_service.contracts import Delete, Upsert

FIXTURE = Path(__file__).parent / 'fixtures/pubmed.xml'


def test_source_order_content_and_replacement():
    events = list(read_events(FIXTURE))
    assert [e.record_number for e in events] == [1, 2, 3]
    a = events[0].article
    assert a.title == 'Effect of synthetic A on X2.'
    assert a.abstract == 'A & B reduced inflammation. Synthetic example.'
    assert a.sections[0].label == 'RESULTS'
    assert a.sections[0].category == 'RESULTS'
    assert a.copyright == 'Fixture only.'
    assert events[1] == Delete(2, ('101', '999'))
    assert isinstance(events[2], Upsert)
    assert events[2].article.pmid_version == '2'
    assert events[2].article.abstract == ''
    assert events[2].article.sections == ()


def test_gzip_equivalence(tmp_path):
    p = tmp_path / 'sample.xml.gz'
    p.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    assert list(read_events(p)) == list(read_events(FIXTURE))


@pytest.mark.parametrize('xml', [
    b'<wrong/>',
    b'<PubmedArticleSet><Unexpected/></PubmedArticleSet>',
    b'<PubmedArticleSet><DeleteCitation/></PubmedArticleSet>',
    b'<PubmedArticleSet><DeleteCitation><PMID Version="1">x</PMID></DeleteCitation></PubmedArticleSet>',
    b'<PubmedArticleSet><DeleteCitation><PMID>1</PMID></DeleteCitation></PubmedArticleSet>',
    b'<PubmedArticleSet><PubmedArticle/></PubmedArticleSet>',
])
def test_invalid_core_structure_fails(xml):
    with pytest.raises(PubMedParseError):
        list(iter_events(io.BytesIO(xml)))


def test_truncated_xml_not_successful_file():
    with pytest.raises(ParseError):
        list(iter_events(io.BytesIO(FIXTURE.read_bytes().replace(b'</PubmedArticleSet>', b''))))


def test_damaged_gzip_footer_not_successful_file(tmp_path):
    p = tmp_path / 'bad.gz'
    p.write_bytes(gzip.compress(FIXTURE.read_bytes())[:-5])
    with pytest.raises(EOFError):
        list(read_events(p))


def test_entity_declarations_rejected():
    with pytest.raises(EntitiesForbidden):
        list(iter_events(io.BytesIO(b'<!DOCTYPE x [<!ENTITY a "boom">]><PubmedArticleSet/>')))


def test_empty_title_and_math_text_preserved():
    xml = b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">1</PMID><Article><ArticleTitle/><Abstract><AbstractText xmlns:m="urn:math">Value <m:math><m:mi>x</m:mi><m:mo>+</m:mo><m:mn>1</m:mn></m:math>.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    article = next(iter_events(io.BytesIO(xml))).article
    assert article.title == ''
    assert article.abstract == 'Value x+1.'
