"""Regression checks for missing tests, premature exits and invalid backends."""

import subprocess
import sys
from pathlib import Path

import pytest

from core.models import ExecutionTrace, Task
from sandbox import execution
from verifier.engine import VerificationEngine
from verifier.requirement_checker import RequirementChecker
from verifier.requirement_runner import run_python_check
from verifier.test_validator import TestValidator as Validator


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setenv("VERICODER_EXECUTION_BACKEND", "local")


def _write(workspace, name, contents):
    path = workspace / name
    path.write_text(contents, encoding="utf-8")
    return path


def test_pytest_requires_complete_session_receipt(tmp_path):
    _write(tmp_path, "test_ok.py", "def test_ok():\n    assert True\n")
    result = Validator("python -m pytest test_ok.py -q").run(tmp_path)
    assert result.passed and result.valid
    assert result.collected_nodes == ["test_ok.py::test_ok"]
    assert result.receipt["completed"]
    assert {event["when"] for event in result.receipt["reports"]} == {"setup", "call", "teardown"}


@pytest.mark.parametrize("during_import", [True, False])
def test_exit_zero_during_pytest_is_invalid(tmp_path, during_import):
    _write(tmp_path, "api.py", "import os\nos._exit(0)\n")
    source = "import api\n" if during_import else "def test_api():\n    import api\n"
    _write(tmp_path, "test_api.py", source)
    result = Validator("python -m pytest test_api.py -q").run(tmp_path)
    assert result.returncode == 0
    assert not result.passed and not result.valid
    assert "receipt" in result.integrity_error


@pytest.mark.parametrize("source", ["", "import pytest\n@pytest.mark.skip\ndef test_skip():\n    assert True\n"])
def test_zero_effective_tests_is_invalid(tmp_path, source):
    _write(tmp_path, "test_empty.py", source)
    result = Validator("python -m pytest test_empty.py -q").run(tmp_path)
    assert not result.passed and not result.valid


def test_missing_expected_test_is_invalid(tmp_path):
    _write(tmp_path, "test_ok.py", "def test_ok():\n    assert True\n")
    result = Validator("pytest test_ok.py -q", expected_count=2).run(tmp_path)
    assert not result.passed and not result.valid
    assert "count" in result.integrity_error


def test_expected_original_tests_allow_additional_tests(tmp_path):
    _write(tmp_path, "test_ok.py", "def test_ok():\n    assert True\ndef test_added():\n    assert True\n")
    result = Validator("pytest test_ok.py -q", expected_nodes=["test_ok.py::test_ok"],
                       expected_count=1).run(tmp_path)
    assert result.passed and result.valid
    assert result.passed_count == 2


def test_genuine_assertion_failure_is_valid(tmp_path):
    _write(tmp_path, "test_bad.py", "def test_bad():\n    assert False\n")
    result = Validator("python -m pytest test_bad.py -q").run(tmp_path)
    assert not result.passed and result.valid
    assert result.failed_count == 1


def test_requirements_attest_assertions_and_completion(tmp_path):
    result = run_python_check(tmp_path, "assert 2 + 2 == 4\n")
    assert result.passed and result.valid
    assert result.metadata["assertions_started"] == 1
    assert result.metadata["assertions_passed"] == 1
    passed, message = result
    assert passed and message


@pytest.mark.parametrize("code", [
    "import os\nos._exit(0)\nassert True\n",
    "import sys\nsys.exit(0)\nassert True\n",
    "print('no assertions')\n",
    "if False:\n    assert True\n",
])
def test_incomplete_or_empty_requirements_are_invalid(tmp_path, code):
    result = run_python_check(tmp_path, code)
    assert not result.passed and not result.valid


def test_candidate_import_exit_zero_cannot_satisfy_requirements(tmp_path):
    _write(tmp_path, "api.py", "import os\nos._exit(0)\n")
    result = run_python_check(tmp_path, "import api\nassert True\n")
    assert not result.passed and not result.valid


@pytest.mark.parametrize("code", [
    "assert False, 'business rule unmet'\n",
    "x = {}\nx['missing']\nassert True\n",
    "from api import value\nassert value\n",
])
def test_completed_candidate_failures_are_functional_failures(tmp_path, code):
    _write(tmp_path, "api.py", "this is invalid python !!!\n")
    result = run_python_check(tmp_path, code)
    assert not result.passed and result.valid
    assert result.metadata["completed"]


def test_requirements_do_not_require_unvisited_assertion_branches(tmp_path):
    result = run_python_check(tmp_path, "if False:\n    assert False\nassert True\n")
    assert result.passed and result.valid
    assert result.metadata["assertions_declared"] == 2
    assert result.metadata["assertions_started"] == 1


def test_timeout_and_missing_requirement_checks_are_invalid(tmp_path):
    result = run_python_check(tmp_path, "import time\ntime.sleep(10)\nassert True\n", timeout=1)
    assert not result.passed and not result.valid
    summary = RequirementChecker().run([], tmp_path)
    assert not summary.passed and not summary.valid


def test_receipt_incomplete_call_is_invalid():
    receipt = {
        "protocol": 1, "nonce": "n", "completed": True,
        "session_exitstatus": 0, "exitstatus": 0, "collection_completed": True,
        "nodes": ["test_a.py::test_a"],
        "reports": [{"nodeid": "test_a.py::test_a", "when": phase, "outcome": "passed"}
                    for phase in ["setup", "teardown"]],
    }
    assert "call" in Validator()._validate_receipt(receipt, "n", 0)


def test_docker_unavailable_never_runs_locally(tmp_path, monkeypatch):
    monkeypatch.setenv("VERICODER_EXECUTION_BACKEND", "docker")
    monkeypatch.setattr(execution.shutil, "which", lambda name: None)
    invoked = []
    monkeypatch.setattr(execution.subprocess, "run", lambda *args, **kwargs: invoked.append(args))
    with pytest.raises(execution.ExecutionBackendError, match="unavailable"):
        execution.run_command([sys.executable, "-c", "print('host')"], tmp_path, 10)
    assert invoked == []


def test_local_candidate_does_not_inherit_api_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('VERICODER_EXECUTION_BACKEND', 'local')
    monkeypatch.setenv('CUSTOM_PROVIDER_CREDENTIAL', 'private-fixture')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'private-fixture')
    proc = execution.run_command([sys.executable, '-c',
        "import os; assert 'DEEPSEEK_API_KEY' not in os.environ; assert 'CUSTOM_PROVIDER_CREDENTIAL' not in os.environ"], tmp_path, 10)
    assert proc.returncode == 0


def test_docker_backend_uses_offline_restricted_mounts(tmp_path, monkeypatch):
    monkeypatch.setenv("VERICODER_EXECUTION_BACKEND", "docker")
    monkeypatch.setattr(execution.shutil, "which", lambda name: "docker")
    captured = []

    def run(argv, **kwargs):
        captured.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(execution.subprocess, "run", run)
    execution.run_command([sys.executable, "-c", "print('container')"], tmp_path, 10, read_only=True)
    args, kwargs = captured[0]
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--pull") + 1] == "never"
    assert f"{tmp_path.resolve()}:/workspace:ro" in args
    assert f"{execution.TRUSTED_HELPERS.resolve()}:/vericoder_trusted:ro" in args
    assert args[-3:] == ["python", "-c", "print('container')"]
    assert kwargs["shell"] is False


def test_engine_reports_invalid_without_turning_warnings_into_failures(tmp_path):
    _write(tmp_path, "test_ok.py", "def test_ok():\n    assert True\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "baseline"], cwd=tmp_path, check=True)
    baseline = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()
    _write(tmp_path, "unrelated.py", "# incidental file\n")
    task = Task("001", "sample", "sample", allowed_files=["api.py"],
                test_command="python -m pytest test_ok.py -q",
                requirement_checks=[("check", lambda repo: run_python_check(repo, "assert True\n"))])
    report = VerificationEngine().verify(task, tmp_path, ExecutionTrace(), base_commit=baseline)
    assert report.passed and report.metadata["verdict"] == report.verdict == "WARNING"
    assert "out_of_scope" in report.metadata["warnings"]
    _write(tmp_path, "test_ok.py", "import os\nos._exit(0)\n")
    report = VerificationEngine().verify(task, tmp_path, ExecutionTrace(), base_commit=baseline)
    assert not report.passed and report.metadata["verdict"] == "INVALID"
    assert not report.metadata["valid"]
