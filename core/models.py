"""Shared data structures passed between the agent, tools and verifier.

Keeping the data model in one place avoids circular imports between the
tracing layer (`trace/`) and the tool runtime (`tools/`).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Task definition
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """A single coding task loaded from a YAML definition."""

    task_id: str
    repository: str
    description: str
    allowed_files: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    test_command: str = "python -m pytest -q"
    max_retries: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    # Populated by the loader, never serialised into the report.
    repo_dir: str = ""
    task_dir: str = ""
    requirement_checks: list[tuple[str, Callable[..., Any]]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("requirement_checks", None)
        return data


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------
@dataclass
class Patch:
    """The concrete code change produced by an agent for a task."""

    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    base_commit: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Execution trace
# ---------------------------------------------------------------------------
@dataclass
class TraceStep:
    step: int
    action: str
    target: str = ""
    command: str = ""
    status: str = "ok"
    detail: str = ""
    timestamp: str = field(default_factory=utcnow)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Anomaly:
    type: str
    step: int
    severity: str
    message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionTrace:
    task_id: str = ""
    agent: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    retry_count: int = 0
    total_tokens: int = 0
    started_at: str = field(default_factory=utcnow)
    finished_at: Optional[str] = None

    # -- mutation helpers --------------------------------------------------
    def add_step(self, action: str, **kwargs: Any) -> TraceStep:
        step = TraceStep(step=len(self.steps) + 1, action=action, **kwargs)
        self.steps.append(step)
        return step

    def add_anomaly(
        self,
        anomaly_type: str,
        step: int,
        severity: str,
        message: str = "",
        **evidence: Any,
    ) -> Anomaly:
        anomaly = Anomaly(
            type=anomaly_type,
            step=step,
            severity=severity,
            message=message,
            evidence=evidence,
        )
        self.anomalies.append(anomaly)
        return anomaly

    def edited_files(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            if step.action in {"edit_file", "write_file", "str_replace"} and step.target and step.status == "ok":
                if step.target not in seen:
                    seen.append(step.target)
        return seen

    def commands(self) -> list[TraceStep]:
        return [s for s in self.steps if s.action in {"run_command", "run_tests"}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "steps": [s.to_dict() for s in self.steps],
            "anomalies": [a.to_dict() for a in self.anomalies],
            "retry_count": self.retry_count,
            "total_tokens": self.total_tokens,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------
@dataclass
class AgentResult:
    patch: Patch = field(default_factory=Patch)
    trace: ExecutionTrace = field(default_factory=ExecutionTrace)
    tokens: int = 0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch": self.patch.to_dict(),
            "trace": self.trace.to_dict(),
            "tokens": self.tokens,
            "error": self.error,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Verification report
# ---------------------------------------------------------------------------
@dataclass
class VerificationReport:
    task_id: str
    repository: str = ""
    agent: str = ""
    passed: bool = False
    test_result: dict[str, Any] = field(default_factory=dict)
    diff_result: dict[str, Any] = field(default_factory=dict)
    trace_result: dict[str, Any] = field(default_factory=dict)
    requirement_result: dict[str, Any] = field(default_factory=dict)
    feedback: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    @property
    def valid(self) -> bool:
        return bool(self.metadata.get("valid", True)) and all(
            part.get("valid", True)
            for part in (self.test_result, self.diff_result, self.requirement_result)
        )

    @property
    def verdict(self) -> str:
        if not self.valid:
            return "INVALID"
        if not self.passed:
            return "FAIL"
        if self.diff_result.get("suspicious") or self.trace_result.get("suspicious"):
            return "WARNING"
        return "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "valid": self.valid, "verdict": self.verdict}
