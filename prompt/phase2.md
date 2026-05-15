# Phase 2：语义搜索 + 多路召回

## API

```
GET /v2/search?q={query}
→ 200 { "query": "...", "rewritten": { "keyword_query": "...", "semantic_query": "..." }, "results": [{ "id": "...", "title": "...", "snippet": "...", "score": 0.87 }] }

GET /v2
→ 返回 static/v2.html
```

---

## 核心流程

```
用户 query
    ↓
DeepSeek 改写 → [keyword_query（含团队推断）, semantic_query（扩展语义）]
    ↓                           ↓
BM25（keyword_query）      向量余弦相似度（semantic_query）
（sentence-transformers）
    ↓                           ↓
结果 A                      结果 B
    └──────── RRF 融合 ────────┘
                  ↓
              最终排序结果
```

---

## Step 0：入库时自动提取关键词（core/keyword_extractor.py）

**问题**：文档原文使用的词汇与用户查询不一致（如 sop-001 原文没有"服务器"，用户搜"服务器挂了"就命中不了）。手写关键词只适用于 10 个 demo 文档，100 个文档无法维护。

**方案**：文档入库时，自动调用 DeepSeek 提取部门 + 关键词，追加到 BM25 索引文本和 index.json，无需人工标注。

```python
# core/keyword_extractor.py
EXTRACT_PROMPT = """\
分析以下 On-Call SOP 文档，提取关键信息。
只输出 JSON：
{{
  "department": "负责团队（后端服务/SRE/数据库DBA/前端/安全团队/数据平台/移动端/AI算法/QA/网络CDN）",
  "keywords": ["关键技术术语1", "术语2", ...]   // 最多 15 个，区分度高的技术词
}}

文档标题：{title}
文档内容（前 600 字）：{text}
"""

def extract_keywords(title: str, text: str) -> dict:
    # 调用 DeepSeek，失败返回 {}，不阻断入库
    ...
```

**入库流程更新（routers/v1.py）**：

```python
@router.post("/documents", status_code=201)
async def add_document(doc: DocumentIn):
    title, text = parse_html(doc.html)
    store.documents[doc.id] = Document(id=doc.id, title=title, text=text)

    # 自动提取关键词，追加到 BM25 索引文本
    augmented_text = text
    kw_meta = extract_keywords(title, text)
    if kw_meta:
        store.doc_keywords[doc.id] = kw_meta
        extra = " ".join(kw_meta.get("keywords", []))
        dept  = kw_meta.get("department", "")
        augmented_text = text + "\n" + dept + " " + extra   # 追加，不替换原文

    build_index(doc.id, augmented_text)      # BM25 用增强文本
    store.vectors[doc.id] = embed(augmented_text)  # 向量也用增强文本
    return {"id": doc.id, "title": title}
```

**index.json 同步更新（core/indexer_utils.py）**：

启动时扫描 `data/` 目录生成 index.json，自动调用 `extract_keywords`，把 department 和 keywords 写进每个条目，供 Agent 路由使用：

```json
{
  "fname": "sop-001.html",
  "title": "后端服务 On-Call SOP",
  "summary": "...",
  "department": "后端服务",
  "keywords": ["OOM", "服务超时", "降级策略", "故障分级", "服务器崩溃"]
}
```

**扩展性**：新增任意文档只需 POST /v1/documents，系统自动提取关键词入索引，无需修改任何配置。

---

## Step 1：Embedding 入库（core/embedder.py）

`POST /v1/documents` 入库时，同步生成 embedding 存入 `store.vectors`：

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def embed(text: str) -> np.ndarray:
    return model.encode(text, normalize_embeddings=True)

def vector_search(query: str, top_k: int = 10) -> list[SearchResult]:
    query_vec = embed(query)
    scores = {
        doc_id: float(np.dot(query_vec, vec))
        for doc_id, vec in store.vectors.items()
    }
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [SearchResult(id=doc_id, ...) for doc_id, score in ranked]
```

---

## Step 2：Query 改写（core/rewriter.py）

使用 DeepSeek（OpenAI 兼容接口）把用户 query 改写为两个版本。

**关键设计**：`keyword_query` 除了保留技术术语，还让 LLM 推断受影响的团队/系统，直接利用 LLM 的领域知识做意图映射，无需手写规则。

```python
REWRITE_PROMPT = """\
将用户的 On-Call 问题改写为更适合文档检索的表达。
只输出 JSON，不要任何解释或 markdown：
{{
  "keyword_query": "保留原问题核心技术术语，并推断受影响的团队或系统
                   （从以下选：后端、SRE、数据库、前端、安全、AI算法、数据平台、移动端、QA、网络CDN），
                   拼到关键词里，不加通用词（事件、问题、处理、On-Call）",
  "semantic_query": "补充同义词、故障场景词、以及推断出的团队职责领域关键词，扩展语义覆盖面"
}}

用户问题：{question}
"""

# 示例：query = "服务器挂了"
# keyword_query → "服务器挂了 后端 SRE"        （LLM 推断受影响团队）
# semantic_query → "服务器宕机 后端服务 SRE基础设施 服务不可用 故障排除"
```

改写失败时降级返回原始 query，不影响搜索可用性。

---

## Step 3：RRF 融合（core/rrf.py）

```python
def rrf_fusion(
    results_a: list[SearchResult],
    results_b: list[SearchResult],
    k: int = 60
) -> list[tuple[str, float]]:
    scores = {}
    for rank, doc in enumerate(results_a):
        scores[doc.id] = scores.get(doc.id, 0) + 1 / (k + rank + 1)
    for rank, doc in enumerate(results_b):
        scores[doc.id] = scores.get(doc.id, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

---

## 完整搜索流程（routers/v2.py）

```python
@router.get("/search")
async def search(q: str):
    # 1. query 改写（含团队推断）
    rewritten = await rewrite_query(q)
    keyword_q = rewritten["keyword_query"]   # 含推断团队，喂给 BM25
    semantic_q = rewritten["semantic_query"] # 扩展语义，喂给向量

    # 2. 双路召回
    results_a = search_keyword(keyword_q)   # BM25：用改写后的 keyword_query
    results_b = vector_search(semantic_q)   # 向量：用扩展语义

    # 3. RRF 融合
    fused = rrf_fusion(results_a, results_b)

    # 4. 组装返回
    results = []
    for doc_id, score in fused:
        doc = store.documents[doc_id]
        results.append({
            "id": doc_id,
            "title": doc.title,
            "snippet": extract_snippet([q], doc.text),
            "score": round(score, 4)
        })
    return {"query": q, "rewritten": rewritten, "results": results}
```

**注意**：BM25 使用 `keyword_query`（含推断团队词），而非原始 `q`。这是为了让 LLM 推断出的"后端"、"SRE"等词，能命中文档里注入的关键词 div，把正确部门的文档拉到前排。

---

## 验证结果

| 查询 | keyword_query（LLM推断） | Top 1 | Top 2 |
|------|--------------------------|-------|-------|
| `服务器挂了` | 服务器挂了 后端 SRE | sop-004 SRE ✓ | sop-001 后端 ✓ |
| `黑客攻击` | 黑客攻击 安全 | sop-005 安全 ✓ | — |
| `机器学习模型出问题` | 机器学习模型 故障 AI算法 | sop-008 AI算法 ✓ | — |

---

## 前端（static/v2.html）

搜索框 + 结果列表，显示 `keyword_query` / `semantic_query` 改写结果，标注 Phase 2 语义搜索。
