"""Execution trace recorder.

The recorder is the single source of truth for *how* an agent reached a
result. Agents never touch the shell directly: every action flows through
:class:`tools.executor.ToolExecutor`, which calls :meth:`TraceRecorder.record`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.models import ExecutionTrace


class TraceRecorder:
    def __init__(self, task_id: str = "", agent: str = "") -> None:
        self.trace = ExecutionTrace(task_id=task_id, agent=agent)

    # -- recording ---------------------------------------------------------
    def record(self, action: str, **kwargs: Any):
        return self.trace.add_step(action, **kwargs)

    def record_command(self, command: str, status: str, detail: str = "", **data: Any):
        return self.trace.add_step(
            "run_command", command=command, status=status, detail=detail, data=data
        )

    def add_anomaly(self, anomaly_type: str, step: int, severity: str, message: str = "", **evidence: Any):
        return self.trace.add_anomaly(
            anomaly_type, step=step, severity=severity, message=message, **evidence
        )

    # -- lifecycle ---------------------------------------------------------
    def add_tokens(self, tokens: int) -> None:
        self.trace.total_tokens += max(0, tokens)

    def set_retry_count(self, count: int) -> None:
        self.trace.retry_count = count

    def finalize(self) -> ExecutionTrace:
        from core.models import utcnow

        self.trace.finished_at = utcnow()
        return self.trace

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return self.trace.to_dict()

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "TraceRecorder":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        recorder = cls(task_id=data.get("task_id", ""), agent=data.get("agent", ""))
        from core.models import Anomaly, TraceStep

        recorder.trace.steps = [TraceStep(**s) for s in data.get("steps", [])]
        recorder.trace.anomalies = [Anomaly(**a) for a in data.get("anomalies", [])]
        recorder.trace.retry_count = data.get("retry_count", 0)
        recorder.trace.total_tokens = data.get("total_tokens", 0)
        recorder.trace.started_at = data.get("started_at", recorder.trace.started_at)
        recorder.trace.finished_at = data.get("finished_at")
        return recorder
