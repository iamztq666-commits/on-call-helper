from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.html_parser import parse_html
from core.indexer import build_index, search_keyword
from core.store import store, Document

router = APIRouter()


class DocumentIn(BaseModel):
    id: str
    html: str


@router.get("")
async def ui():
    return FileResponse("static/v1.html")


@router.post("/documents", status_code=201)
async def add_document(doc: DocumentIn):
    title, text = parse_html(doc.html)
    store.documents[doc.id] = Document(id=doc.id, title=title, text=text)

    # Auto-extract department + keywords via LLM, augment BM25 text
    augmented_text = text
    try:
        from core.keyword_extractor import extract_keywords
        kw_meta = extract_keywords(title, text)
        if kw_meta:
            store.doc_keywords[doc.id] = kw_meta
            extra = " ".join(kw_meta.get("keywords", []))
            dept = kw_meta.get("department", "")
            augmented_text = text + "\n" + dept + " " + extra
    except Exception:
        pass

    build_index(doc.id, augmented_text)

    # Phase 2: generate embedding
    try:
        from core.embedder import embed
        store.vectors[doc.id] = embed(augmented_text)
    except Exception:
        pass

    return {"id": doc.id, "title": title}


@router.get("/search")
async def search(q: str):
    results = search_keyword(q)
    return {
        "query": q,
        "results": [
            {
                "id": r.id,
                "title": r.title,
                "snippet": r.snippet,
                "score": round(r.score, 6),
            }
            for r in results
        ],
    }
