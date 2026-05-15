import json
import os
from openai import OpenAI

_client: OpenAI | None = None

TECH_TERMS = {
    "OOM", "主从延迟", "Pod", "CDN", "GPU", "ETL", "Spark",
    "DDoS", "DNS", "崩溃率", "热修复", "K8s", "kubernetes",
}

CLARIFY_PROMPT = """\
你是 On-Call 助手，判断用户问题是否需要澄清才能准确检索文档。

SOP 覆盖范围：
- 后端服务（OOM、超时、降级、故障分级）
- 数据库 DBA（主从延迟、慢查询、连接池、数据恢复）
- 前端（白屏、CDN 资源、兼容性、性能劣化）
- SRE（K8s、监控告警、容量规划、故障响应）
- 安全团队（入侵检测、漏洞响应、安全事件分级）
- 数据平台（ETL、Spark、数据管道故障）
- 移动端（App 崩溃、热修复、推送服务）
- AI & 算法（模型推理延迟、推荐质量、GPU 集群）
- QA（测试环境故障、自动化测试、发版卡点）
- 网络 & CDN（节点故障、DNS 异常、DDoS 防护）

用户问题：{question}
对话历史：{history}

判断是否需要澄清，只输出 JSON，不要任何解释：
{{"need_clarify": true, "reason": "问题涉及多个领域", "candidates": [{{"id": 1, "label": "后端服务问题", "icon": "🖥️", "hint": "如 OOM、服务超时"}}, {{"id": 2, "label": "数据库问题", "icon": "🗄️", "hint": "如主从延迟、慢查询"}}]}}
"""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-58db0d35fe01401da9409d6c19014842"),
            base_url="https://api.deepseek.com",
        )
    return _client


async def maybe_clarify(question: str, history: list) -> dict:
    # 只对极短且无上下文的首次问题才澄清，其余全部直接走 Agent
    # Agent 读 index.json 后自己能判断，不需要问用户
    if len(history) > 0:
        return {"type": "agent"}
    if len(question) >= 6:
        return {"type": "agent"}
    if any(term.lower() in question.lower() for term in TECH_TERMS):
        return {"type": "agent"}

    # 只剩 <= 5 字、无历史、无专业词的极短问题才尝试澄清
    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": CLARIFY_PROMPT.format(
                    question=question,
                    history="[]",
                ),
            }],
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text.strip())
        if data.get("need_clarify") and data.get("candidates"):
            return {
                "type": "clarification",
                "message": "你的问题可能涉及几个方向，请选择：",
                "candidates": data["candidates"],
            }
    except Exception:
        pass

    return {"type": "agent"}
