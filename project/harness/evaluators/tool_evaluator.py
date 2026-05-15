from agent.tracer import AgentTrace


def evaluate(trace: AgentTrace, case: dict) -> dict:
    actual = [t.fname for t in trace.tool_calls]
    expected = case["expected_files"]

    precision = (
        len(set(actual) & set(expected)) / len(actual) if actual else 0.0
    )
    recall = len(set(actual) & set(expected)) / len(expected)
    efficiency = 1.0 if len(actual) <= case["max_tool_calls"] else 0.5
    first_hit = (actual[0] in expected) if actual else False

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "efficiency": efficiency,
        "first_hit": first_hit,
        "actual_files": actual,
        "expected_files": expected,
    }
