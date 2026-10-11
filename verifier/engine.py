"""Verification Engine.

Runs the four frozen verification dimensions over an agent's patch + trace:

    Test Validation  ->  Diff Analysis  ->  Trace Analysis  ->  Requirement Checks

A task only *passes* when the tests pass and every requirement assertion
holds.  Suspicious diffs and trace anomalies are reported but never block a
pass on their own (see ``allowed_files`` rationale in the design doc).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.models import ExecutionTrace, Task, VerificationReport
from trace.analyzer import TraceAnalyzer
from verifier.diff_analyzer import DiffAnalyzer
from verifier.requirement_checker import RequirementChecker
from verifier.test_validator import TestValidator


class VerificationEngine:
    def __init__(
        self,
        large_refactor_threshold: int | None = None,
        repeated_failure_threshold: int | None = None,
    ) -> None:
        self.trace_analyzer = TraceAnalyzer(
            large_refactor_threshold=large_refactor_threshold,
            repeated_failure_threshold=repeated_failure_threshold,
        )

    def verify(
        self,
        task: Task,
        repo_dir: str | Path,
        trace: ExecutionTrace,
        base_commit: str | None = None,
    ) -> VerificationReport:
        from feedback.loop import build_feedback

        test_validator = TestValidator(
            command=task.test_command,
            expected_nodes=task.metadata.get("expected_test_nodes"),
            expected_count=task.metadata.get("expected_test_count"),
        )
        test_result = test_validator.run(repo_dir)

        diff_analyzer = DiffAnalyzer(allowed_files=list(task.allowed_files))
        diff_result = diff_analyzer.analyze(repo_dir, base_commit=base_commit)

        trace_result = self.trace_analyzer.analyze(trace)

        requirement_result = RequirementChecker().run(
            task.requirement_checks, repo_dir
        )

        diff_data = diff_result.to_dict()
        valid = bool(test_result.valid and requirement_result.valid and diff_data.get("valid", True))
        functional_passed = bool(test_result.passed and requirement_result.passed)
        warnings = []
        if diff_data.get("out_of_scope_files"):
            warnings.append("out_of_scope")
        if diff_data.get("test_files_modified"):
            warnings.append("test_files_modified")
        if trace_result.get("suspicious"):
            warnings.append("trace_anomalies")
        verdict = "INVALID" if not valid else (("WARNING" if warnings else "PASS") if functional_passed else "FAIL")
        report = VerificationReport(
            task_id=task.task_id,
            repository=task.repository,
            agent=trace.agent,
            passed=bool(valid and functional_passed),
            test_result=test_result.to_dict(),
            diff_result=diff_data,
            trace_result=trace_result,
            requirement_result=requirement_result.to_dict(),
            metadata={"valid": valid, "verdict": verdict,
                      "functional_passed": functional_passed, "warnings": warnings},
        )
        report.feedback = build_feedback(report)
        return report

    def quick_test(self, task: Task, repo_dir: str | Path) -> dict[str, Any]:
        return TestValidator(
            command=task.test_command,
            expected_nodes=task.metadata.get("expected_test_nodes"),
            expected_count=task.metadata.get("expected_test_count"),
        ).run(repo_dir).to_dict()
