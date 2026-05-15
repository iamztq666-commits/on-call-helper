# On-Call 助手

AI 编程面试题实现，基于 FastAPI + DeepSeek 的三阶段 On-Call 文档检索与问答系统。

## 快速启动

```bash
cd project
pip install -r requirements.txt
python -m uvicorn main:app --port 8000 --reload
```

启动后加载文档（每次重启都需要执行，文档存内存）：

```bash
python - <<'EOF'
import json, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(1, 11):
    with open(f"data/sop-{i:03d}.html", encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps({"id": f"sop-{i:03d}", "html": html}).encode()
    req = urllib.request.Request("http://localhost:8000/v1/documents", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req) as resp:
        r = json.load(resp)
    print(f"{r['id']}: {r['title']}")
EOF
```

## 三个入口

| 地址 | 功能 |
|------|------|
| http://localhost:8000/v1 | Phase 1：关键词搜索（BM25） |
| http://localhost:8000/v2 | Phase 2：语义搜索（BM25 + 向量 + RRF） |
| http://localhost:8000/v3 | Phase 3：On-Call Agent 对话 |

## 环境变量

```bash
export DEEPSEEK_API_KEY=sk-xxxxxxx   # 不设置时用代码内置的 fallback key
```

## 项目结构

```
project/
├── main.py                        # FastAPI 入口，lifespan 启动时生成 index.json
├── requirements.txt
├── routers/
│   ├── v1.py                      # POST /v1/documents, GET /v1/search
│   ├── v2.py                      # GET /v2/search（改写 + 双路召回 + RRF）
│   └── v3.py                      # POST /v3/chat（SSE 流式）
├── core/
│   ├── store.py                   # 全局内存单例
│   ├── html_parser.py             # BeautifulSoup 解析，去除 script/style
│   ├── indexer.py                 # BM25 + CJK bigram tokenizer
│   ├── embedder.py                # sentence-transformers 向量搜索
│   ├── rewriter.py                # DeepSeek query 改写（含团队意图推断）
│   ├── rrf.py                     # Reciprocal Rank Fusion
│   ├── keyword_extractor.py       # DeepSeek 自动提取文档关键词（支持任意数量文档）
│   └── indexer_utils.py           # 启动时扫描 data/ 生成 index.json
├── agent/
│   ├── runner.py                  # DeepSeek tool use 循环，SSE 流式输出
│   ├── clarifier.py               # 极短问题澄清（≤5字才触发）
│   ├── tools.py                   # readFile 工具定义
│   └── tracer.py                  # AgentTrace 记录
├── harness/
│   ├── cases/eval_cases.json      # 5 个评测用例
│   ├── evaluators/
│   │   ├── tool_evaluator.py      # 工具调用精召率
│   │   ├── answer_evaluator.py    # LLM-as-judge（准确性/完整性/可操作性）
│   │   └── hallucination.py       # 幻觉检测
│   ├── runner.py
│   └── report.py
├── static/
│   ├── v1.html
│   ├── v2.html
│   └── v3.html
└── data/
    ├── index.json                 # 启动自动生成，Agent 路由用
    └── sop-001.html ~ sop-010.html
```

## 技术实现

### Phase 1：关键词搜索
- HTML 解析：BeautifulSoup4，自动去除 `<script>/<style>/<noscript>`
- 分词：CJK bigram + ASCII 词边界切分，支持中英混合
- 排序：BM25Okapi（rank-bm25），含 IDF 权重和文档长度归一化

### Phase 2：语义搜索
- Query 改写：DeepSeek 生成 `keyword_query`（含团队意图推断）+ `semantic_query`（扩展语义）
- 双路召回：BM25 用 `keyword_query`，向量搜索用 `semantic_query`
- 向量模型：`paraphrase-multilingual-MiniLM-L12-v2`，归一化后点积 = 余弦相似度
- 融合：RRF（k=60），两路结果倒数排名求和
- 文档增强：每个 SOP 注入部门关键词 div，解决文档词汇与查询词汇不匹配问题；新文档入库时 LLM 自动提取关键词追加到索引

### Phase 3：On-Call Agent
- 模型：DeepSeek deepseek-chat，OpenAI 兼容接口
- 工具：`readFile(fname)`，支持读取 `index.json` 和 `sop-*.html`
- 流程：先读 index.json 了解文档目录 → 按需读具体 SOP → 给出处理步骤
- 输出：SSE 流式，前端实时显示 tool_call 和 answer 两个阶段
- 上下文：sliding window，保留最近 10 轮

### Harness 评测
- 工具调用：precision / recall / efficiency / first_hit_rank
- 回答质量：LLM-as-judge，三维度打分（准确性/完整性/可操作性）
- 幻觉检测：对比 Agent 回答与实际读取的文档内容

## 验证用例

**Phase 1 BM25**

```bash
curl "http://localhost:8000/v1/search?q=OOM"            # → sop-001 靠前
curl "http://localhost:8000/v1/search?q=故障"            # → 多篇命中
curl "http://localhost:8000/v1/search?q=CDN"            # → sop-003, sop-010
```

**Phase 2 语义搜索**

```bash
curl "http://localhost:8000/v2/search?q=服务器挂了"      # → sop-001(后端), sop-004(SRE) 靠前
curl "http://localhost:8000/v2/search?q=黑客攻击"        # → sop-005(安全) 靠前
curl "http://localhost:8000/v2/search?q=机器学习模型出问题" # → sop-008(AI算法) 靠前
```

**Phase 3 Agent**

访问 http://localhost:8000/v3，输入"数据库主从延迟超过30秒怎么处理"，Agent 会先读 index.json，再读 sop-002.html，输出具体操作步骤。

## 目录说明

```
question-1/
├── README.md          # 本文件
├── project/           # 项目代码
├── prompt/            # 所有 LLM 提示词 + AI 交互记录
├── DESIGN.md          # 原题设计文档
├── PHASE1~3.md        # 原题各阶段说明
└── HARNESS.md         # 原题评测框架说明
```
