"""Coding Agent abstraction.

The verification layer only depends on this interface, never on a specific
model.  Swapping DeepSeek for Claude means implementing ``run`` once.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import config
from core.models import AgentResult, ExecutionTrace, Patch, Task
from trace.recorder import TraceRecorder


def build_patch(repo_dir: str | Path, source: str = "") -> Patch:
    """Capture the working-tree change as a Patch using git."""
    from core.workspace import WorkspaceError
    from verifier.diff_analyzer import DiffAnalyzer

    result = DiffAnalyzer().analyze(repo_dir)
    if not result.valid:
        raise WorkspaceError(result.error)
    return Patch(diff=result.diff, changed_files=result.changed_files,
                 base_commit=result.base_commit, source=source)


class CodingAgent(ABC):
    name: str = "base"

    @abstractmethod
    def run(
        self,
        task: Task,
        repo_dir: str,
        feedback: Optional[dict[str, Any]] = None,
    ) -> AgentResult:
        """Produce a patch + execution trace for ``task`` inside ``repo_dir``."""

    def _empty_result(self, repo_dir: str, error: str = "") -> AgentResult:
        trace = TraceRecorder(task_id="", agent=self.name).finalize()
        return AgentResult(patch=Patch(), trace=trace, error=error)

    @staticmethod
    def trace_of(recorder: TraceRecorder) -> ExecutionTrace:
        return recorder.finalize()
