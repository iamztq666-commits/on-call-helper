from fastapi import APIRouter
from fastapi.responses import FileResponse

from core.embedder import vector_search
from core.indexer import extract_snippet, search_keyword
from core.rewriter import rewrite_query
from core.rrf import rrf_fusion
from core.store import store

router = APIRouter()


@router.get("")
async def ui():
    return FileResponse("static/v2.html")


@router.get("/search")
async def search(q: str):
    # 1. Query rewrite
    rewritten = await rewrite_query(q)
    keyword_q = rewritten["keyword_query"]
    semantic_q = rewritten["semantic_query"]

    # 2. Dual recall
    keyword_q = rewritten["keyword_query"]
    results_a = search_keyword(keyword_q)
    results_b = vector_search(semantic_q)

    # 3. RRF fusion
    fused = rrf_fusion(results_a, results_b)

    # 4. Assemble response
    results = []
    for doc_id, score in fused:
        doc = store.documents[doc_id]
        results.append({
            "id": doc_id,
            "title": doc.title,
            "snippet": extract_snippet([q], doc.text),
            "score": round(score, 4),
        })

    return {"query": q, "rewritten": rewritten, "results": results}
