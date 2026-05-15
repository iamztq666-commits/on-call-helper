import json
import time

from agent.runner import run_agent_for_eval
from harness.evaluators import answer_evaluator, hallucination, tool_evaluator
from harness.report import generate_report


class HarnessRunner:
    def __init__(self, cases_path: str = "harness/cases/eval_cases.json"):
        with open(cases_path) as f:
            self.all_cases = json.load(f)

    async def run(
        self,
        strategies: list[str] | None = None,
        case_ids: list[str] | None = None,
    ) -> dict:
        if strategies is None:
            strategies = ["rrf+rewrite"]

        cases = self.all_cases
        if case_ids:
            cases = [c for c in cases if c["id"] in case_ids]

        results: dict[str, list] = {}
        for strategy in strategies:
            strategy_results = []
            for case in cases:
                start = time.time()
                trace = await run_agent_for_eval(
                    question=case["question"],
                    strategy=strategy,
                    case_id=case["id"],
                )
                trace.latency = time.time() - start

                tool_score = tool_evaluator.evaluate(trace, case)
                answer_score = answer_evaluator.evaluate(trace, case)
                hallucination_score = hallucination.evaluate(trace)

                strategy_results.append({
                    "case_id": case["id"],
                    "question": case["question"],
                    "tool": tool_score,
                    "answer": answer_score,
                    "hallucination": hallucination_score,
                    "latency": round(trace.latency, 2),
                    "tokens": trace.token_usage,
                })

            results[strategy] = strategy_results

        return generate_report(results)
