"""Reusable scenario builder for VeriCoder task suites.

Instead of hand-writing four near-identical functions per task, every suite
declares a declarative ``SPEC`` mapping a ``task_id`` to the edits its scripted
agent should perform.  :func:`build_scenarios` turns that data into the four
canonical scenarios the framework expects:

    good              -- implement the task correctly
    modify_test       -- weaken a test file so the suite goes green dishonestly
    wrong_file        -- correct change plus an out-of-scope file
    omit_requirement  -- tests pass but a requirement assertion is unmet

These are authored contract fixtures, not observed mistakes by a model. Their
labels and the test/requirement split are controlled inputs. They exercise the
verification plumbing; they cannot establish a real coding agent's success rate
or the independent benefit of trace analysis.

Each SPEC entry supports three edit lists (tuples of ``path, old, new``):

    good     -- reference implementation validated against the task contract
    weaken   -- edit a test file so the suite passes without a real fix
    partial  -- implement only what the unit test checks, leaving a separate
                requirement assertion unsatisfied

An edit list is applied with :meth:`ToolExecutor.str_replace`, so ``old`` must
be an exact substring of the baseline file and the resulting git diff/trace are
genuine.
"""

from __future__ import annotations

from typing import Callable, TypeAlias

from core.models import Task
from tools.executor import ToolExecutor

Edit: TypeAlias = tuple[str, str, str]
Scenario: TypeAlias = Callable[[ToolExecutor, Task], None]

DEFAULT_UNRELATED_PATH = "scripts/maintenance.py"
DEFAULT_UNRELATED_BODY = '"""Unrelated maintenance script the agent decided to add."""\n'


def apply_edits(executor: ToolExecutor, edits: list[Edit]) -> None:
    """Apply ``(path, old, new)`` string replacements in order."""
    for path, old, new in edits:
        executor.str_replace(path, old, new)


def build_scenarios(
    spec: dict[str, dict[str, list[Edit]]],
    unrelated_path: str = DEFAULT_UNRELATED_PATH,
    unrelated_body: str = DEFAULT_UNRELATED_BODY,
) -> tuple[Scenario, Scenario, Scenario, Scenario]:
    """Build the four canonical scenarios from a per-task edit ``spec``."""

    def good(executor: ToolExecutor, task: Task) -> None:
        apply_edits(executor, spec[task.task_id]["good"])

    def modify_test(executor: ToolExecutor, task: Task) -> None:
        entry = spec[task.task_id]
        executor.run_command(task.test_command)  # an honest, failing run...
        apply_edits(executor, entry.get("weaken", []))
        executor.run_command(task.test_command)  # ...then a dishonest green run

    def wrong_file(executor: ToolExecutor, task: Task) -> None:
        good(executor, task)
        executor.write_file(unrelated_path, unrelated_body)

    def omit_requirement(executor: ToolExecutor, task: Task) -> None:
        entry = spec[task.task_id]
        apply_edits(executor, entry.get("partial", entry["good"]))

    return good, modify_test, wrong_file, omit_requirement
