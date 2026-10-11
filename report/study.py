"""Paired summaries with a separate held-out outcome and honest token accounting."""
from __future__ import annotations

import random
from collections import defaultdict


def summarize_study(data):
    grouped = defaultdict(list)
    for result in data["results"]:
        grouped[result["condition"]].append(result)
    lines = [f"# Paired study {data['run_id']}", "",
             "All conditions share each first attempt and the same retry limit.",
             "Internal success is a development diagnostic; held-out acceptance is reported separately.",
             "A held-out file is not automatically independent: inspect reviewed_by and independence_declared in the evidence.", "",
             "| Condition | N | Internal success | Held-out pass/scored | Held-out invalid | Attempt invalid | Warnings | Retry tokens | Per-arm tokens* |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, values in grouped.items():
        scored = [v for v in values if (v.get("acceptance") or {}).get("available") and v["acceptance"].get("valid")]
        passed = sum(v["acceptance"]["passed"] for v in scored)
        invalid = sum(not (v.get("final_report") or {}).get("valid", False) for v in values)
        warnings = sum((v.get("final_report") or {}).get("verdict") == "WARNING" for v in values)
        retry = sum(v["retry_tokens"] for v in values)
        available = [v for v in values if (v.get('acceptance') or {}).get('available')]
        acceptance_invalid = sum(not v['acceptance'].get('valid') for v in available)
        held_out = f"{passed}/{len(scored)}" if scored else ('unscorable' if available else "not supplied")
        lines.append(f"| {name} | {len(values)} | {sum(v['success'] for v in values)}/{len(values)} | {held_out} | {acceptance_invalid} | {invalid} | {warnings} | {retry} | {sum(v['total_tokens'] for v in values)} |")
    lines += ["", f"Provider-reported tokens (shared calls counted once): {data['actual_tokens']}.",
              "* Per-arm totals each include the shared first attempt; summing arms would double-count its cost.",
              "Warnings indicate review, not proven cheating. Invalid attempts remain in the denominator."]
    usage_complete = data.get('usage_complete', all(not a.get('agent_error') for v in data['results'] for a in v['attempts']))
    if not usage_complete:
        lines.append('Usage is incomplete: interrupted requests may have incurred additional provider charges; no exact monetary cost is inferred.')
    baseline = grouped.get("requirements_retry", [])
    full = grouped.get("full_retry", [])
    def key(v):
        return (v["final_report"]["repository"], v["task_id"], v["repeat_index"])
    left, right = {key(v): v for v in baseline}, {key(v): v for v in full}
    differences = defaultdict(list)
    for sample in sorted(left.keys() & right.keys()):
        a, b = left[sample].get("acceptance") or {}, right[sample].get("acceptance") or {}
        if all(x.get("available") and x.get("valid") for x in (a, b)):
            differences[sample[:2]].append(int(b["passed"]) - int(a["passed"]))
    if differences:
        values = [sum(v) / len(v) for v in differences.values()]
        delta = sum(values) / len(values)
        lines += ["", f"Held-out full vs requirements-only paired difference: {delta:+.4f} across {len(values)} tasks."]
        if len(values) >= 2 and len(set(values)) > 1:
            rng = random.Random(0)
            samples = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(2000))
            lines.append(f"Exploratory task-cluster bootstrap interval: [{samples[50]:.4f}, {samples[1950]:.4f}]. Shared-repository dependence remains.")
        else:
            lines.append("A nondegenerate uncertainty interval cannot be estimated from these task outcomes.")
    else:
        lines += ["", "No complete held-out pairs: no causal effectiveness or significance claim is produced."]
    return "\n".join(lines)
