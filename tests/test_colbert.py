"""Jina-ColBERT-v2 adapter contract tests; no model/GPU is involved."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from literature_search_service.contracts import AbstractSection, Article
from literature_search_service.search import (
    JinaColBERTSearch, LiteratureSearch, create_search_backend,
)


def article(pmid):
    return Article(pmid, "1", "Synthetic title", (AbstractSection("Synthetic abstract"),))


def test_mapping_order_native_rank_score_and_backend():
    searcher = Mock()
    searcher.search.return_value = ([7, 2], [1, 2, 3], [19.25, 17.5])
    lookup = {7: article("1234"), 2: article("4567")}.__getitem__
    hits = JinaColBERTSearch(searcher, lookup).search("query")
    searcher.search.assert_called_once_with("query", k=3)
    assert [(h.pmid, h.rank, h.score, h.backend) for h in hits] == [
        ("1234", 1, 19.25, "jina-colbert-v2"),
        ("4567", 2, 17.5, "jina-colbert-v2"),
    ]
    assert hits[0].abstract == "Synthetic abstract"


def test_empty_hits_with_official_rank_padding():
    searcher = Mock()
    searcher.search.return_value = ([], [1, 2, 3], [])
    lookup = Mock()
    assert JinaColBERTSearch(searcher, lookup).search("query") == []
    lookup.assert_not_called()


def test_missing_mapping_is_error():
    searcher = Mock()
    searcher.search.return_value = ([9], [1], [1.0])
    with pytest.raises(KeyError):
        JinaColBERTSearch(searcher, {}.__getitem__).search("query")


@pytest.mark.parametrize("response", [([1], [], [2]), ([1], [1], []),
                                     ([1, 2], [1, 2], [2, 1])])
def test_malformed_results_fail(response):
    searcher = Mock()
    searcher.search.return_value = response
    with pytest.raises(RuntimeError):
        JinaColBERTSearch(searcher, Mock()).search("query", k=1)


def test_jina_priority_and_options_forwarding(monkeypatch):
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "colbert", SimpleNamespace(Searcher=constructor))
    backend = create_search_backend(
        jina_options={"index": "sample", "checkpoint": "jina-model"},
        article_lookup=Mock(),
        elastic_client=Mock(),
        elastic_index="es",
    )
    assert isinstance(backend, JinaColBERTSearch)
    constructor.assert_called_once_with(index="sample", checkpoint="jina-model")


def test_jina_loading_failure_does_not_fallback(monkeypatch):
    constructor = Mock(side_effect=RuntimeError("model unavailable"))
    monkeypatch.setitem(sys.modules, "colbert", SimpleNamespace(Searcher=constructor))
    with pytest.raises(RuntimeError, match="model unavailable"):
        create_search_backend(
            jina_options={"index": "sample"},
            article_lookup=Mock(),
            elastic_client=Mock(),
            elastic_index="es",
        )


def test_legacy_elasticsearch_does_not_require_jina(monkeypatch):
    monkeypatch.setitem(sys.modules, "colbert", None)
    assert isinstance(
        create_search_backend(elastic_client=Mock(), elastic_index="es"),
        LiteratureSearch,
    )


@pytest.mark.parametrize("options", [{}, {"index": "sample"}])
def test_incomplete_jina_config_does_not_fallback(options):
    with pytest.raises(ValueError):
        create_search_backend(
            jina_options=options,
            elastic_client=Mock(),
            elastic_index="es",
        )


def test_old_colbert_options_are_no_longer_a_factory_contract():
    with pytest.raises(TypeError):
        create_search_backend(colbert_options={"index": "old"})  # type: ignore[call-arg]


def test_no_backend_is_error():
    with pytest.raises(ValueError):
        create_search_backend()


def test_invalid_query_does_not_call_model():
    searcher = Mock()
    with pytest.raises(ValueError):
        JinaColBERTSearch(searcher, Mock()).search("", k=3)
    searcher.search.assert_not_called()
