"""Test Validation — the highest priority signal.

Runs the task's test command (pytest by default) inside the repository and
extracts structured pass/fail information.
"""

from __future__ import annotations

import re
import json
import os
import shlex
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
from sandbox.execution import IO_DIRECTORY_ENV, TRUSTED_HELPERS, run_command


_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERROR_RE = re.compile(r"(\d+)\s+error")
_FAILED_ID_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$", re.MULTILINE)


@dataclass
class TestResult:
    passed: bool
    returncode: int
    command: str
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    failed_tests: list[dict[str, str]] = field(default_factory=list)
    output: str = ""
    duration_ms: int = 0
    valid: bool = True
    integrity_error: str = ""
    collected_nodes: list[str] = field(default_factory=list)
    receipt: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "returncode": self.returncode,
            "command": self.command,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "error_count": self.error_count,
            "failed_tests": self.failed_tests,
            "output": self.output,
            "duration_ms": self.duration_ms,
            "valid": self.valid,
            "integrity_error": self.integrity_error,
            "collected_nodes": self.collected_nodes,
            "receipt": self.receipt,
        }


class TestValidator:
    __test__ = False
    def __init__(
        self, command: str | None = None, timeout: int | None = None,
        expected_nodes: list[str] | None = None, expected_count: int | None = None,
    ) -> None:
        self.command = command or "python -m pytest -q"
        self.timeout = timeout or config.COMMAND_TIMEOUT
        self.expected_nodes = expected_nodes
        self.expected_count = expected_count

    def _pytest_args(self) -> list[str]:
        parts = shlex.split(self.command, posix=os.name != "nt")
        parts = [part.strip('"') for part in parts]
        if not parts:
            raise ValueError("Empty test command")
        executable = Path(parts[0]).name.lower()
        if executable in {"pytest", "pytest.exe"}:
            return parts[1:]
        if executable.startswith(("python", "pypy")) and parts[1:3] == ["-m", "pytest"]:
            return parts[3:]
        raise ValueError("Trusted verification supports only a pytest command argv")

    def run(self, repo_dir: str | Path) -> TestResult:
        import time

        started = time.perf_counter()
        nonce = uuid.uuid4().hex
        receipt: dict[str, Any] = {}
        integrity_error = ""
        try:
            pytest_args = self._pytest_args()
            with tempfile.TemporaryDirectory(prefix="vericoder-pytest-") as scratch:
                report_path = Path(scratch) / "receipt.json"
                proc = run_command(
                    [sys.executable, "-B", str(TRUSTED_HELPERS / "pytest_runner.py"),
                     str(report_path), nonce, "--rootdir", str(Path(repo_dir).resolve()),
                     "--confcutdir", str(Path(repo_dir).resolve()),
                     "-c", str(TRUSTED_HELPERS / "pytest.ini"),
                     "-p", "no:cacheprovider", *pytest_args],
                    cwd=repo_dir, timeout=self.timeout, read_only=True,
                    env={IO_DIRECTORY_ENV: scratch, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                         "PYTEST_ADDOPTS": "", "PYTHONPATH": "",
                         "PYTHONOPTIMIZE": "", "PYTHONDONTWRITEBYTECODE": "1"},
                )
                returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
                try:
                    receipt = json.loads(report_path.read_text(encoding="utf-8"))
                    if not isinstance(receipt, dict):
                        receipt = {}
                        integrity_error = "Malformed pytest completion receipt"
                except (OSError, ValueError):
                    integrity_error = "Missing or unreadable pytest completion receipt"
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = f"Test command timed out after {self.timeout}s"
            integrity_error = "Pytest execution timed out"
        except (OSError, RuntimeError, ValueError) as exc:
            returncode, stdout, stderr = 125, "", str(exc)
            integrity_error = f"Test execution unavailable: {exc}"
        duration_ms = int((time.perf_counter() - started) * 1000)

        output = (stdout or "") + ("\n" + stderr if stderr else "")
        result = self.parse(output, returncode, duration_ms)
        result.receipt = receipt
        result.collected_nodes = receipt.get("nodes", [])
        if not integrity_error:
            integrity_error = self._validate_receipt(receipt, nonce, returncode)
        result.integrity_error = integrity_error
        result.valid = not bool(integrity_error)
        result.passed = result.valid and returncode == 0
        if result.valid:
            # Text summaries disappear under -qq; the trusted reports remain.
            events = receipt.get("reports", [])
            result.passed_count = sum(e["when"] == "call" and e["outcome"] == "passed" for e in events)
            result.failed_count = sum(e["when"] == "call" and e["outcome"] == "failed" for e in events)
            result.error_count = (sum(e["when"] in {"setup", "teardown"} and e["outcome"] == "failed"
                                      for e in events) + len(receipt.get("collection_errors", [])))
            result.failed_tests = [
                {"name": e["nodeid"], "status": "failed" if e["when"] == "call" else "error",
                 "reason": e.get("message", "")}
                for e in events if e.get("outcome") == "failed"
            ]
            result.failed_tests.extend({"name": "<collection>", "status": "error", "reason": error}
                                       for error in receipt.get("collection_errors", []))
        if integrity_error:
            result.failed_tests.append({
                "name": "<verification integrity>", "status": "invalid",
                "reason": integrity_error,
            })
        return result

    def _validate_receipt(self, receipt: dict[str, Any], nonce: str, returncode: int) -> str:
        if (receipt.get("protocol") != 1 or receipt.get("nonce") != nonce
                or receipt.get("completed") is not True
                or receipt.get("exitstatus") != returncode
                or receipt.get("session_exitstatus") != returncode):
            return "Pytest did not complete its trusted session"
        # A completed collection error is a candidate failure, not a green run.
        if receipt.get("collection_errors") and returncode == 2:
            if any(error.get('origin') != 'candidate' for error in receipt.get('collection_error_details', [])):
                return 'Pytest collection failed outside candidate test modules'
            return ""
        if returncode not in {0, 1}:
            return f"Pytest ended without a complete test run (exit {returncode})"
        nodes = receipt.get("nodes", [])
        if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
            return "Malformed collected pytest nodes"
        if receipt.get("collection_completed") is not True or not nodes:
            return "Pytest collected no tests or collection did not finish"
        if len(nodes) != len(set(nodes)):
            return "Duplicate collected pytest node identifiers"
        if self.expected_nodes is not None and not set(self.expected_nodes).issubset(nodes):
            return "Collected tests are missing nodes from the trusted expected node set"
        if self.expected_count is not None and len(nodes) < self.expected_count:
            return "Collected test count is below the trusted required count"
        reports = receipt.get("reports", [])
        if (not isinstance(reports, list) or not all(isinstance(item, dict) for item in reports)
                or not all(item.get("when") in {"setup", "call", "teardown"}
                           and item.get("outcome") in {"passed", "failed", "skipped"}
                           for item in reports)):
            return "Malformed pytest reports"
        if any(item.get("outcome") == "failed" for item in reports) and returncode == 0:
            return "Pytest exit status contradicts its failed test reports"
        if {item.get("nodeid") for item in reports} != set(nodes):
            return "Collected tests and reported test nodes differ"
        meaningful = False
        for node in nodes:
            events = [item for item in reports if item.get("nodeid") == node]
            phases = [item.get("when") for item in events]
            if phases.count("setup") != 1 or phases.count("teardown") != 1:
                return f"Incomplete pytest setup/teardown report: {node}"
            setup = next(item for item in events if item["when"] == "setup")
            expected_calls = 1 if setup.get("outcome") == "passed" else 0
            if phases.count("call") != expected_calls:
                return f"Incomplete pytest call report: {node}"
            meaningful = meaningful or any(item.get("outcome") in {"passed", "failed"}
                                          and item["when"] == "call" for item in events)
            meaningful = meaningful or setup.get("outcome") == "failed"
        if not meaningful:
            return "No test body completed; all collected tests were skipped"
        return ""

    def parse(self, output: str, returncode: int, duration_ms: int = 0) -> TestResult:
        passed = returncode == 0
        passed_count = self._first_int(_PASSED_RE, output)
        failed_count = self._first_int(_FAILED_RE, output)
        error_count = self._first_int(_ERROR_RE, output)

        failed_tests: list[dict[str, str]] = []
        for status, node_id, reason in _FAILED_ID_RE.findall(output):
            failed_tests.append(
                {
                    "name": node_id,
                    "status": status.lower(),
                    "reason": (reason or "").strip(),
                }
            )

        # A non-zero exit with no parsed failures is still a failure.
        if returncode != 0 and not failed_tests and failed_count == 0:
            failed_tests.append(
                {"name": "<collection/setup>", "status": "error", "reason": self._tail(output)}
            )

        return TestResult(
            passed=passed,
            returncode=returncode,
            command=self.command,
            passed_count=passed_count,
            failed_count=failed_count,
            error_count=error_count,
            failed_tests=failed_tests,
            output=self._tail(output),
            duration_ms=duration_ms,
        )

    @staticmethod
    def _first_int(regex: re.Pattern[str], text: str) -> int:
        match = regex.search(text)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _tail(text: str, limit: int = 8000) -> str:
        text = (text or "").strip()
        return text[-limit:]
