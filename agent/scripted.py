"""Offline scripted agent.

The framework's first phase simulates an agent with hand-written scenarios so
the verification layer can be exercised without an API key.  It also powers
the reproducible failure-case library (design doc section 6.3):

    good              -> correct change
    modify_test       -> weakens/deletes tests to make them pass
    wrong_file        -> touches files outside ``allowed_files``
    omit_requirement  -> tests pass but a requirement assertion fails

Scenarios live in ``tasks/<suite>/scenarios.py`` as functions taking a
:class:`ToolExecutor` and the :class:`Task`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional

from agent.base import CodingAgent, build_patch
from core.models import AgentResult, Task
from tools.executor import ToolExecutor
from trace.recorder import TraceRecorder

Scenario = Callable[[ToolExecutor, Task], None]


def _load_scenarios(task_dir: str) -> dict[str, Scenario]:
    path = Path(task_dir) / "scenarios.py"
    if not path.exists():
        return {}
    spec = importlib.util.spec_from_file_location(
        f"vericoder_scenarios_{path.parent.name}", path
    )
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        name: getattr(module, name)
        for name in dir(module)
        if not name.startswith("_") and callable(getattr(module, name))
    }


class ScriptedAgent(CodingAgent):
    name = "scripted"

    def __init__(self, scenario: str = "good", recover_on_retry: bool = True) -> None:
        self.scenario = scenario
        self.recover_on_retry = recover_on_retry

    def run(
        self,
        task: Task,
        repo_dir: str,
        feedback: Optional[dict] = None,
    ) -> AgentResult:
        # Simulate an agent that corrects itself when the verifier sends feedback.
        scenario = self.scenario
        if feedback and self.recover_on_retry and scenario != "good":
            scenario = "good"
        recorder = TraceRecorder(task_id=task.task_id, agent=f"{self.name}:{scenario}")
        executor = ToolExecutor(repo_dir, recorder, test_command=task.test_command)

        scenarios = _load_scenarios(task.task_dir)
        func = scenarios.get(scenario)
        if func is None:
            recorder.record(
                "noop",
                status="fail",
                detail=f"scenario '{scenario}' not found in {task.task_dir}/scenarios.py",
            )
            return AgentResult(
                patch=build_patch(repo_dir, source=self.name),
                trace=recorder.finalize(),
                error=f"scenario '{scenario}' unavailable for task {task.task_id}",
            )

        error = ""
        try:
            func(executor, task)
        except Exception as exc:
            error = str(exc)
        try:
            patch = build_patch(repo_dir, source=f"{self.name}:{scenario}")
        except Exception as exc:
            from core.models import Patch
            patch = Patch(source=f"{self.name}:{scenario}")
            error = "; ".join(part for part in (error, str(exc)) if part)
        return AgentResult(patch=patch, trace=recorder.finalize(), error=error,
                           metadata={"scenario": scenario, "requested_scenario": self.scenario,
                                     "recover_on_retry": self.recover_on_retry,
                                     "stop_reason": "error" if error else "scenario_completed"})
