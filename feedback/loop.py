"""Bounded retries with explicit feedback policies and complete evidence."""
from __future__ import annotations
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable
import config
from core.models import AgentResult, ExecutionTrace, Patch, Task, VerificationReport
from core.workspace import Workspace
from verifier.engine import VerificationEngine


def build_feedback(report: VerificationReport, policy: str = "full") -> dict[str, Any]:
    if policy not in {"tests", "requirements", "full"}:
        raise ValueError(f"Unknown feedback policy: {policy}")
    test, diff, trace = report.test_result or {}, report.diff_result or {}, report.trace_result or {}
    failed = [r for r in (report.requirement_result or {}).get("results", []) if not r.get("passed")]
    instructions = []
    if not report.valid:
        instructions.append("Verification did not complete. Do not treat this as a passing result.")
    if not test.get("passed", False):
        instructions.append("Fix failing tests without weakening existing assertions.")
    payload = {"task_id": report.task_id, "policy": policy, "valid": report.valid,
               "test_failures": test.get("failed_tests", []), "instructions": instructions}
    if policy in {"requirements", "full"}:
        payload["failed_requirements"] = failed
        if failed:
            instructions.append("Satisfy failed requirement assertions: " + ", ".join(r["name"] for r in failed))
    if policy == "full":
        payload.update(out_of_scope_changes=diff.get("out_of_scope_files", []),
                       test_files_modified=diff.get("test_files_modified", []),
                       trace_anomalies=trace.get("anomalies", []))
        if diff.get("out_of_scope_files") or trace.get("suspicious"):
            instructions.append("Review reported changes and events; warnings are not proof of cheating.")
    return payload


@dataclass
class Attempt:
    index: int
    report: VerificationReport
    patch: Patch
    tokens: int = 0
    trace: ExecutionTrace = field(default_factory=ExecutionTrace)
    agent_error: str = ""
    agent_metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def to_dict(self):
        return {"index": self.index, "passed": self.report.passed, "tokens": self.tokens,
                "report": self.report.to_dict(), "patch": self.patch.to_dict(),
                "trace": self.trace.to_dict(), "agent_error": self.agent_error,
                "agent_metadata": self.agent_metadata, "duration_ms": self.duration_ms}


@dataclass
class LoopResult:
    task_id: str
    success: bool
    attempts: list[Attempt] = field(default_factory=list)
    final_report: VerificationReport | None = None
    total_tokens: int = 0
    retries: int = 0
    run_id: str = ""
    condition: str = ""
    repeat_index: int = 0
    human_interventions: list[dict[str, Any]] = field(default_factory=list)
    acceptance: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def first_attempt_success(self):
        return bool(self.attempts and self.attempts[0].report.passed and self.attempts[0].report.valid)

    @property
    def manual_intervention(self):
        return bool(self.human_interventions)

    def to_dict(self):
        return {"task_id": self.task_id, "success": self.success,
                "first_attempt_success": self.first_attempt_success, "retries": self.retries,
                "total_tokens": self.total_tokens, "retry_tokens": sum(a.tokens for a in self.attempts[1:]),
                "manual_intervention": self.manual_intervention, "human_interventions": self.human_interventions,
                "requires_review": not self.success or bool(self.final_report and self.final_report.verdict == "WARNING"),
                "run_id": self.run_id, "condition": self.condition, "repeat_index": self.repeat_index,
                "duration_ms": sum(a.duration_ms for a in self.attempts),
                "acceptance": self.acceptance, "metadata": self.metadata,
                "attempts": [a.to_dict() for a in self.attempts],
                "final_report": self.final_report.to_dict() if self.final_report else None}


class FeedbackLoop:
    def __init__(self, engine=None, max_retries=None, policy="full", retry_warnings=False):
        self.engine = engine or VerificationEngine()
        self.max_retries = config.DEFAULT_MAX_RETRIES if max_retries is None else max_retries
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if policy not in {"tests", "requirements", "full"}:
            raise ValueError(f"Unknown feedback policy: {policy}")
        self.policy, self.retry_warnings = policy, retry_warnings

    def _finished(self, report):
        if not report.valid:
            return True
        functional = report.test_result.get("passed", False) if self.policy == "tests" else report.passed
        return bool(functional and not (self.retry_warnings and self.policy == "full" and report.verdict == "WARNING"))

    def run(self, agent, task: Task, workspace: Workspace,
            on_attempt: Callable[[Attempt], None] | None = None,
            initial_attempt: Attempt | None = None):
        attempts, feedback = [], None
        for index in range(self.max_retries + 1):
            if index == 0 and initial_attempt is not None:
                attempt = copy.deepcopy(initial_attempt)
            else:
                started = time.perf_counter()
                result = None
                try:
                    workspace.reset()
                    result: AgentResult = agent.run(task, str(workspace.path), feedback=feedback)
                    result.trace.task_id, result.trace.retry_count = task.task_id, index
                    report = self.engine.verify(task, workspace.path, result.trace, base_commit=workspace.base_commit)
                    if result.error:
                        report.metadata.update(valid=False, agent_error=result.error)
                        report.passed = False
                    attempt = Attempt(index, report, result.patch, result.tokens or result.trace.total_tokens,
                                      result.trace, result.error, result.metadata,
                                      int((time.perf_counter() - started) * 1000))
                except Exception as exc:
                    report = VerificationReport(task.task_id, repository=task.repository,
                        agent=getattr(agent, "name", ""), passed=False,
                        metadata={"valid": False, "error": f"{type(exc).__name__}: {exc}"})
                    attempt = Attempt(index, report, result.patch if result else Patch(),
                                      tokens=(result.tokens or result.trace.total_tokens) if result else 0,
                                      trace=result.trace if result else ExecutionTrace(),
                                      agent_metadata=result.metadata if result else {}, agent_error=str(exc),
                                      duration_ms=int((time.perf_counter() - started) * 1000))
            attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
            if self._finished(attempt.report):
                break
            feedback = build_feedback(attempt.report, self.policy)
            feedback["previous_patch"] = attempt.patch.diff
            feedback["retry_strategy"] = "regenerate_from_fixed_baseline"
        final = attempts[-1].report
        return LoopResult(task.task_id, bool(final.valid and final.passed), attempts, final,
                          sum(a.tokens for a in attempts), len(attempts) - 1,
                          metadata={"feedback_policy": self.policy, "retry_warnings": self.retry_warnings,
                                    "retry_strategy": "regenerate_from_fixed_baseline"})
