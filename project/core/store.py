from dataclasses import dataclass, field
from typing import Any
import numpy as np


@dataclass
class Document:
    id: str
    title: str
    text: str


class Store:
    def __init__(self):
        self.documents: dict[str, Document] = {}
        self.inverted_index: dict[str, set[str]] = {}
        self.vectors: dict[str, np.ndarray] = {}
        self.doc_keywords: dict[str, dict] = {}  # doc_id → {"department": str, "keywords": list}
        # BM25
        self.bm25_doc_ids: list[str] = []   # ordered, maps index → doc_id
        self.bm25: Any = None               # BM25Okapi instance, rebuilt on each ingest


store = Store()
