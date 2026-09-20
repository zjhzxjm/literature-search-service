"""Use only an explicitly designated disposable ES 8.13 instance.

Creates/deletes one UUID-named test index. Never targets an existing index.
Reference adapted from SciClaims; see THIRD_PARTY_NOTICES.md.
"""
import os
import uuid

import pytest
from elasticsearch import Elasticsearch
from literature_search_service.search import LiteratureSearch


def reference_search(client, index, sentence, k):
    resp = client.search(index=index, query={
        'multi_match': {'query': sentence, 'fields': ['title', 'abstract']}})
    ids, ranks, scores = [], [], []
    for i, hit in enumerate(resp['hits']['hits'][:k]):
        ids.append(int(hit['_id']))
        ranks.append(i)
        scores.append(hit['_score'])
    return ids, ranks, scores


@pytest.mark.integration
def test_sciclaims_same_index_parity():
    url = os.environ.get('LSS_TEST_ES_URL')
    if not url:
        pytest.skip('Set LSS_TEST_ES_URL to a disposable Elasticsearch 8.13 instance')
    index = 'lss-test-' + uuid.uuid4().hex
    with Elasticsearch(url) as client:
        assert client.info()['version']['number'].startswith('8.13.')
        client.indices.create(index=index, settings={'number_of_shards': 1, 'number_of_replicas': 0},
                              mappings={'properties': {'title': {'type': 'text'}, 'abstract': {'type': 'text'}}})
        try:
            for i in range(15):
                client.index(index=index, id=str(i + 1), document={
                    'title': 'synthetic inflammation' if i % 2 else 'synthetic treatment',
                    'abstract': 'treatment reduces inflammation' if i % 3 else ''})
            client.indices.refresh(index=index)
            for query in ['synthetic', 'treatment inflammation', 'no_matching_token_zz']:
                for k in [1, 3, 10]:
                    ids, ranks, scores = reference_search(client, index, query, k)
                    hits = LiteratureSearch(client, index).search(query, k)
                    assert [h.pmid for h in hits] == list(map(str, ids))
                    assert [h.rank for h in hits] == ranks
                    assert [h.score for h in hits] == scores
        finally:
            client.indices.delete(index=index)
