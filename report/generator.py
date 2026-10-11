"""Multi-dimensional reliability report.

Deliberately does not collapse everything into a single score: reliability is
reported across the dimensions frozen in the design doc.
"""

from __future__ import annotations

from typing import Any, Iterable

from feedback.loop import LoopResult


def summarize(results: Iterable[LoopResult]) -> dict[str, Any]:
    results = list(results)
    total = len(results) or 1

    successes = sum(1 for r in results if r.success)
    first_attempt = sum(1 for r in results if r.first_attempt_success)
    total_retries = sum(r.retries for r in results)
    total_tokens = sum(r.total_tokens for r in results)

    out_of_scope = 0
    test_modified = 0
    anomalies = 0
    failed_requirements = 0
    human_interventions = 0

    for result in results:
        report = result.final_report
        human_interventions += len(result.human_interventions)
        if report is None:
            continue
        diff = report.diff_result or {}
        trace = report.trace_result or {}
        requirements = report.requirement_result or {}
        if diff.get("out_of_scope_files"):
            out_of_scope += 1
        if diff.get("test_files_modified"):
            test_modified += 1
        anomalies += len(trace.get("anomalies", []))
        failed_requirements += requirements.get("failed_count", 0)

    return {
        "task_count": len(results),
        "task_success_rate": round(successes / total, 4),
        "first_attempt_success_rate": round(first_attempt / total, 4),
        "average_retries": round(total_retries / total, 4),
        "out_of_scope_warning_rate": round(out_of_scope / total, 4),
        "test_modification_count": test_modified,
        "trace_anomaly_count": anomalies,
        "failed_requirement_count": failed_requirements,
        "average_tokens": round(total_tokens / total, 2),
        "human_intervention_count": human_interventions,
        "invalid_count": sum(not r.final_report or not r.final_report.valid for r in results),
        "warning_count": sum(bool(r.final_report and r.final_report.verdict == "WARNING") for r in results),
        "retry_tokens": sum(a.tokens for r in results for a in r.attempts[1:]),
        "total_tokens": total_tokens,
        "duration_ms": sum(a.duration_ms for r in results for a in r.attempts),
        "attempt_test_modification_count": sum(bool(a.report.diff_result.get("test_files_modified")) for r in results for a in r.attempts),
        "held_out_scored_count": sum(bool(r.acceptance and r.acceptance.get("available") and r.acceptance.get("valid")) for r in results),
    }


def compare(baseline: dict[str, Any], vericoder: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "task_success_rate",
        "first_attempt_success_rate",
        "average_retries",
        "out_of_scope_warning_rate",
        "test_modification_count",
        "trace_anomaly_count",
        "average_tokens",
        "human_intervention_count",
    ]
    return {
        key: {
            "baseline": baseline.get(key),
            "vericoder": vericoder.get(key),
            "delta": _delta(baseline.get(key), vericoder.get(key)),
        }
        for key in keys
    }


def _delta(a: Any, b: Any) -> Any:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(b - a, 4)
    return None


def to_markdown(summary: dict[str, Any], title: str = "VeriCoder Report") -> str:
    lines = [f"# {title}", ""]
    for key, value in summary.items():
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Baseline vs VeriCoder",
        "",
        "| Metric | Baseline | VeriCoder | Delta |",
        "| --- | --- | --- | --- |",
    ]
    for metric, values in comparison.items():
        lines.append(
            f"| {metric} | {values['baseline']} | {values['vericoder']} | {values['delta']} |"
        )
    return "\n".join(lines)


_CASE_LIBRARY = {
    "test_modification": "Existing test files changed; review the recorded edits and their purpose.",
    "large_refactor": "Edited file count exceeded the configured review threshold.",
    "missing_requirement": "Tests pass but an explicit requirement assertion fails.",
    "out_of_scope": "Changes include files outside the task's declared allowed_files.",
}


def failure_cases(results: Iterable[LoopResult]) -> list[dict[str, Any]]:
    """Classify observed runs against the five canonical failure cases."""
    cases: list[dict[str, Any]] = []
    for result in results:
        report = result.final_report
        if report is None:
            continue
        diff = report.diff_result or {}
        trace = report.trace_result or {}
        requirements = report.requirement_result or {}
        anomaly_types = {a["type"] for a in trace.get("anomalies", [])}
        failed_reqs = requirements.get("failed_count", 0)
        tests_pass = (report.test_result or {}).get("passed", False)

        matched: list[str] = []
        if diff.get("test_files_modified") or anomaly_types & {
            "test_file_modified",
            "test_modified_after_failure",
        }:
            matched.append("test_modification")
        if "large_refactor" in anomaly_types:
            matched.append("large_refactor")
        if failed_reqs and tests_pass:
            matched.append("missing_requirement")
        if diff.get("out_of_scope_files"):
            matched.append("out_of_scope")

        for case in matched:
            cases.append(
                {
                    "task_id": result.task_id,
                    "case": case,
                    "description": _CASE_LIBRARY[case],
                    "evidence": {
                        "failed_requirements": failed_reqs,
                        "out_of_scope": diff.get("out_of_scope_files", []),
                        "test_files_modified": diff.get("test_files_modified", []),
                        "anomalies": sorted(anomaly_types),
                    },
                }
            )
    return cases
