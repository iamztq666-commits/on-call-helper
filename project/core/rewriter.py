import json
import os
from openai import OpenAI

_client: OpenAI | None = None

REWRITE_PROMPT = """\
将用户的 On-Call 问题改写为更适合文档检索的表达。
只输出 JSON，不要任何解释或 markdown：
{{
  "keyword_query": "保留原问题核心技术术语，并推断受影响的团队或系统（从以下选：后端、SRE、数据库、前端、安全、AI算法、数据平台、移动端、QA、网络CDN），拼到关键词里，不加通用词（事件、问题、处理、On-Call）",
  "semantic_query": "在原问题基础上补充：同义词、故障场景词、以及推断出的团队职责领域关键词（如 后端服务、SRE基础设施、数据库DBA、前端Web、信息安全、AI算法、网络CDN），扩展语义覆盖面"
}}

用户问题：{question}
"""


def _get_client() -> OpenAI | None:
    global _client
    api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-58db0d35fe01401da9409d6c19014842")
    if not api_key:
        return None
    if _client is None:
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _client


async def rewrite_query(question: str) -> dict:
    """改写 query；若无 API 或调用失败则降级直接返回原始 query。"""
    client = _get_client()
    if client is None:
        return {"keyword_query": question, "semantic_query": question}
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=200,
            messages=[{"role": "user", "content": REWRITE_PROMPT.format(question=question)}],
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception:
        return {"keyword_query": question, "semantic_query": question}
