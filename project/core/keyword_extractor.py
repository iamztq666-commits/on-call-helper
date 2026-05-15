import json
import os
from openai import OpenAI

_client: OpenAI | None = None

EXTRACT_PROMPT = """\
分析以下 On-Call SOP 文档，提取关键信息。
只输出 JSON，不要任何解释或 markdown：
{{
  "department": "负责团队（从以下选一个：后端服务、SRE、数据库DBA、前端、安全团队、数据平台、移动端、AI算法、QA、网络CDN）",
  "keywords": ["关键技术术语1", "术语2"]
}}

keywords 要求：最多 15 个，选对这份文档最有区分度的技术词，用于 BM25 检索匹配。

文档标题：{title}
文档内容（前 600 字）：{text}
"""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-58db0d35fe01401da9409d6c19014842"),
            base_url="https://api.deepseek.com",
        )
    return _client


def extract_keywords(title: str, text: str) -> dict:
    """Return {"department": str, "keywords": list[str]}, or {} on failure."""
    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": EXTRACT_PROMPT.format(title=title, text=text[:600]),
            }],
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return {}
