from core.indexer import SearchResult


def rrf_fusion(
    results_a: list[SearchResult],
    results_b: list[SearchResult],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, doc in enumerate(results_a):
        scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (k + rank + 1)
    for rank, doc in enumerate(results_b):
        scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
