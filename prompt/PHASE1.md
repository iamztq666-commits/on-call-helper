# Phase 1：关键词搜索引擎

## API

```
POST /v1/documents
Body: { "id": "sop-001", "html": "<html>...</html>" }
→ 201 { "id": "sop-001", "title": "后端服务 On-Call SOP" }

GET /v1/search?q={query}
→ 200 { "query": "...", "results": [{ "id": "...", "title": "...", "snippet": "...", "score": 1.0 }] }

GET /v1
→ 返回 static/v1.html
```

---

## HTML 解析规则（html_parser.py）

1. 用 BeautifulSoup4 解析
2. 剔除 `<script>`、`<style>`、`<noscript>` 标签及其全部内容
3. 自动解析 HTML 实体（`&amp;` → `&`，`&lt;` → `<` 等）—— BeautifulSoup 默认处理
4. 提取 `<title>` 标签文字作为标题，没有则取第一个 `<h1>`
5. 用 `soup.get_text(separator="\n", strip=True)` 提取纯文本

```python
def parse_html(html: str) -> tuple[str, str]:
    # 返回 (title, plain_text)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
    elif soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    text = soup.get_text(separator="\n", strip=True)
    return title, text
```

---

## 倒排索引逻辑（indexer.py）

### 建索引
- 分词：按空格 + 常见标点切分，不引入 jieba
- 每个词映射到包含该词的 doc_id set
- 同步存入 `store.inverted_index`

### 搜索
- query 分词后查倒排索引，取所有命中文档的并集
- score = 关键词在该文档出现次数 / 文档总词数（TF）
- snippet = 第一个关键词在文本中出现位置的前后各 50 字符
- 结果按 score 降序排列

```python
def build_index(doc_id: str, text: str):
    words = tokenize(text)
    for word in set(words):
        store.inverted_index.setdefault(word, set()).add(doc_id)

def search_keyword(query: str) -> list[SearchResult]:
    query_words = tokenize(query)
    matched_docs = set()
    for word in query_words:
        matched_docs |= store.inverted_index.get(word, set())
    results = []
    for doc_id in matched_docs:
        doc = store.documents[doc_id]
        score = calc_tf(query_words, doc.text)
        snippet = extract_snippet(query_words, doc.text)
        results.append(SearchResult(id=doc_id, title=doc.title, snippet=snippet, score=score))
    return sorted(results, key=lambda x: x.score, reverse=True)
```

---

## 验证用例（必须全部通过）

| 查询 | 期望结果 |
|------|---------|
| `GET /v1/search?q=OOM` | 返回 sop-001 |
| `GET /v1/search?q=故障` | 返回多个文档 |
| `GET /v1/search?q=replication` | 返回空（该词仅在 script 标签内） |
| `GET /v1/search?q=CDN` | 返回 sop-003, sop-010 |
| `GET /v1/search?q=&` | 返回正文中含 & 字符的文档 |

---

## 前端（static/v1.html）
- 搜索输入框 + 搜索按钮
- 结果列表：标题 + snippet + score
- 简洁即可，无特殊要求
