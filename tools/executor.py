"""Trace-aware file tools and a fixed, task-owned pytest action.

This records tool calls and persistent file changes around tests. It does not
claim to monitor every syscall or transient modification inside candidate code.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import config
from trace.analyzer import is_test_path
from trace.recorder import TraceRecorder


class ToolRuntimeError(RuntimeError):
    """A tool was denied or could not complete."""


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, limit: int = 2000) -> str:
        return (self.stdout + "\n" + self.stderr).strip()[-limit:]

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "ok": self.ok}


_IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", "venv"}


def _manifest(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in _IGNORED_PARTS for part in rel.parts):
            continue
        if path.is_symlink():
            files[rel.as_posix()] = "symlink:" + str(path.readlink())
        elif path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            files[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _file_changes(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(after.keys() - before.keys()),
        "deleted": sorted(before.keys() - after.keys()),
        "modified": sorted(name for name in before.keys() & after.keys() if before[name] != after[name]),
    }


def _pytest_argv(command: str) -> list[str]:
    if any(token in command for token in (";", "&", "|", ">", "<", "\n", "\r", "`", "$(")):
        raise ToolRuntimeError("Task test action must be one pytest command without shell syntax")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ToolRuntimeError(f"Invalid task test command: {exc}") from exc
    if len(argv) < 3 or Path(argv[0]).name.lower() not in {"python", "python.exe", "python3", "python3.exe"} or argv[1:3] != ["-m", "pytest"]:
        raise ToolRuntimeError("Only the task's python -m pytest action is supported")
    return argv


class ToolExecutor:
    def __init__(self, root: str | Path, recorder: TraceRecorder, test_command: str | None = None) -> None:
        self.root = Path(root).resolve()
        self.trace = recorder
        self.test_command = test_command
        self.test_argv = _pytest_argv(test_command) if test_command else None

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if any(part.casefold() == ".git" for part in candidate.parts):
            raise ToolRuntimeError(f"Git metadata access is forbidden: {path}")
        resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ToolRuntimeError(f"Path escapes workspace: {path}")
        relative = resolved.relative_to(self.root)
        if any(part.casefold() == ".git" for part in relative.parts):
            raise ToolRuntimeError(f"Git metadata access is forbidden: {path}")
        # A symlink could otherwise redirect a later write after initial validation.
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ToolRuntimeError(f"Symlink file access is forbidden: {path}")
        return resolved

    def _file(self, action: str, path: str, operation: Callable[[Path], Any]) -> Any:
        target = path.replace("\\", "/")
        try:
            resolved = self._resolve(path)
            target = resolved.relative_to(self.root).as_posix()
            existed_before = resolved.exists()
            outcome = operation(resolved)
        except Exception as exc:
            self.trace.record(action, target=target,
                              status="denied" if isinstance(exc, ToolRuntimeError) else "fail",
                              detail=str(exc), data={"category": "file", "completed": False})
            raise ToolRuntimeError(str(exc)) from exc
        self.trace.record(action, target=target, status="ok",
                          data={"category": "file", "completed": True, "existed_before": existed_before})
        return outcome

    def read_file(self, path: str) -> str:
        return self._file("read_file", path, lambda resolved: resolved.read_text(encoding="utf-8"))

    def _write(self, path: str, content: str, action: str) -> None:
        def write(resolved: Path) -> None:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        self._file(action, path, write)

    def write_file(self, path: str, content: str) -> None:
        self._write(path, content, "write_file")

    def edit_file(self, path: str, content: str) -> None:
        self._write(path, content, "edit_file")

    def str_replace(self, path: str, old: str, new: str) -> None:
        def replace(resolved: Path) -> None:
            text = resolved.read_text(encoding="utf-8")
            if not old or old not in text:
                raise ValueError("Replacement source is empty or not found")
            if text.count(old) != 1:
                raise ValueError("Replacement source must occur exactly once")
            resolved.write_text(text.replace(old, new, 1), encoding="utf-8")
        self._file("str_replace", path, replace)

    def list_dir(self, path: str = ".") -> list[str]:
        return self._file("list_dir", path, lambda resolved: sorted(
            item.name + ("/" if item.is_dir() else "")
            for item in resolved.iterdir() if item.name.casefold() != ".git"
        ))

    def run_command(self, command: str, timeout: int | None = None) -> CommandResult:
        """Compatibility for scripted scenarios; never accepts a free shell."""
        try:
            argv = _pytest_argv(command)
            if self.test_argv is None or argv != self.test_argv:
                raise ToolRuntimeError("Command is not the configured task test action")
        except ToolRuntimeError as exc:
            self.trace.record("run_command", command=command, status="denied", detail=str(exc),
                              data={"category": "command", "completed": False, "denied": True})
            raise
        return self.run_tests(timeout=timeout)

    def run_tests(self, timeout: int | None = None) -> CommandResult:
        if self.test_argv is None:
            message = "No task-owned pytest action has been configured"
            self.trace.record("run_tests", status="denied", detail=message,
                              data={"category": "test", "completed": False, "denied": True})
            raise ToolRuntimeError(message)
        from sandbox.execution import TRUSTED_HELPERS, run_command
        started = time.perf_counter()
        argv = [sys.executable, *self.test_argv[1:3],
                '--rootdir', str(self.root), '--confcutdir', str(self.root),
                '-c', str(TRUSTED_HELPERS / 'pytest.ini'), '-p', 'no:cacheprovider',
                *self.test_argv[3:]]
        before = _manifest(self.root)
        error = ""
        try:
            proc = run_command(argv, self.root, timeout or config.COMMAND_TIMEOUT, read_only=True,
                               env={'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': '',
                                    'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': '', 'PYTHONOPTIMIZE': ''})
            returncode, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
        except Exception as exc:
            error = str(exc)
            returncode, stdout, stderr = 125, "", error
        after = _manifest(self.root)
        changes = _file_changes(before, after)
        result = CommandResult(self.test_command or "", returncode, stdout, stderr,
                               int((time.perf_counter() - started) * 1000))
        changed = sorted(set().union(*changes.values()))
        self.trace.record("run_tests", command=result.command,
                          status="ok" if result.ok else "fail", detail=result.tail(300),
                          data={"category": "test", "completed": not bool(error), "argv": argv,
                                "result": result.to_dict(), "file_changes": changes,
                                "test_files_changed": [name for name in changed if is_test_path(name)],
                                "backend": os.environ.get("VERICODER_EXECUTION_BACKEND", "local"),
                                "read_only_requested": True,
                                "error": error})
        return result

    def git(self, *args: str) -> CommandResult:
        return self.run_command("git " + " ".join(args))

    def apply_patch(self, patch_text: str) -> CommandResult:
        message = "Raw Git patch execution is unavailable; use structured file tools"
        self.trace.record("apply_patch", status="denied", detail=message,
                          data={"category": "command", "completed": False, "denied": True})
        raise ToolRuntimeError(message)

