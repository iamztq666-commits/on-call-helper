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

## 设计思路

### 意图识别：让 LLM 做团队映射，不写规则

On-Call 场景的核心难点是词汇鸿沟：用户描述的是故障现象（"服务器挂了"、"黑客攻击"），SOP 文档却按团队组织（后端、安全、SRE）。传统做法是手写关键词→团队映射表，但面对用户的自然语言，规则很快失效。

解法是把意图映射交给 LLM：在 query 改写阶段，Prompt 要求 LLM 推断"受影响的团队"并拼入 `keyword_query`，直接利用 LLM 的领域知识做语义→团队映射：

```
用户输入："服务器挂了"
  → LLM 推断受影响团队：后端 / SRE
  → keyword_query = "服务器挂了 后端 SRE"
  → 命中文档里注入的部门关键词，正确 SOP 排到前排
```

文档入库时同理：LLM 自动提取每个 SOP 的部门标签和关键词追加到 BM25 索引，让文档侧也能主动"迎合"自然语言查询，无需人工标注。

---

### Query 改写：两路拆分，各司其职

用单一改写版本同时喂 BM25 和向量检索，两者会相互妥协——BM25 需要精确术语，向量检索需要语义丰富。解法是拆成两路独立处理：

- `keyword_query`：保留核心技术术语 + 推断团队词，过滤通用词（"问题"、"处理"、"事件"），专供 BM25
- `semantic_query`：补充同义词、故障场景词、团队职责描述，扩展语义覆盖面，专供向量检索

两路独立召回后用 RRF 融合（k=60），用排名倒数求和而非直接加权，不依赖两路分数的量纲一致，鲁棒性更好。API 调用失败时自动降级为原始 query，不阻断搜索。

---

### 澄清机制：默认信任 Agent，谨慎触发

On-Call 场景用户通常很急，过度澄清会损害体验。触发条件设计得很保守，需**同时满足**三个条件才触发：首轮对话 + 问题 ≤5 字 + 无专业术语。任一不满足就直接走 Agent。

原因：Agent 工作流第一步就读取 `index.json`（含各 SOP 的部门和关键词摘要），自己能判断该读哪个文件，不需要用户帮它缩小范围。只有问题极度模糊（单字"故障"、"挂了"）且完全无上下文，Agent 自身也无法定位时，才回退澄清。

---

### 上下文管理：sliding window + 强制保留首条

滑动窗口保留最近 10 轮对话，同时**强制保留第一条消息**：

```python
return [history[0]] + history[-(max_turns * 2 - 1):]
```

单纯保留最近 N 轮会丢失原始问题背景（比如用户第一句交代了部门），导致后续追问（"第三步怎么操作"）失去定位依据。保留首条确保原始上下文始终在窗口里，同时用滑动窗口控制 token 消耗，避免早期无关内容堆积污染当前问题。

---

### BM25 检索结果注入 Agent 上下文

Agent 每次至少两次 LLM 调用（先读 index.json，再读具体 SOP），如果选错文件还要追加调用，延迟累积明显。优化方案是把 BM25 召回结果预先注入用户消息作为 hint：

```
[用户问题] + [检索系统已找到以下可能相关的文件：sop-002.html, sop-004.html，
              请结合实际内容判断是否需要读取]
```

这不是强制 Agent 读哪些文件，而是给它一个低成本的初始方向，减少走弯路概率，同时保留 Agent 的最终判断权。

---

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

访问 http://localhost:8000/v3 ，输入"数据库主从延迟超过30秒怎么处理"，Agent 会先读 index.json，再读 sop-002.html，输出具体操作步骤。

**Harness 评测**

```bash
# 跑全部 5 个用例，返回 tool precision/recall、回答质量、幻觉率报告
curl -X POST http://localhost:8000/v3/eval \
  -H "Content-Type: application/json" \
  -d '{"strategy": "rrf+rewrite"}'

# 只跑单个用例
curl -X POST http://localhost:8000/v3/eval \
  -H "Content-Type: application/json" \
  -d '{"strategy": "rrf+rewrite", "cases": ["case-001"]}'
```

## 目录说明

```
question-1/
├── README.md          # 本文件
├── project/           # 项目代码
├── prompt/            # 所有 LLM 提示词 + AI 交互记录
└── DESIGN.md          # Prompt 脚本：项目整体架构设计，作为 AI 编码的总指令
```

> DESIGN.md 作为结构化 Prompt 脚本使用，喂给 AI 编码工具驱动整个项目的生成与迭代（各阶段详细实现指令见 `prompt/` 目录下的交互记录）。
