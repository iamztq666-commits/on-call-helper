# Agent Harness 评估框架

## 触发方式

```
POST /v3/eval
Body: { "strategy": "rrf+rewrite", "cases": ["case-001", "case-002"] }
不传 cases 则跑全部用例

→ 返回完整评估报告（JSON + 文字报告）
```

---

## 测试用例（harness/cases/eval_cases.json）

```json
[
  {
    "id": "case-001",
    "question": "数据库主从延迟超过30秒怎么处理？",
    "expected_files": ["sop-002.html"],
    "expected_keywords": ["主从延迟", "只读", "延迟监控"],
    "max_tool_calls": 3,
    "tags": ["database", "p1"]
  },
  {
    "id": "case-002",
    "question": "P0故障的响应流程是什么？",
    "expected_files": ["sop-001.html", "sop-004.html"],
    "expected_keywords": ["P0", "响应", "升级"],
    "max_tool_calls": 5,
    "tags": ["multi-doc", "p0"]
  },
  {
    "id": "case-003",
    "question": "推荐结果质量下降了",
    "expected_files": ["sop-008.html"],
    "expected_keywords": ["推荐", "模型", "降级"],
    "max_tool_calls": 3,
    "tags": ["ai", "quality"]
  },
  {
    "id": "case-004",
    "question": "怀疑有人入侵了系统",
    "expected_files": ["sop-005.html"],
    "expected_keywords": ["入侵", "安全事件", "响应流程"],
    "max_tool_calls": 3,
    "tags": ["security", "p0"]
  },
  {
    "id": "case-005",
    "question": "服务OOM了怎么办？",
    "expected_files": ["sop-001.html"],
    "expected_keywords": ["OOM", "内存", "堆栈"],
    "max_tool_calls": 3,
    "tags": ["backend", "p1"]
  }
]
```

---

## Trace 数据结构（agent/tracer.py）

Agent 每次运行自动记录 trace，供 Harness 使用：

```python
from dataclasses import dataclass, field
import time

@dataclass
class ToolCall:
    fname: str
    result_length: int
    timestamp: float = field(default_factory=time.time)

@dataclass
class AgentTrace:
    case_id: str = ""
    question: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer: str = ""
    latency: float = 0.0          # 总耗时（秒）
    token_usage: dict = field(default_factory=dict)  # input_tokens / output_tokens
    strategy: str = "rrf+rewrite"
    timestamp: float = field(default_factory=time.time)

# trace 存在内存列表里，供 /v3/eval 读取
trace_store: list[AgentTrace] = []

def save_trace(trace: AgentTrace):
    trace_store.append(trace)
```

---

## 三个评估器

### 1. tool_evaluator.py（规则 based，快速）

评估 Agent 的工具调用行为是否合理：

```python
def evaluate(trace: AgentTrace, case: dict) -> dict:
    actual = [t.fname for t in trace.tool_calls]
    expected = case["expected_files"]

    # 精确率：读的文件中有多少是对的
    precision = (
        len(set(actual) & set(expected)) / len(actual)
        if actual else 0.0
    )

    # 召回率：期望的文件有多少被读到了
    recall = len(set(actual) & set(expected)) / len(expected)

    # 效率：是否在 max_tool_calls 内完成
    efficiency = 1.0 if len(actual) <= case["max_tool_calls"] else 0.5

    # 首命中：第一个读的文件是否在期望列表里
    first_hit = (actual[0] in expected) if actual else False

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "efficiency": efficiency,
        "first_hit": first_hit,
        "actual_files": actual,
        "expected_files": expected
    }
```

### 2. answer_evaluator.py（LLM-as-judge）

用 Claude 评估回答质量，解决开放式回答无法用规则评估的问题：

```python
JUDGE_PROMPT = """
你是严格的技术评审，评估 On-Call 助手的回答质量。

用户问题：{question}
Agent 回答：{answer}
参考文档内容：{reference}

从以下三个维度打分，每项 0-10 分：
1. 准确性（accuracy）：回答内容是否符合 SOP 文档，有无错误信息
2. 完整性（completeness）：关键处理步骤是否都覆盖到了
3. 可操作性（actionability）：工程师能否直接按回答执行操作

只输出 JSON，不要任何解释：
{{"accuracy": 8, "completeness": 7, "actionability": 9, "overall": 8}}
"""

def evaluate(trace: AgentTrace, case: dict) -> dict:
    # 把 Agent 读取的所有文件内容拼起来作为参考
    reference = "\n\n".join([
        execute_read_file(t.fname)
        for t in trace.tool_calls
        if t.fname in case["expected_files"]
    ])

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": JUDGE_PROMPT.format(
                question=trace.question,
                answer=trace.final_answer,
                reference=reference[:3000]  # 避免超长
            )
        }]
    )
    return json.loads(response.content[0].text)
```

### 3. hallucination.py（幻觉检测）

检测回答中是否有无法从检索文档找到来源的内容：

```python
HALLUCINATION_PROMPT = """
判断 On-Call 助手的回答中是否存在幻觉（即无法从检索到的文档中找到来源的信息）。

Agent 读取到的文档内容：
{retrieved_content}

Agent 的回答：
{answer}

只输出 JSON，不要任何解释：
{{"has_hallucination": false, "hallucinated_parts": [], "confidence": 0.95}}
"""

def evaluate(trace: AgentTrace) -> dict:
    retrieved = "\n\n".join([
        f"=== {t.fname} ===\n{execute_read_file(t.fname)}"
        for t in trace.tool_calls
    ])

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": HALLUCINATION_PROMPT.format(
                retrieved_content=retrieved[:4000],
                answer=trace.final_answer
            )
        }]
    )
    return json.loads(response.content[0].text)
```

---

## Harness Runner（harness/runner.py）

支持对比多个策略：

```python
class HarnessRunner:
    def __init__(self, cases_path: str = "harness/cases/eval_cases.json"):
        with open(cases_path) as f:
            self.all_cases = json.load(f)

    async def run(
        self,
        strategies: list[str] = ["baseline", "rrf+rewrite"],
        case_ids: list[str] = None
    ) -> dict:
        cases = self.all_cases
        if case_ids:
            cases = [c for c in cases if c["id"] in case_ids]

        results = {}
        for strategy in strategies:
            strategy_results = []
            for case in cases:
                start = time.time()

                # 用指定策略跑 Agent
                trace = await run_agent_for_eval(
                    question=case["question"],
                    strategy=strategy,
                    case_id=case["id"]
                )
                trace.latency = time.time() - start

                # 三个评估器
                tool_score = tool_evaluator.evaluate(trace, case)
                answer_score = answer_evaluator.evaluate(trace, case)
                hallucination = hallucination_evaluator.evaluate(trace)

                strategy_results.append({
                    "case_id": case["id"],
                    "question": case["question"],
                    "tool": tool_score,
                    "answer": answer_score,
                    "hallucination": hallucination,
                    "latency": round(trace.latency, 2),
                    "tokens": trace.token_usage
                })

            results[strategy] = strategy_results

        return generate_report(results)
```

---

## 报告格式（harness/report.py）

```
============ Harness Report ============
运行时间：2024-01-15 14:32:00
用例数量：5

策略对比：
                      baseline    rrf+rewrite
tool_precision          0.75        0.92    ✅ +0.17
tool_recall             0.80        0.95    ✅ +0.15
first_hit_rate          0.60        0.80    ✅ +0.20
answer_quality          6.2         7.8     ✅ +1.6
hallucination_rate      0.20        0.08    ✅ -0.12
avg_latency             3.2s        4.1s    ⚠️ +0.9s（query改写额外耗时）
avg_tokens              1200        1580    ⚠️ +380

Case 详情（rrf+rewrite 策略）：
case-001 ✅  precision=1.0  quality=8.5  hallucination=false  latency=3.8s
case-002 ⚠️  precision=0.5  quality=6.0  hallucination=false  latency=5.2s
             ↑ 只读了 sop-001，漏读 sop-004
case-003 ✅  precision=1.0  quality=7.2  hallucination=false  latency=3.5s
case-004 ✅  precision=1.0  quality=8.0  hallucination=false  latency=3.9s
case-005 ✅  precision=1.0  quality=8.8  hallucination=false  latency=3.2s

结论：rrf+rewrite 策略在精确率、召回率、回答质量、幻觉率均优于 baseline，
     代价是额外 ~0.9s 延迟和 ~380 tokens 开销，整体值得。
========================================
```

---

## 给 Claude Code 的指令

实现 Harness 时请按以下顺序：

1. `agent/tracer.py` — Trace 数据结构 + save_trace
2. `harness/cases/eval_cases.json` — 5 个测试用例
3. `harness/evaluators/tool_evaluator.py` — 规则评估
4. `harness/evaluators/answer_evaluator.py` — LLM-as-judge
5. `harness/evaluators/hallucination.py` — 幻觉检测
6. `harness/runner.py` — 串联三个评估器
7. `harness/report.py` — 生成格式化报告
8. `POST /v3/eval` 接口 — 暴露给外部调用
