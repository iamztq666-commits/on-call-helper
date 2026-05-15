# Phase 3：On-Call Agent

## API

```
GET /v3
→ 返回 static/v3.html

POST /v3/chat
Body: { "message": "...", "session_id": "...", "history": [...] }
→ SSE 流式返回（text/event-stream）

POST /v3/eval
Body: { "strategy": "rrf+rewrite", "cases": ["case-001"] }
→ 触发 Harness 评估，返回报告（详见 HARNESS.md）
```

---

## 整体流程

```
用户发送消息
    ↓
clarifier.py 判断是否模糊
    ↓              ↓
模糊            清晰
返回候选项      走 Agent 主循环
    ↓              ↓
用户选择       runner.py tool use 循环
    ↓              ↓
拼接成清晰问题  SSE 流式输出工具调用 + 回答
```

---

## 澄清模块（agent/clarifier.py）

### 跳过澄清的条件（满足任一即跳过）
- `len(history) > 2`（多轮对话，上下文已足够）
- 问题包含明确技术术语：`OOM、主从延迟、Pod、CDN、GPU、ETL、Spark、DDoS、DNS、崩溃率、热修复` 等

### 触发澄清的条件
- 第一轮对话（history 为空）
- 问题少于 10 字且无专业术语
- 问题可能对应多个 SOP 领域

### Prompt

```python
CLARIFY_PROMPT = """
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
{{
  "need_clarify": true,
  "reason": "问题涉及多个领域",
  "candidates": [
    {{"id": 1, "label": "后端服务问题", "icon": "🖥️", "hint": "如 OOM、服务超时"}},
    {{"id": 2, "label": "数据库问题", "icon": "🗄️", "hint": "如主从延迟、慢查询"}},
    {{"id": 3, "label": "K8s 集群问题", "icon": "☸️", "hint": "如 Pod 重启、节点异常"}}
  ]
}}
"""
```

### 返回结构

```json
// 需要澄清时
{
  "type": "clarification",
  "message": "你的问题可能涉及几个方向，请选择：",
  "candidates": [
    {"id": 1, "label": "后端服务问题", "icon": "🖥️", "hint": "如 OOM、服务超时"},
    {"id": 2, "label": "数据库问题", "icon": "🗄️", "hint": "如主从延迟、慢查询"}
  ]
}

// 不需要澄清，直接走 Agent
{
  "type": "agent"
}
```

---

## Agent 主循环（agent/runner.py）

### 系统 Prompt

```python
SYSTEM_PROMPT = """
你是专业的 On-Call 助手，帮助工程师快速定位和解决线上问题。

你只有一个工具 readFile(fname)，可读取以下文件：
- sop-001.html：后端服务（OOM、超时、降级）
- sop-002.html：数据库 DBA（主从延迟、慢查询、连接池）
- sop-003.html：前端（白屏、CDN、性能）
- sop-004.html：SRE（K8s、监控、容量规划）
- sop-005.html：安全团队（入侵、漏洞、事件分级）
- sop-006.html：数据平台（ETL、Spark、数据管道）
- sop-007.html：移动端（崩溃、热修复、推送）
- sop-008.html：AI & 算法（模型推理、推荐质量、GPU）
- sop-009.html：QA（测试环境、自动化、发版）
- sop-010.html：网络 & CDN（节点故障、DNS、DDoS）

严格规则：
1. 回答前必须先读取相关文件，不能凭记忆回答
2. 不能列目录，不能使用通配符，只能按文件名读取
3. 问题涉及多个领域时，读取多个文件后综合回答
4. 回答要给出具体可操作的处理步骤
"""
```

### Tool 定义（agent/tools.py）

```python
TOOLS = [
    {
        "name": "readFile",
        "description": "读取 data/ 目录下的 SOP 文件内容。只能读取已知文件名，不能列目录。",
        "input_schema": {
            "type": "object",
            "properties": {
                "fname": {
                    "type": "string",
                    "description": "文件名，如 sop-001.html、sop-002.html"
                }
            },
            "required": ["fname"]
        }
    }
]

def execute_read_file(fname: str) -> str:
    # 路径安全校验：只允许 sop-XXX.html 格式
    import re, os
    if not re.match(r'^sop-\d{3}\.html$', fname):
        return "错误：只能读取 sop-XXX.html 格式的文件"
    path = os.path.join("data", fname)
    if not os.path.exists(path):
        return f"错误：文件 {fname} 不存在"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
```

### 滑动窗口（agent/runner.py）

```python
def sliding_window(history: list, max_turns: int = 10) -> list:
    if len(history) <= max_turns * 2:
        return history
    # 保留第一条消息（原始问题上下文）+ 最近 N 轮
    return [history[0]] + history[-(max_turns * 2 - 1):]
```

### Agent 循环 + SSE 流式输出

```python
async def run_agent(question: str, history: list, strategy: str = "rrf+rewrite"):
    trace = AgentTrace(question=question, strategy=strategy)

    windowed = sliding_window(history)
    messages = windowed + [{"role": "user", "content": question}]

    while True:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "tool_use":
            assistant_msg = {"role": "assistant", "content": response.content}
            messages.append(assistant_msg)
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    fname = block.input["fname"]
                    # SSE：通知前端正在读取文件
                    yield {"type": "tool_call", "fname": fname}

                    content = execute_read_file(fname)
                    trace.tool_calls.append(ToolCall(fname=fname, result_length=len(content)))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content
                    })

            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            final_answer = response.content[0].text
            trace.final_answer = final_answer
            # SSE：流式输出最终回答
            yield {"type": "answer", "message": final_answer}
            break

    save_trace(trace)
```

### SSE 事件格式

```
// 工具调用
data: {"type": "tool_call", "fname": "sop-002.html"}

// 最终回答（一次性，非逐 token，简化实现）
data: {"type": "answer", "message": "处理步骤如下..."}

// 结束
data: {"type": "done"}
```

---

## 前端（static/v3.html）

### 必须实现的功能

**1. 消息输入框 + 发送按钮**

**2. 澄清候选项渲染**
```
收到 type="clarification" 时，渲染点击按钮：
[🖥️ 后端服务问题]  [🗄️ 数据库问题]  [☸️ K8s 集群问题]
点击后把 label 作为新消息自动发送
```

**3. 工具调用过程可视化**
```
🔍 分析问题中...
📄 正在读取 sop-002.html
✅ 找到相关内容，生成回答...
```

**4. SSE 接收**
```javascript
async function sendMessage(message) {
    const response = await fetch("/v3/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id, history })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const lines = decoder.decode(value).split("\n");
        for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const data = JSON.parse(line.slice(6));
            if (data.type === "tool_call") showToolCall(data.fname);
            if (data.type === "answer") showAnswer(data.message);
            if (data.type === "done") finalize();
        }
    }
}
```
