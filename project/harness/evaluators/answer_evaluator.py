import json
import os
from openai import OpenAI

from agent.tools import execute_read_file
from agent.tracer import AgentTrace

_client: OpenAI | None = None

JUDGE_PROMPT = """\
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


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-58db0d35fe01401da9409d6c19014842"),
            base_url="https://api.deepseek.com",
        )
    return _client


def evaluate(trace: AgentTrace, case: dict) -> dict:
    reference = "\n\n".join([
        execute_read_file(t.fname)
        for t in trace.tool_calls
        if t.fname in case["expected_files"]
    ])
    if not reference:
        return {"accuracy": 0, "completeness": 0, "actionability": 0, "overall": 0}

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=trace.question,
                    answer=trace.final_answer[:2000],
                    reference=reference[:3000],
                ),
            }],
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        return {"accuracy": 0, "completeness": 0, "actionability": 0, "overall": 0, "error": str(e)}
