"""Query adapters; Jina-ColBERT-v2 is the formal vector-search route."""

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from elasticsearch import Elasticsearch

from .contracts import Article, SearchHit


class SearchBackend(Protocol):
    def search(self, query: str, k: int = 3) -> list[SearchHit]: ...


def _validate_query(query: str, k: int) -> None:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if type(k) is not int or not 1 <= k <= 10:
        raise ValueError("k must be an integer between 1 and 10")


class LiteratureSearch:
    """Legacy Elasticsearch adapter kept for comparison/backward integration."""

    def __init__(self, client: Elasticsearch, index: str):
        self.client = client
        self.index = index

    def search(self, query: str, k: int = 3) -> list[SearchHit]:
        _validate_query(query, k)
        response = self.client.search(
            index=self.index,
            query={"multi_match": {"query": query, "fields": ["title", "abstract"]}},
        )
        if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
            raise RuntimeError("Elasticsearch returned incomplete search results")
        return [
            SearchHit(str(hit["_id"]), rank, hit["_score"],
                      hit["_source"]["title"], hit["_source"]["abstract"])
            for rank, hit in enumerate(response["hits"]["hits"][:k])
        ]


class JinaColBERTSearch:
    """Wrap an official Searcher with its matching Jina-ColBERT-v2 collection.

    Lookup must resolve an internal document ID to the exact article version used
    when building that Jina index. Missing mappings fail the query and are never
    silently dropped.
    """

    def __init__(self, searcher: Any, article_lookup: Callable[[int], Article]):
        self.searcher = searcher
        self.article_lookup = article_lookup

    def search(self, query: str, k: int = 3) -> list[SearchHit]:
        _validate_query(query, k)
        ids, ranks, scores = self.searcher.search(query, k=k)
        # Official Searcher can return k ranks even when fewer than k IDs match.
        if len(ids) != len(scores) or len(ranks) < len(ids) or len(ids) > k:
            raise RuntimeError("Inconsistent Jina-ColBERT-v2 search result lengths")
        hits = []
        for doc_id, rank, score in zip(ids, ranks, scores):
            article = self.article_lookup(int(doc_id))
            hits.append(SearchHit(
                article.pmid,
                int(rank),
                float(score),
                article.title,
                article.abstract,
                "jina-colbert-v2",
            ))
        return hits


def create_search_backend(
    *,
    jina_options: Mapping[str, Any] | None = None,
    article_lookup: Callable[[int], Article] | None = None,
    elastic_client: Elasticsearch | None = None,
    elastic_index: str | None = None,
) -> SearchBackend:
    """Create the configured backend without silent fallback.

    Jina-ColBERT-v2 is the formal project route. Its checkpoint and index are
    prepared externally; this factory does not install, download or build them.
    Elasticsearch remains only as an explicitly configured legacy adapter. A
    Jina configuration error never falls back to Elasticsearch.
    """
    if jina_options is not None:
        if not jina_options.get("index"):
            raise ValueError("Jina-ColBERT-v2 requires an index")
        if article_lookup is None:
            raise ValueError("Jina-ColBERT-v2 requires its index-specific article lookup")
        from colbert import Searcher

        return JinaColBERTSearch(Searcher(**dict(jina_options)), article_lookup)
    if elastic_client is not None and elastic_index:
        return LiteratureSearch(elastic_client, elastic_index)
    raise ValueError("Configure Jina-ColBERT-v2 or the legacy Elasticsearch adapter")
