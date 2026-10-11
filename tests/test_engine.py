from pathlib import Path

import config
from agent.scripted import ScriptedAgent
from core.workspace import Workspace
from tasks.loader import TaskLoader
from verifier.engine import VerificationEngine

TASK001 = Path(config.TASKS_DIR) / "todo" / "task001.yaml"


def _run(tmp_path, scenario):
    task = TaskLoader().load(TASK001)
    workspace = Workspace.prepare(task.repo_dir, tmp_path / f"ws-{scenario}")
    result = ScriptedAgent(scenario=scenario).run(task, str(workspace.path))
    report = VerificationEngine().verify(task, workspace.path, result.trace)
    workspace.cleanup()
    return report


def test_good_patch_passes(tmp_path):
    report = _run(tmp_path, "good")
    assert report.passed
    assert report.test_result["passed"]
    assert report.requirement_result["passed"]
    assert report.diff_result["out_of_scope_files"] == []


def test_modify_test_is_caught_despite_passing_tests(tmp_path):
    report = _run(tmp_path, "modify_test")
    assert report.test_result["passed"] is True  # ordinary CI would be green
    assert report.passed is False
    anomalies = {a["type"] for a in report.trace_result["anomalies"]}
    assert "test_file_modified" in anomalies
    assert "test_modified_after_failure" in anomalies


def test_omit_requirement_passes_tests_but_fails_assertion(tmp_path):
    report = _run(tmp_path, "omit_requirement")
    assert report.test_result["passed"] is True
    assert report.passed is False
    assert report.requirement_result["failed_count"] >= 1


def test_wrong_file_is_suspicious_but_passes(tmp_path):
    report = _run(tmp_path, "wrong_file")
    assert report.passed is True
    assert report.diff_result["out_of_scope_files"]
