"""Baseline experiment: Coding Agent -> Patch -> Test (no feedback, no retry)."""

from __future__ import annotations

from typing import Callable, Iterable

from agent.base import CodingAgent
from agent.scripted import ScriptedAgent
from core.models import Task
from feedback.loop import LoopResult
from experiments.runner import ExperimentRunner, ExperimentSpec
from report.storage import ResultStore
from verifier.engine import VerificationEngine

SPEC = ExperimentSpec("baseline", max_retries_override=0)


def scripted_factory(scenario: str = "good") -> Callable[[Task], CodingAgent]:
    return lambda task: ScriptedAgent(scenario=scenario)


def run_baseline(
    tasks: Iterable[Task],
    agent_factory: Callable[[Task], CodingAgent] = scripted_factory(),
    storage: ResultStore | None = None,
    engine: VerificationEngine | None = None,
    run_id: str | None = None,
) -> list[LoopResult]:
    runner = ExperimentRunner(SPEC, storage=storage, engine=engine, run_id=run_id)
    return runner.run(tasks, agent_factory)
