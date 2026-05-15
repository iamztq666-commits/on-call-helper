# Prompt 5：LLM-as-Judge 回答质量评估（harness/evaluators/answer_evaluator.py）

**用途**：Harness 自动评测中，用 LLM 对 Agent 回答打分，替代人工评审。

**触发时机**：运行 Harness 评测时，对每个 case 的 Agent 回答调用一次

**模型**：DeepSeek deepseek-chat

---

```
你是严格的技术评审，评估 On-Call 助手的回答质量。

用户问题：{question}
Agent 回答：{answer}
参考文档内容：{reference}

从以下三个维度打分，每项 0-10 分：
1. 准确性（accuracy）：回答内容是否符合 SOP 文档，有无错误信息
2. 完整性（completeness）：关键处理步骤是否都覆盖到了
3. 可操作性（actionability）：工程师能否直接按回答执行操作

只输出 JSON，不要任何解释：
{"accuracy": 8, "completeness": 7, "actionability": 9, "overall": 8}
```

---

# Prompt 6：幻觉检测（harness/evaluators/hallucination.py）

**用途**：检测 Agent 回答中是否包含无法从检索文档中找到来源的信息。

---

```
判断 On-Call 助手的回答中是否存在幻觉（即无法从检索到的文档中找到来源的信息）。

Agent 读取到的文档内容：
{retrieved_content}

Agent 的回答：
{answer}

只输出 JSON，不要任何解释：
{"has_hallucination": false, "hallucinated_parts": [], "confidence": 0.95}
```
