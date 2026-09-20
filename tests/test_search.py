from unittest.mock import Mock
import pytest
from literature_search_service.search import LiteratureSearch


def test_preserves_request_rank_score_and_ties():
    client = Mock()
    client.search.return_value = {'hits': {'hits': [
        {'_id': p, '_score': 2.5, '_source': {'title': p, 'abstract': ''}}
        for p in ['20', '10', '30']
    ]}}
    hits = LiteratureSearch(client, 'test').search('  synthetic query  ', 2)
    client.search.assert_called_once_with(index='test', query={
        'multi_match': {'query': '  synthetic query  ', 'fields': ['title', 'abstract']}})
    assert [(h.pmid, h.rank, h.score) for h in hits] == [('20', 0, 2.5), ('10', 1, 2.5)]


@pytest.mark.parametrize('query,k', [('', 3), (' ', 3), (None, 3), ('x', 0), ('x', 11), ('x', True), ('x', 1.5)])
def test_invalid_input_never_calls_backend(query, k):
    client = Mock()
    with pytest.raises(ValueError):
        LiteratureSearch(client, 'test').search(query, k)
    client.search.assert_not_called()


@pytest.mark.parametrize('metadata', [{'timed_out': True}, {'_shards': {'failed': 1}}])
def test_partial_results_rejected(metadata):
    client = Mock()
    client.search.return_value = dict(metadata, hits={'hits': []})
    with pytest.raises(RuntimeError):
        LiteratureSearch(client, 'test').search('query')
