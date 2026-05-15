from datetime import datetime


def generate_report(results: dict) -> dict:
    strategies = list(results.keys())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    summary: dict[str, dict] = {}
    for strategy, cases in results.items():
        n = len(cases)
        if n == 0:
            continue
        summary[strategy] = {
            "tool_precision":     round(sum(c["tool"]["precision"]  for c in cases) / n, 3),
            "tool_recall":        round(sum(c["tool"]["recall"]      for c in cases) / n, 3),
            "first_hit_rate":     round(sum(1 for c in cases if c["tool"]["first_hit"]) / n, 3),
            "answer_quality":     round(sum(c["answer"].get("overall", 0) for c in cases) / n, 2),
            "hallucination_rate": round(sum(1 for c in cases if c["hallucination"].get("has_hallucination")) / n, 3),
            "avg_latency":        round(sum(c["latency"] for c in cases) / n, 2),
            "avg_tokens":         round(sum((c["tokens"].get("input_tokens", 0) + c["tokens"].get("output_tokens", 0)) for c in cases) / n),
        }

    # Build text report
    lines = [
        "=" * 44,
        "Harness Report",
        "=" * 44,
        f"运行时间：{now}",
        f"策略数量：{len(strategies)}",
        "",
        "策略对比：",
    ]

    metrics = ["tool_precision", "tool_recall", "first_hit_rate", "answer_quality",
               "hallucination_rate", "avg_latency", "avg_tokens"]

    # Header
    col = 22
    header = f"{'':22}" + "".join(f"{s:>14}" for s in strategies)
    lines.append(header)

    for m in metrics:
        row = f"{m:22}"
        vals = [summary.get(s, {}).get(m, "-") for s in strategies]
        for v in vals:
            row += f"{str(v):>14}"
        if len(strategies) == 2:
            a, b = vals
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                diff = round(b - a, 3)
                sign = "+" if diff >= 0 else ""
                icon = "✅" if (
                    (m in ("hallucination_rate",) and diff < 0) or
                    (m not in ("hallucination_rate", "avg_latency", "avg_tokens") and diff > 0)
                ) else "⚠️"
                row += f"  {icon} {sign}{diff}"
        lines.append(row)

    lines += ["", "Case 详情："]
    for strategy, cases in results.items():
        lines.append(f"\n  策略: {strategy}")
        for c in cases:
            t = c["tool"]
            a = c["answer"]
            h = c["hallucination"]
            ok = "✅" if t["first_hit"] and t["recall"] >= 1.0 else "⚠️"
            halluc = "false" if not h.get("has_hallucination") else "true"
            lines.append(
                f"  {c['case_id']} {ok}  "
                f"precision={t['precision']}  recall={t['recall']}  "
                f"quality={a.get('overall', '?')}  "
                f"hallucination={halluc}  "
                f"latency={c['latency']}s"
            )
            if t["recall"] < 1.0:
                missing = set(t["expected_files"]) - set(t["actual_files"])
                if missing:
                    lines.append(f"        ↑ 漏读: {', '.join(missing)}")

    lines += ["", "=" * 44]
    text_report = "\n".join(lines)

    return {
        "timestamp": now,
        "summary": summary,
        "details": results,
        "report": text_report,
    }
