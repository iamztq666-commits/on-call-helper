# On-Call 助手 - 设计总览

## 背景
编程面试题，GitHub：https://github.com/oriengy/coding-exam/tree/main/question-1
请先读取 question-1/README.md 和 question-1/data/ 下所有文件，理解题目要求和数据格式。

---

## 技术栈
- Python 3.11+ / FastAPI
- BeautifulSoup4（HTML 解析）
- sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`（本地 embedding，支持中文）
- Anthropic SDK（query 改写 / Agent tool use / LLM-as-judge）
- numpy（余弦相似度计算）
- 全内存存储，不用数据库

---

## 项目结构
```
project/
├── main.py                  # FastAPI 入口，挂载三个路由
├── routers/
│   ├── v1.py               # Phase 1：关键词搜索
│   ├── v2.py               # Phase 2：语义搜索
│   └── v3.py               # Phase 3：Agent 对话
├── core/
│   ├── html_parser.py      # HTML 解析，提取纯文本
│   ├── indexer.py          # 倒排索引
│   ├── embedder.py         # sentence-transformers embedding
│   ├── rrf.py              # RRF 融合
│   ├── rewriter.py         # Claude query 改写
│   └── store.py            # 全局内存存储
├── agent/
│   ├── runner.py           # Agent 主循环（tool use）
│   ├── clarifier.py        # 模糊问题澄清
│   ├── tools.py            # readFile 工具定义
│   └── tracer.py           # Trace 收集
├── harness/
│   ├── cases/
│   │   └── eval_cases.json # 测试用例
│   ├── evaluators/
│   │   ├── tool_evaluator.py      # 工具调用评估
│   │   ├── answer_evaluator.py    # LLM-as-judge
│   │   └── hallucination.py       # 幻觉检测
│   ├── runner.py           # 跑评估
│   └── report.py           # 生成报告
├── static/
│   ├── v1.html             # Phase 1 前端
│   ├── v2.html             # Phase 2 前端
│   └── v3.html             # Phase 3 对话前端
├── data/                   # SOP 文件目录（sop-001.html ~ sop-010.html）
└── requirements.txt
```

---

## 全局内存存储（store.py）
所有模块共享同一个 store 单例：
- `documents: dict[str, Document]` — id → 文档（含 title、text）
- `inverted_index: dict[str, set[str]]` — 词 → doc_id set
- `vectors: dict[str, np.ndarray]` — id → embedding 向量

---

## 注意事项
- `ANTHROPIC_API_KEY` 从环境变量读取，不要硬编码
- `data/` 目录文件通过 `POST /v1/documents` 入库，服务启动时不自动加载
- `readFile` 做路径安全校验，只能读 `data/` 目录，防止路径穿越
- 所有接口加 CORS 支持
- embedding 模型首次运行自动下载（约 400MB），需要网络

---

## 开发顺序
严格按顺序执行，每步完成后等确认再继续：

1. **项目骨架** — 目录结构 + main.py + requirements.txt，不写业务逻辑
2. **html_parser.py** — 解析 HTML，跑通验证用例
3. **Phase 1** — 详见 PHASE1.md
4. **Phase 2** — 详见 PHASE2.md
5. **Phase 3** — 详见 PHASE3.md
6. **Harness** — 详见 HARNESS.md
