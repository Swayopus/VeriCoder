"""Compare feedback policies starting with the exact same first attempt.

All conditions regenerate from the same fixed baseline on retry and receive the
same previous patch. Only their feedback policy differs. Held-out acceptance is
never included in feedback. Missing held-out acceptance is explicitly provisional.
"""
from __future__ import annotations

import hashlib
import json
import ast
from pathlib import Path

import config
from core.artifacts import EvidenceBundle, new_run_id, write_json
from core.workspace import Workspace
from feedback.loop import FeedbackLoop
from report.detection import Observation, signals_from_report
from verifier.requirement_runner import run_python_check

CONDITIONS = {
    "no_retry": ("requirements", False),
    "tests_retry": ("tests", False),
    "requirements_retry": ("requirements", False),
    "full_retry": ("full", True),
}


class AcceptanceSet:
    def __init__(self, path=None):
        self.data = {}
        self.sha256 = None
        if path:
            raw = Path(path).read_bytes()
            self.sha256 = hashlib.sha256(raw).hexdigest()
            self.data = json.loads(raw)
            if not isinstance(self.data, dict) or not isinstance(self.data.get("tasks"), dict):
                raise ValueError("Acceptance file must contain a tasks mapping")
            for key, check in self.data['tasks'].items():
                if not isinstance(check, dict) or not isinstance(check.get('code'), str) or not check['code'].strip():
                    raise ValueError(f'Acceptance {key} needs Python assertion code')
                try:
                    ast.parse(check['code'])
                except SyntaxError as exc:
                    raise ValueError(f'Acceptance {key} has invalid Python syntax') from exc

    def check(self, task, workspace):
        key = f"{task.repository}/{task.task_id}"
        check = self.data.get("tasks", {}).get(key)
        if not check:
            return {"available": False, "passed": None, "valid": False,
                    "reason": "No independent held-out acceptance supplied"}
        if not isinstance(check.get("code"), str):
            raise ValueError(f"Acceptance {key} needs Python assertion code")
        result = run_python_check(str(workspace.path), check["code"])
        return {"available": True, "passed": result.passed, "valid": result.valid,
                "message": result.message, "metadata": result.metadata,
                "sha256": self.sha256,
                "reviewed_by": self.data.get("reviewed_by", []),
                "independence_declared": self.data.get("independence_declared", False)}


def run_paired_study(tasks, agent_factory, *, repeats=1, max_retries=2,
                     run_id=None, work_root=None, storage=None, acceptance_path=None):
    if repeats < 1 or max_retries < 0:
        raise ValueError("repeats must be positive; max_retries must be nonnegative")
    tasks = list(tasks)
    run_id = run_id or new_run_id("paired")
    root = Path(work_root or config.RUNS_DIR)
    acceptance = AcceptanceSet(acceptance_path)
    bundle = EvidenceBundle(root / "evidence" / "paired", run_id, {
        "design": "shared-first-attempt", "repeats": repeats,
        "max_retries": max_retries, "conditions": CONDITIONS,
        "acceptance_sha256": acceptance.sha256,
        "backend": __import__("os").environ.get("VERICODER_EXECUTION_BACKEND", "local"),
    })
    results, observations = [], []
    actual_tokens = 0
    for repeat in range(repeats):
        for task in tasks:
            workspace = Workspace.prepare(task.repo_dir,
                root / "workspaces" / run_id / str(repeat) / task.repository / task.task_id)
            try:
                first = FeedbackLoop(max_retries=0).run(agent_factory(task), task, workspace)
                first.run_id, first.condition, first.repeat_index = run_id, 'first', repeat
                initial = first.attempts[0]
                snapshot = workspace.capture() if initial.report.valid else None
                digest = hashlib.sha256(initial.patch.diff.encode()).hexdigest()
                actual_tokens += initial.tokens
                sample_id = f"{run_id}/{repeat}/{task.repository}/{task.task_id}"
                first_path = bundle.save_task(task, f"repeat-{repeat}/first", first.to_dict())
                observations.append(Observation(task.task_id, task.repository, "agent_first_attempt", None,
                    signals_from_report(initial.report), valid=initial.report.valid,
                    error=initial.agent_error,
                    source="synthetic" if initial.report.agent.startswith("scripted") else "agent_unlabelled",
                    sample_id=sample_id, evidence_path=str(first_path.resolve())))
                for condition, (policy, warnings) in CONDITIONS.items():
                    if snapshot is not None:
                        workspace.restore_snapshot(snapshot)
                    retries = 0 if condition == "no_retry" else max_retries
                    result = FeedbackLoop(max_retries=retries, policy=policy,
                                          retry_warnings=warnings).run(
                        agent_factory(task), task, workspace, initial_attempt=initial)
                    result.run_id, result.condition, result.repeat_index = run_id, condition, repeat
                    result.metadata.update(shared_first_sample=sample_id, shared_first_patch_sha256=digest,
                                           first_attempt_billed_once=True)
                    result.acceptance = (acceptance.check(task, workspace) if result.final_report.valid else
                        {'available': False, 'passed': None, 'valid': False,
                         'reason': 'Candidate execution invalid; held-out acceptance not executed'})
                    actual_tokens += sum(a.tokens for a in result.attempts[1:])
                    result.metadata["artifact_path"] = str(bundle.save_task(
                        task, f"repeat-{repeat}/{condition}", result.to_dict()).resolve())
                    if storage:
                        storage.save(condition, result, repository=task.repository)
                    results.append(result)
            finally:
                workspace.cleanup()
    manifest = {"schema_version": 2, "run_id": run_id, "design": "shared-first-attempt",
                "actual_tokens": actual_tokens,
                "token_accounting": "sum_of_provider_reported_usage; missing responses may incur unknown usage",
                "usage_complete": all(a.agent_metadata.get('usage_complete', not a.agent_error)
                                      for r in results for a in r.attempts),
                "shared_initial_tokens_are_not_billed_per_condition": True,
                "outcome_scope": "held-out acceptance when supplied; internal scores otherwise provisional",
                "observations": [o.to_dict() for o in observations],
                "results": [r.to_dict() for r in results]}
    write_json(bundle.path / "study.json", manifest)
    return results, observations, bundle.path / "study.json"
