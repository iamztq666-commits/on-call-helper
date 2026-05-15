import json
import os
from openai import OpenAI

from agent.tools import execute_read_file
from agent.tracer import AgentTrace

_client: OpenAI | None = None

HALLUCINATION_PROMPT = """\
判断 On-Call 助手的回答中是否存在幻觉（即无法从检索到的文档中找到来源的信息）。

Agent 读取到的文档内容：
{retrieved_content}

Agent 的回答：
{answer}

只输出 JSON，不要任何解释：
{{"has_hallucination": false, "hallucinated_parts": [], "confidence": 0.95}}
"""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-58db0d35fe01401da9409d6c19014842"),
            base_url="https://api.deepseek.com",
        )
    return _client


def evaluate(trace: AgentTrace) -> dict:
    if not trace.tool_calls:
        return {"has_hallucination": True, "hallucinated_parts": ["未读取任何文件"], "confidence": 0.5}

    retrieved = "\n\n".join([
        f"=== {t.fname} ===\n{execute_read_file(t.fname)}"
        for t in trace.tool_calls
    ])

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": HALLUCINATION_PROMPT.format(
                    retrieved_content=retrieved[:4000],
                    answer=trace.final_answer[:2000],
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
        return {"has_hallucination": False, "hallucinated_parts": [], "confidence": 0.5, "error": str(e)}
