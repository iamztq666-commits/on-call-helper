import numpy as np
from sentence_transformers import SentenceTransformer

from core.indexer import extract_snippet, SearchResult
from core.store import store

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model


def embed(text: str) -> np.ndarray:
    return _get_model().encode(text, normalize_embeddings=True)


def vector_search(query: str, top_k: int = 10) -> list[SearchResult]:
    if not store.vectors:
        return []
    query_vec = embed(query)
    scores: dict[str, float] = {
        doc_id: float(np.dot(query_vec, vec))
        for doc_id, vec in store.vectors.items()
    }
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [
        SearchResult(
            id=doc_id,
            title=store.documents[doc_id].title,
            snippet=extract_snippet([], store.documents[doc_id].text),
            score=score,
        )
        for doc_id, score in ranked
    ]
