"""Compare candidate files with the framework's immutable initial commit."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import config
from core.workspace import Workspace, WorkspaceError
from trace.analyzer import is_test_path


def _run_git(repo_dir: str | Path, *args: str, allowed_codes: set[int] | None = None,
             env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env.update(env_overrides or {})
    try:
        proc = subprocess.run(
            [config.GIT_BIN, "-c", f"core.hooksPath={os.devnull}", *args],
            cwd=str(repo_dir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=config.COMMAND_TIMEOUT, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"Git evidence unavailable: {exc}") from exc
    if proc.returncode not in (allowed_codes or {0}):
        raise WorkspaceError(f"Git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc


_ARTIFACT_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", "venv"}


def _is_artifact(path: str) -> bool:
    parts = set(path.replace("\\", "/").split("/"))
    return bool(parts & _ARTIFACT_PARTS) or path.endswith((".pyc", ".pyo", ".vericoder.patch"))


def is_allowed(path: str, allowed_files: list[str]) -> bool:
    normalised = path.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised in [item.replace("\\", "/").removeprefix("./") for item in allowed_files]


@dataclass
class DiffResult:
    changed_files: list[str] = field(default_factory=list)
    out_of_scope_files: list[str] = field(default_factory=list)
    test_files_modified: list[str] = field(default_factory=list)
    test_files_added: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    diff: str = ""
    base_commit: str = ""
    suspicious: bool = False
    allowed_files: list[str] = field(default_factory=list)
    valid: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiffAnalyzer:
    def __init__(self, allowed_files: list[str] | None = None) -> None:
        self.allowed_files = allowed_files or []

    def analyze(self, repo_dir: str | Path, base_commit: str | None = None) -> DiffResult:
        result = DiffResult(allowed_files=list(self.allowed_files), valid=False)
        try:
            baseline = base_commit or Workspace.baseline_for(repo_dir)
            if not baseline or not all(char in "0123456789abcdefABCDEF" for char in baseline) or len(baseline) not in {40, 64}:
                raise WorkspaceError("Baseline must be a fixed Git object ID")
            result.base_commit = baseline
            _run_git(repo_dir, "cat-file", "-e", f"{baseline}^{{commit}}")
            statuses = _run_git(repo_dir, "diff", "--name-status", "-z", "--find-renames", baseline, "--").stdout.split("\0")
            changed: list[str] = []
            added: set[str] = set()
            index = 0
            while index < len(statuses) and statuses[index]:
                status = statuses[index]
                width = 2 if status.startswith(("R", "C")) else 1
                changed.extend(statuses[index + 1:index + 1 + width])
                if status == "A":
                    added.add(statuses[index + 1])
                index += width + 1
            untracked = [name for name in _run_git(repo_dir, "ls-files", "--others", "-z").stdout.split("\0") if name and not _is_artifact(name)]
            changed.extend(untracked)
            added.update(untracked)
            result.changed_files = sorted({name for name in changed if not _is_artifact(name)})
            result.out_of_scope_files = [name for name in result.changed_files if self.allowed_files and not is_allowed(name, self.allowed_files)]
            result.test_files_modified = [name for name in result.changed_files if is_test_path(name) and name not in added]
            result.test_files_added = [name for name in result.changed_files if is_test_path(name) and name in added]
            result.suspicious = bool(result.out_of_scope_files or result.test_files_modified)
            # A separate, process-owned index yields one replayable Git patch
            # including untracked binaries without mutating the agent's index.
            with tempfile.TemporaryDirectory(prefix="vericoder-diff-", dir=Path(repo_dir).resolve().parent) as staging:
                env = {"GIT_INDEX_FILE": str(Path(staging) / "index")}
                _run_git(repo_dir, "read-tree", baseline, env_overrides=env)
                _run_git(repo_dir, "add", "-u", "--", ".", env_overrides=env)
                present = [name for name in result.changed_files if (Path(repo_dir) / name).exists()]
                if present:
                    _run_git(repo_dir, "add", "-f", "--", *present, env_overrides=env)
                result.diff = _run_git(repo_dir, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "--find-renames", baseline, "--", env_overrides=env).stdout
                numstat = _run_git(repo_dir, "diff", "--cached", baseline, "--numstat", "--", env_overrides=env).stdout
            for row in numstat.splitlines():
                parts = row.split("\t")
                if len(parts) >= 3:
                    result.insertions += int(parts[0]) if parts[0].isdigit() else 0
                    result.deletions += int(parts[1]) if parts[1].isdigit() else 0
            result.valid = True
        except (WorkspaceError, OSError, ValueError) as exc:
            result.error = str(exc)
        return result

