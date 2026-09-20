"""Adapter contract tests; no model installation or GPU is involved."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from literature_search_service.contracts import AbstractSection, Article
from literature_search_service.search import (
    ColBERTSearch, LiteratureSearch, create_search_backend,
)


def article(pmid):
    return Article(pmid, "1", "Synthetic title", (AbstractSection("Synthetic abstract"),))


def test_mapping_order_native_rank_and_score():
    searcher = Mock()
    searcher.search.return_value = ([7, 2], [1, 2, 3], [19.25, 17.5])
    lookup = {7: article("1234"), 2: article("4567")}.__getitem__
    hits = ColBERTSearch(searcher, lookup).search("query")
    searcher.search.assert_called_once_with("query", k=3)
    assert [(h.pmid, h.rank, h.score, h.backend) for h in hits] == [
        ("1234", 1, 19.25, "colbert"), ("4567", 2, 17.5, "colbert")]
    assert hits[0].abstract == "Synthetic abstract"


def test_empty_hits_with_official_rank_padding():
    searcher = Mock()
    searcher.search.return_value = ([], [1, 2, 3], [])
    lookup = Mock()
    assert ColBERTSearch(searcher, lookup).search("query") == []
    lookup.assert_not_called()


def test_missing_mapping_is_error():
    searcher = Mock()
    searcher.search.return_value = ([9], [1], [1.0])
    with pytest.raises(KeyError):
        ColBERTSearch(searcher, {}.__getitem__).search("query")


@pytest.mark.parametrize("response", [([1], [], [2]), ([1], [1], []),
                                     ([1, 2], [1, 2], [2, 1])])
def test_malformed_results_fail(response):
    searcher = Mock()
    searcher.search.return_value = response
    with pytest.raises(RuntimeError):
        ColBERTSearch(searcher, Mock()).search("query", k=1)


def test_colbert_priority_and_options_forwarding(monkeypatch):
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "colbert", SimpleNamespace(Searcher=constructor))
    backend = create_search_backend(colbert_options={"index": "sample", "checkpoint": "model"},
                                    article_lookup=Mock(), elastic_client=Mock(), elastic_index="es")
    assert isinstance(backend, ColBERTSearch)
    constructor.assert_called_once_with(index="sample", checkpoint="model")


def test_loading_failure_does_not_fallback(monkeypatch):
    constructor = Mock(side_effect=RuntimeError("model unavailable"))
    monkeypatch.setitem(sys.modules, "colbert", SimpleNamespace(Searcher=constructor))
    with pytest.raises(RuntimeError, match="model unavailable"):
        create_search_backend(colbert_options={"index": "sample"}, article_lookup=Mock(),
                              elastic_client=Mock(), elastic_index="es")


def test_elasticsearch_does_not_require_colbert(monkeypatch):
    monkeypatch.setitem(sys.modules, "colbert", None)
    assert isinstance(create_search_backend(elastic_client=Mock(), elastic_index="es"),
                      LiteratureSearch)


@pytest.mark.parametrize("options", [{}, {"index": "sample"}])
def test_incomplete_colbert_config_does_not_fallback(options):
    with pytest.raises(ValueError):
        create_search_backend(colbert_options=options, elastic_client=Mock(), elastic_index="es")


def test_no_backend_is_error():
    with pytest.raises(ValueError):
        create_search_backend()


def test_invalid_query_does_not_call_model():
    searcher = Mock()
    with pytest.raises(ValueError):
        ColBERTSearch(searcher, Mock()).search("", k=3)
    searcher.search.assert_not_called()
