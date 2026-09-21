"""Backend-neutral query adapters for reproducible literature retrieval."""

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .contracts import Article, SearchHit


class SearchBackend(Protocol):
    def search(self, query: str, k: int = 3) -> list[SearchHit]: ...


def _validate_query(query: str, k: int) -> None:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if type(k) is not int or not 1 <= k <= 10:
        raise ValueError("k must be an integer between 1 and 10")


class LiteratureSearch:
    """SciClaims-compatible Elasticsearch/BM25 retrieval adapter."""

    def __init__(self, client: Any, index: str):
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
            SearchHit(
                str(hit["_id"]),
                rank,
                hit["_score"],
                hit["_source"]["title"],
                hit["_source"]["abstract"],
                "elasticsearch",
            )
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
            hits.append(
                SearchHit(
                    article.pmid,
                    int(rank),
                    float(score),
                    article.title,
                    article.abstract,
                    "jina-colbert-v2",
                )
            )
        return hits


def create_search_backend(
    *,
    backend: str | None = None,
    jina_options: Mapping[str, Any] | None = None,
    article_lookup: Callable[[int], Article] | None = None,
    elastic_client: Any | None = None,
    elastic_index: str | None = None,
) -> SearchBackend:
    """Create one explicitly selected backend without silent fallback.

    If exactly one backend is configured, backend may be omitted for convenience.
    If multiple backends are configured, callers must choose one explicitly;
    configuration order never acts as an implicit priority rule.
    """

    configured = []
    if jina_options is not None:
        configured.append("jina-colbert-v2")
    if elastic_client is not None or elastic_index is not None:
        configured.append("elasticsearch")

    if backend is None:
        if not configured:
            raise ValueError("Configure a search backend")
        if len(configured) != 1:
            raise ValueError("Multiple backends configured; select backend explicitly")
        backend = configured[0]

    if backend == "jina-colbert-v2":
        if jina_options is None or not jina_options.get("index"):
            raise ValueError("Jina-ColBERT-v2 requires an index")
        if article_lookup is None:
            raise ValueError("Jina-ColBERT-v2 requires its index-specific article lookup")
        from colbert import Searcher

        return JinaColBERTSearch(Searcher(**dict(jina_options)), article_lookup)

    if backend == "elasticsearch":
        if elastic_client is None or not elastic_index:
            raise ValueError("Elasticsearch requires a client and index")
        return LiteratureSearch(elastic_client, elastic_index)

    raise ValueError(f"Unsupported search backend: {backend}")
