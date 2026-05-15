import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from core.store import store

_CJK = "一-鿿㐀-䶿"

# Build split pattern without embedding curly quotes directly in a string literal
_PUNCT = (
    "。，、；：！？"  # 。，、；：！？
    "“”‘’"                      # " " ' '
    "「」『』"                      # 「」『』
    "【】（）"                      # 【】（）
)
_SPLIT = re.compile(r"[\s" + _PUNCT + r"\[\]{}]+")
_CJK_RE = re.compile(f"[{_CJK}]+")
_TOKEN_RE = re.compile(f"[A-Za-z0-9_]+|[{_CJK}]+|[^\\sA-Za-z0-9_{_CJK}]")


@dataclass
class SearchResult:
    id: str
    title: str
    snippet: str
    score: float


def _split_tokens(text: str) -> list[str]:
    """Base split: whitespace/punctuation + ASCII/CJK boundary."""
    tokens = []
    for part in _SPLIT.split(text):
        if not part:
            continue
        tokens.extend(t for t in _TOKEN_RE.findall(part) if t)
    return tokens


def tokenize(text: str) -> list[str]:
    """For indexing: add CJK bigrams so substrings like "故障" match inside longer phrases."""
    tokens: list[str] = []
    for tok in _split_tokens(text):
        if _CJK_RE.fullmatch(tok) and len(tok) >= 2:
            tokens.append(tok)
            for i in range(len(tok) - 1):
                tokens.append(tok[i : i + 2])
        else:
            tokens.append(tok)
    return [t for t in tokens if t]


def tokenize_query(query: str) -> list[str]:
    """For querying: same bigram logic as indexing for consistent matching."""
    return tokenize(query)


def _rebuild_bm25() -> None:
    if not store.bm25_doc_ids:
        store.bm25 = None
        return
    corpus = [tokenize(store.documents[doc_id].text) for doc_id in store.bm25_doc_ids]
    store.bm25 = BM25Okapi(corpus)


def build_index(doc_id: str, text: str) -> None:
    # Keep inverted index for special-char queries (e.g. &)
    for word in set(tokenize(text)):
        store.inverted_index.setdefault(word, set()).add(doc_id)
    # BM25
    if doc_id not in store.bm25_doc_ids:
        store.bm25_doc_ids.append(doc_id)
    _rebuild_bm25()


def extract_snippet(query_words: list[str], text: str, window: int = 50) -> str:
    flat = text.replace("\n", " ")
    for qw in query_words:
        idx = flat.find(qw)
        if idx != -1:
            start = max(0, idx - window)
            end = min(len(flat), idx + len(qw) + window)
            return flat[start:end]
    return flat[:100]


def search_keyword(query: str) -> list[SearchResult]:
    query_tokens = tokenize_query(query)

    if store.bm25 and store.bm25_doc_ids:
        scores = store.bm25.get_scores(query_tokens)
        results = []
        for i, doc_id in enumerate(store.bm25_doc_ids):
            s = float(scores[i])
            if s > 0:
                doc = store.documents[doc_id]
                results.append(SearchResult(
                    id=doc_id,
                    title=doc.title,
                    snippet=extract_snippet(query_tokens, doc.text),
                    score=s,
                ))
        return sorted(results, key=lambda x: x.score, reverse=True)

    # Fallback: inverted-index (handles special chars like &)
    # Use both query tokens and their bigrams for recall
    query_tokens_expanded = tokenize(query)
    matched: set[str] = set()
    for w in query_tokens_expanded:
        matched |= store.inverted_index.get(w, set())
    results = []
    for doc_id in matched:
        doc = store.documents[doc_id]
        count = sum(doc.text.count(w) for w in query_tokens)
        score = count / len(doc.text) if doc.text else 0.0
        results.append(SearchResult(
            id=doc_id, title=doc.title,
            snippet=extract_snippet(query_tokens, doc.text),
            score=score,
        ))
    return sorted(results, key=lambda x: x.score, reverse=True)
