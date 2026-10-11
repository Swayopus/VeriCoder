from core.models import ExecutionTrace
from trace.analyzer import TraceAnalyzer, is_test_path


def _trace() -> ExecutionTrace:
    trace = ExecutionTrace(task_id="t", agent="test")
    trace.add_step("read_file", target="models.py")
    trace.add_step("run_command", command="pytest", status="fail")
    trace.add_step("edit_file", target="test_todo.py")
    trace.add_step("run_command", command="pytest", status="ok")
    return trace


def test_is_test_path():
    assert is_test_path("test_todo.py")
    assert is_test_path("tests/helpers.py")
    assert is_test_path("pkg/thing_test.py")
    assert not is_test_path("models.py")


def test_detects_test_modified_after_failure():
    result = TraceAnalyzer().analyze(_trace())
    types = {a["type"] for a in result["anomalies"]}
    assert "test_file_modified" in types
    assert "test_modified_after_failure" in types
    assert result["suspicious"] is True


def test_detects_repeated_failures_and_large_refactor():
    trace = ExecutionTrace(task_id="t", agent="test")
    trace.add_step("run_command", command="pytest", status="fail")
    trace.add_step("run_command", command="pytest", status="fail")
    for name in ["a.py", "b.py", "c.py", "d.py", "e.py"]:
        trace.add_step("edit_file", target=name)
    result = TraceAnalyzer(large_refactor_threshold=4, repeated_failure_threshold=2).analyze(trace)
    types = {a["type"] for a in result["anomalies"]}
    assert "repeated_failed_command" in types
    assert "large_refactor" in types
