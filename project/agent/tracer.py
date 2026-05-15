# TODO: Harness
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
    latency: float = 0.0
    token_usage: dict = field(default_factory=dict)
    strategy: str = "rrf+rewrite"
    timestamp: float = field(default_factory=time.time)


trace_store: list[AgentTrace] = []


def save_trace(trace: AgentTrace) -> None:
    trace_store.append(trace)
