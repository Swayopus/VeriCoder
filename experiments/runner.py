"""Shared experiment orchestration for Baseline and VeriCoder runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import config
from agent.base import CodingAgent
from core.models import Task
from core.workspace import Workspace
from core.artifacts import EvidenceBundle, new_run_id
from feedback.loop import Attempt, FeedbackLoop, LoopResult
from report.storage import ResultStore
from verifier.engine import VerificationEngine

AgentFactory = Callable[[Task], CodingAgent]


@dataclass
class ExperimentSpec:
    name: str
    # 0 == single attempt (Baseline); None == use task.max_retries (VeriCoder)
    max_retries_override: Optional[int] = None

    def retries_for(self, task: Task) -> int:
        if self.max_retries_override is None:
            return task.max_retries
        return self.max_retries_override


class ExperimentRunner:
    def __init__(
        self,
        spec: ExperimentSpec,
        storage: ResultStore | None = None,
        work_root: str | Path | None = None,
        engine: VerificationEngine | None = None,
        run_id: str | None = None,
    ) -> None:
        self.spec = spec
        self.storage = storage
        self.run_id = run_id or new_run_id(spec.name)
        root = Path(work_root or config.RUNS_DIR)
        self.work_root = root / "workspaces" / self.run_id / spec.name
        self.bundle = EvidenceBundle(root / "evidence" / spec.name, self.run_id,
                                     {"experiment": spec.name, "max_retries_override": spec.max_retries_override})
        self.engine = engine or VerificationEngine()

    def run(
        self,
        tasks: Iterable[Task],
        agent_factory: AgentFactory,
        on_attempt: Callable[[Attempt], None] | None = None,
        keep_workspaces: bool = False,
        repeats: int = 1,
    ) -> list[LoopResult]:
        if repeats < 1:
            raise ValueError("repeats must be positive")
        tasks = list(tasks)
        results: list[LoopResult] = []
        for repeat in range(repeats):
            for task in tasks:
                results.append(
                    self.run_task(
                        task,
                        agent_factory(task),
                        on_attempt=on_attempt,
                        keep_workspaces=keep_workspaces,
                        repeat_index=repeat,
                    )
                )
        return results

    def run_task(
        self,
        task: Task,
        agent: CodingAgent,
        on_attempt: Callable[[Attempt], None] | None = None,
        keep_workspaces: bool = False,
        repeat_index: int = 0,
    ) -> LoopResult:
        workspace = Workspace.prepare(
            task.repo_dir, self.work_root / str(repeat_index) / task.repository / task.task_id
        )
        loop = FeedbackLoop(self.engine, max_retries=self.spec.retries_for(task))
        try:
            result = loop.run(agent, task, workspace, on_attempt=on_attempt)
            result.run_id = self.run_id
            result.condition = self.spec.name
            result.repeat_index = repeat_index
            self.bundle.save_task(task, f"repeat-{repeat_index}/{self.spec.name}", result.to_dict())
        finally:
            if not keep_workspaces:
                workspace.cleanup()

        if self.storage is not None:
            self.storage.save(self.spec.name, result, repository=task.repository, agent=agent.name)
        return result
