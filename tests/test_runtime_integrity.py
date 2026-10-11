"""Regression tests for candidate-controlled Git state and tool boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent.base import build_patch
from agent.deepseek import DeepSeekAgent
from core.models import Task
from core.workspace import Workspace, WorkspaceError
from tools.executor import ToolExecutor, ToolRuntimeError
from trace.analyzer import TraceAnalyzer
from trace.recorder import TraceRecorder
from verifier.diff_analyzer import DiffAnalyzer, is_allowed


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("value = 1\n", encoding="utf-8")
    (source / "test_api.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (source / "removed.txt").write_text("remove me\n", encoding="utf-8")
    (source / "rename.txt").write_text("rename me\n", encoding="utf-8")
    ws = Workspace.prepare(source, tmp_path / "candidate")
    yield ws
    ws.cleanup()


def test_commits_do_not_hide_diff_or_move_retry_baseline(workspace):
    baseline = workspace.base_commit
    (workspace.path / "api.py").write_text("value = 2\n", encoding="utf-8")
    (workspace.path / "extra.py").write_text("unexpected = True\n", encoding="utf-8")
    workspace._git("add", "-A")
    workspace._git("commit", "-q", "-m", "candidate commit")
    assert workspace._git("rev-parse", "HEAD").stdout.strip() != baseline
    result = DiffAnalyzer(["api.py"]).analyze(workspace.path)
    assert result.valid
    assert result.base_commit == baseline
    assert result.changed_files == ["api.py", "extra.py"]
    assert result.out_of_scope_files == ["extra.py"]
    assert "+value = 2" in result.diff and "+unexpected = True" in result.diff
    assert build_patch(workspace.path).diff == result.diff
    workspace.reset()
    assert workspace._git("rev-parse", "HEAD").stdout.strip() == baseline
    assert (workspace.path / "api.py").read_text(encoding="utf-8") == "value = 1\n"
    assert not (workspace.path / "extra.py").exists()


def test_full_patch_replays_add_delete_rename_and_binary(workspace, tmp_path):
    (workspace.path / "removed.txt").unlink()
    (workspace.path / "rename.txt").rename(workspace.path / "renamed.txt")
    workspace._git("add", "-A")
    nested = workspace.path / "new folder"
    nested.mkdir()
    (nested / "中文.py").write_text("text = '你好'\n", encoding="utf-8")
    (nested / "binary.bin").write_bytes(b"\x00\x01\xff")
    result = DiffAnalyzer().analyze(workspace.path)
    assert result.valid, result.error
    assert {"removed.txt", "rename.txt", "renamed.txt", "new folder/中文.py", "new folder/binary.bin"} <= set(result.changed_files)
    assert "GIT binary patch" in result.diff
    replay = Workspace.prepare(tmp_path / "source", tmp_path / "replay")
    try:
        proc = subprocess.run(["git", "apply", "--binary", "-"], input=result.diff.encode("utf-8"), cwd=replay.path,
                              capture_output=True)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace") + "\n" + result.diff
        assert replay.capture() == workspace.capture()
    finally:
        replay.cleanup()


def test_ignored_candidate_files_are_still_evidence(workspace):
    (workspace.path / ".gitignore").write_text("hidden/\n", encoding="utf-8")
    directory = workspace.path / "hidden"
    directory.mkdir()
    (directory / "payload.py").write_text("payload = True\n", encoding="utf-8")
    result = DiffAnalyzer().analyze(workspace.path)
    assert result.valid
    assert "hidden/payload.py" in result.changed_files
    assert "+payload = True" in result.diff


def test_missing_baseline_and_broken_git_are_invalid(workspace, tmp_path):
    unregistered = DiffAnalyzer().analyze(tmp_path)
    assert not unregistered.valid and "baseline" in unregistered.error
    assert not DiffAnalyzer().analyze(workspace.path, base_commit="HEAD").valid
    (workspace.path / ".git" / "HEAD").write_text("broken\n", encoding="utf-8")
    broken = DiffAnalyzer().analyze(workspace.path)
    assert not broken.valid and broken.error
    with pytest.raises(WorkspaceError):
        workspace.reset()


def test_snapshot_exactly_restores_candidate_files(workspace):
    (workspace.path / "api.py").write_text("value = 9\n", encoding="utf-8")
    (workspace.path / "added.py").write_text("saved = True\n", encoding="utf-8")
    (workspace.path / "removed.txt").unlink()
    snapshot = workspace.capture()
    workspace.reset()
    workspace.restore_snapshot(snapshot)
    assert workspace.capture() == snapshot
    assert workspace.base_commit == Workspace.baseline_for(workspace.path)


def test_reset_preserves_source_files_ignored_by_git(tmp_path):
    source = tmp_path / "ignored-source"
    source.mkdir()
    (source / ".gitignore").write_text("data/\n", encoding="utf-8")
    (source / "data").mkdir()
    (source / "data" / "initial.txt").write_text("original", encoding="utf-8")
    ws = Workspace.prepare(source, tmp_path / "ignored-candidate")
    try:
        original = ws.capture()
        (ws.path / "data" / "initial.txt").write_text("candidate", encoding="utf-8")
        ws.reset()
        assert ws.capture() == original
    finally:
        ws.cleanup()


def test_snapshot_can_replace_nested_directories_with_file(tmp_path):
    source = tmp_path / "nested-source"
    nested = source / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "old.txt").write_text("old", encoding="utf-8")
    ws = Workspace.prepare(source, tmp_path / "nested-candidate")
    try:
        snapshot = {"a": b"directory replaced by file"}
        ws.restore_snapshot(snapshot)
        assert ws.capture() == snapshot
    finally:
        ws.cleanup()


def test_git_metadata_escape_and_free_shell_are_denied_and_recorded(workspace):
    recorder = TraceRecorder()
    tools = ToolExecutor(workspace.path, recorder, test_command="python -m pytest test_api.py -q")
    for path in [".git/HEAD", ".Git/config", "../outside.py"]:
        with pytest.raises(ToolRuntimeError):
            tools.write_file(path, "bad")
    for command in ["python -c \"print('shell')\"", "git commit -am hidden",
                    "python -m pytest test_api.py -q && echo hidden",
                    "python -m pytest removed.txt -q"]:
        with pytest.raises(ToolRuntimeError):
            tools.run_command(command)
    assert all(step.status == "denied" for step in recorder.trace.steps)
    assert ".git/" not in tools.list_dir()
    assert not (workspace.path.parent / "outside.py").exists()
    assert not TraceAnalyzer().analyze(recorder.trace)["edited_files"]


def test_fixed_test_action_records_full_result_and_persistent_changes(workspace, monkeypatch):
    import sandbox.execution

    def fake_run(argv, cwd, timeout, env=None, read_only=False):
        assert argv[1:3] == ["-m", "pytest"]
        assert read_only is True
        (Path(cwd) / "test_api.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 1, "complete stdout", "complete stderr")

    monkeypatch.setattr(sandbox.execution, "run_command", fake_run)
    recorder = TraceRecorder()
    command = "python -m pytest test_api.py -q"
    tools = ToolExecutor(workspace.path, recorder, test_command=command)
    result = tools.run_command(command)
    step = recorder.trace.steps[-1]
    assert result.returncode == 1 and step.action == "run_tests"
    assert step.data["result"]["stdout"] == "complete stdout"
    assert step.data["result"]["stderr"] == "complete stderr"
    assert step.data["file_changes"]["modified"] == ["test_api.py"]
    assert step.data["test_files_changed"] == ["test_api.py"]
    assert "files_changed_during_tests" in {item["type"] for item in TraceAnalyzer().analyze(recorder.trace)["anomalies"]}


def test_normal_added_tests_and_non_test_failures_do_not_imply_cheating(workspace):
    recorder = TraceRecorder()
    recorder.record_command("ls missing", "fail")
    tools = ToolExecutor(workspace.path, recorder)
    tools.write_file("test_new.py", "def test_new():\n    assert True\n")
    result = TraceAnalyzer().analyze(recorder.trace)
    assert not result["suspicious"]
    assert {item["type"] for item in result["anomalies"]} == {"test_file_added"}


def test_repeated_non_test_failures_and_editing_new_tests_are_not_suspicious(workspace):
    recorder = TraceRecorder()
    for _ in range(5):
        recorder.record_command("ls missing", "fail")
    tools = ToolExecutor(workspace.path, recorder)
    tools.write_file("test_new.py", "def test_new():\n    assert True\n")
    recorder.record("run_tests", command="pytest", status="fail", data={"category": "test"})
    tools.str_replace("test_new.py", "assert True", "assert 1 == 1")
    result = TraceAnalyzer().analyze(recorder.trace)
    assert not result["suspicious"]
    assert {item["type"] for item in result["anomalies"]} == {"test_file_added"}


def test_added_allowed_test_is_separate_from_modified_tests(workspace):
    (workspace.path / "test_added.py").write_text("def test_new():\n    assert 1 == 1\n", encoding="utf-8")
    result = DiffAnalyzer(["test_added.py"]).analyze(workspace.path)
    assert result.valid
    assert result.test_files_added == ["test_added.py"]
    assert result.test_files_modified == []
    assert not result.suspicious


def test_normal_repairs_break_repeated_failure_chain(workspace):
    recorder = TraceRecorder()
    tools = ToolExecutor(workspace.path, recorder)
    recorder.record("run_tests", command="pytest", status="fail", data={"category": "test"})
    tools.str_replace("api.py", "value = 1", "value = 2")
    recorder.record("run_tests", command="pytest", status="fail", data={"category": "test"})
    tools.str_replace("api.py", "value = 2", "value = 3")
    result = TraceAnalyzer().analyze(recorder.trace)
    assert not result["suspicious"]
    assert not any(item["type"] == "repeated_failed_command" for item in result["anomalies"])


def test_failed_edit_is_recorded_without_claiming_file_changed(workspace):
    recorder = TraceRecorder()
    tools = ToolExecutor(workspace.path, recorder)
    with pytest.raises(ToolRuntimeError):
        tools.str_replace("api.py", "missing source", "new")
    assert recorder.trace.steps[-1].status == "fail"
    result = TraceAnalyzer().analyze(recorder.trace)
    assert result["edited_files"] == [] and not result["suspicious"]


def test_restored_test_edits_remain_visible_in_trace(workspace):
    recorder = TraceRecorder()
    tools = ToolExecutor(workspace.path, recorder)
    original = tools.read_file("test_api.py")
    tools.edit_file("test_api.py", "def test_ok():\n    pass\n")
    tools.edit_file("test_api.py", original)
    diff = DiffAnalyzer().analyze(workspace.path)
    assert diff.valid and diff.test_files_modified == []
    trace = TraceAnalyzer().analyze(recorder.trace)
    assert trace["suspicious"]
    assert "test_file_modified" in {item["type"] for item in trace["anomalies"]}


def test_deepseek_metadata_records_actual_model_and_stop_reason_without_api(workspace, monkeypatch):
    agent = DeepSeekAgent(api_key="never-use-this-key")
    payload = {"model": "actual-served-model", "usage": {"total_tokens": 12, "prompt_tokens": 7},
               "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "done"}}]}
    monkeypatch.setattr(agent, "_chat", lambda messages: payload)
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert result.metadata["models_seen"] == ["actual-served-model"]
    assert result.metadata["responses"][0]["usage"]["prompt_tokens"] == 7
    assert result.metadata["stop_reason"] == "model_finished"
    assert "never-use-this-key" not in str(result.metadata)
    assert result.tokens == 12


@pytest.mark.parametrize("options", [{"max_steps": 0}, {"max_steps": -1}, {"max_steps": True},
                                     {"max_tokens": 0}, {"max_tokens": -1}])
def test_deepseek_rejects_invalid_request_budgets(options):
    with pytest.raises(ValueError, match="positive integer"):
        DeepSeekAgent(api_key="test-only-key", **options)


def test_deepseek_sends_output_cap_and_redacts_provider_errors(workspace, monkeypatch):
    import requests

    secret = "test-only-secret-never-send"
    agent = DeepSeekAgent(api_key=secret, max_steps=1, max_tokens=2048)
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs)
        raise RuntimeError(f"provider error accidentally echoed {secret}")

    monkeypatch.setattr(requests, "post", fake_post)
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert seen["json"]["max_tokens"] == 2048
    assert result.metadata["max_tokens"] == 2048
    assert result.metadata["max_steps"] == 1
    assert result.metadata["stop_reason"] == "api_or_protocol_error"
    assert "[REDACTED]" in result.error
    assert secret not in str(result.to_dict())


def test_deepseek_redacts_provider_echoes_in_saved_metadata(workspace, monkeypatch):
    secret = "test-only-secret-never-send"
    agent = DeepSeekAgent(api_key=secret)
    payload = {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": f"unexpected provider echo {secret}"}}]}
    monkeypatch.setattr(agent, "_chat", lambda messages: payload)
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert secret not in str(result.to_dict())
    assert "[REDACTED]" in result.metadata["responses"][0]["choices"][0]["message"]["content"]


@pytest.mark.parametrize("failure_type", ["ConnectionError", "Timeout"])
def test_deepseek_retries_transport_failure_once_and_marks_usage_unknown(workspace, monkeypatch, failure_type):
    import requests

    secret = "mock-key-only"
    agent = DeepSeekAgent(api_key=secret, max_steps=1)
    calls = []
    waits = []
    payload = {"model": "actual-served-model", "usage": {"total_tokens": 17},
               "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "done"}}]}

    def fake_chat(messages):
        calls.append(messages)
        if len(calls) == 1:
            raise getattr(requests, failure_type)(f"lost response for {secret}")
        return payload

    monkeypatch.setattr(agent, "_chat", fake_chat)
    monkeypatch.setattr("agent.deepseek.time.sleep", waits.append)
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert len(calls) == 2 and waits == [0.25]
    assert result.error == "" and result.tokens == 17
    assert result.metadata["stop_reason"] == "model_finished"
    assert result.metadata["usage_complete"] is False
    assert result.metadata["usage_accounting"] == "provider_reported_only"
    assert result.metadata["request_count"] == 2
    assert result.metadata["transport_retry_count"] == 1
    assert result.metadata["request_failures"] == [{
        "request_number": 1, "step": 1, "attempt": 1, "type": failure_type,
        "message": "lost response for [REDACTED]", "retry": True,
    }]
    assert result.metadata["successful_requests"] == [{"request_number": 2, "step": 1}]
    assert secret not in str(result.to_dict())


def test_deepseek_stops_after_transport_retry_budget(workspace, monkeypatch):
    import requests

    agent = DeepSeekAgent(api_key="mock-key-only", max_steps=5, max_api_retries=1)
    calls = []

    def failing_chat(messages):
        calls.append(messages)
        raise requests.ConnectionError("reset")

    monkeypatch.setattr(agent, "_chat", failing_chat)
    monkeypatch.setattr("agent.deepseek.time.sleep", lambda _: None)
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert len(calls) == 2
    assert result.error == "reset" and result.tokens == 0
    assert result.metadata["stop_reason"] == "api_or_protocol_error"
    assert result.metadata["usage_complete"] is False
    assert [entry["retry"] for entry in result.metadata["request_failures"]] == [True, False]
    assert [entry["request_number"] for entry in result.metadata["request_failures"]] == [1, 2]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_deepseek_does_not_retry_http_errors(workspace, monkeypatch, status):
    import requests

    agent = DeepSeekAgent(api_key="mock-key-only")
    calls = []

    def failing_chat(messages):
        calls.append(messages)
        response = requests.Response()
        response.status_code = status
        raise requests.HTTPError(f"HTTP {status}", response=response)

    monkeypatch.setattr(agent, "_chat", failing_chat)
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert len(calls) == 1 and result.error == f"HTTP {status}"
    assert result.metadata["transport_retry_count"] == 0
    assert result.metadata["request_failures"][0]["retry"] is False


def test_deepseek_retry_can_be_disabled(workspace, monkeypatch):
    import requests

    agent = DeepSeekAgent(api_key="mock-key-only", max_api_retries=0)
    monkeypatch.setattr(agent, "_chat", lambda _: (_ for _ in ()).throw(requests.Timeout("late")))
    result = agent.run(Task("t", "repo", "test task"), str(workspace.path))
    assert result.metadata["request_count"] == 1
    assert result.metadata["request_failures"][0]["retry"] is False


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_deepseek_rejects_invalid_transport_retry_budget(value):
    with pytest.raises(ValueError, match="non-negative integer"):
        DeepSeekAgent(api_key="mock-key-only", max_api_retries=value)

