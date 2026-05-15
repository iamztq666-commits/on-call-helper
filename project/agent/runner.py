import json
import os
import time
from openai import AsyncOpenAI

from agent.tools import TOOLS, execute_read_file
from agent.tracer import AgentTrace, ToolCall, save_trace

_client: AsyncOpenAI | None = None

SYSTEM_PROMPT = """\
你是专业的 On-Call 助手，帮助工程师快速定位和解决线上问题。

你只有一个工具 readFile(fname)，可读取 data/ 目录下的文件。

工作流程（严格遵守）：
1. 先调用 readFile("index.json") 获取所有可用 SOP 文档的标题和摘要
2. 根据摘要判断哪些文件与问题相关，按文件名逐一读取
3. 综合文档内容给出处理步骤

回答要求：
- 必须先读文件，不能凭记忆回答
- 回答简洁，只给关键步骤，不要大段背景介绍
- 用编号列表，每条不超过两行
- 总字数控制在 300 字以内
"""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-58db0d35fe01401da9409d6c19014842"),
            base_url="https://api.deepseek.com",
        )
    return _client


def sliding_window(history: list, max_turns: int = 10) -> list:
    if len(history) <= max_turns * 2:
        return history
    return [history[0]] + history[-(max_turns * 2 - 1):]


def _build_messages(question: str, history: list) -> list:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs += sliding_window(history)
    msgs.append({"role": "user", "content": question})
    return msgs


async def run_agent(question: str, history: list, strategy: str = "rrf+rewrite"):
    """Async generator yielding SSE-ready dicts for /v3/chat."""
    trace = AgentTrace(question=question, strategy=strategy)
    start = time.time()
    messages = _build_messages(question, history)

    while True:
        response = await _get_client().chat.completions.create(
            model="deepseek-chat",
            max_tokens=600,
            tools=TOOLS,
            messages=messages,
        )
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            tc_list = choice.message.tool_calls or []
            # Append assistant turn (must include tool_calls field)
            messages.append({
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tc_list
                ],
            })
            for tc in tc_list:
                fname = json.loads(tc.function.arguments).get("fname", "")
                yield {"type": "tool_call", "fname": fname}
                content = execute_read_file(fname)
                trace.tool_calls.append(ToolCall(fname=fname, result_length=len(content)))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                })

        else:  # stop / end_turn
            final = choice.message.content or ""
            trace.final_answer = final
            trace.latency = time.time() - start
            trace.token_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
            save_trace(trace)
            yield {"type": "answer", "message": final}
            yield {"type": "done"}
            return


async def run_agent_for_eval(question: str, strategy: str, case_id: str) -> AgentTrace:
    """Non-streaming version used by harness."""
    trace = AgentTrace(question=question, strategy=strategy, case_id=case_id)
    start = time.time()
    messages = _build_messages(question, [])

    while True:
        response = await _get_client().chat.completions.create(
            model="deepseek-chat",
            max_tokens=600,
            tools=TOOLS,
            messages=messages,
        )
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            tc_list = choice.message.tool_calls or []
            messages.append({
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tc_list
                ],
            })
            for tc in tc_list:
                fname = json.loads(tc.function.arguments).get("fname", "")
                content = execute_read_file(fname)
                trace.tool_calls.append(ToolCall(fname=fname, result_length=len(content)))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        else:
            trace.final_answer = choice.message.content or ""
            trace.latency = time.time() - start
            trace.token_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
            save_trace(trace)
            return trace
