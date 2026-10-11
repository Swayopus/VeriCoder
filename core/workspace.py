"""Disposable working copies with a baseline owned by the framework process."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import config

_IGNORE_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", "venv"}
_IGNORE = shutil.ignore_patterns(*_IGNORE_PARTS, "*.pyc", "*.pyo")
# Candidate file tools cannot rewrite this process-owned registry. The local
# execution backend remains trusted host code, not a security sandbox.
_BASELINES: dict[str, str] = {}


class WorkspaceError(RuntimeError):
    """A workspace cannot supply reliable baseline or Git evidence."""


def _force_remove(path: str | Path) -> None:
    path = Path(path).resolve()
    if path == Path(path.anchor):
        raise WorkspaceError("Refusing to remove a filesystem root")
    if not path.exists():
        return

    def handle(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IWRITE)
            except OSError:
                pass
    try:
        shutil.rmtree(path, onexc=handle)
    except TypeError:  # Python < 3.12
        shutil.rmtree(path, onerror=handle)


def _workspace_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _IGNORE_PARTS for part in rel.parts):
            continue
        if path.is_symlink():
            raise WorkspaceError(f"Symlink cannot be captured as a regular file: {rel}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            files[rel.as_posix()] = path.read_bytes()
    return files


class Workspace:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    @property
    def base_commit(self) -> str:
        return self.baseline_for(self.path)

    @classmethod
    def baseline_for(cls, repo_path: str | Path) -> str:
        key = str(Path(repo_path).resolve())
        baseline = _BASELINES.get(key)
        if not baseline:
            raise WorkspaceError(f"No framework-owned baseline for workspace: {key}")
        return baseline

    @classmethod
    def prepare(cls, source_repo: str | Path, dest: str | Path) -> "Workspace":
        source = Path(source_repo).resolve()
        target = Path(dest).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Source repository not found: {source}")
        if target == source or target in source.parents or source in target.parents:
            raise WorkspaceError("Workspace must be separate from the source repository")
        if target == Path(target.anchor):
            raise WorkspaceError("Workspace cannot be a filesystem root")
        if target.exists():
            if str(target) not in _BASELINES:
                raise WorkspaceError(f"Destination already exists and is not owned: {target}")
            _force_remove(target)
        _BASELINES.pop(str(target), None)
        shutil.copytree(source, target, ignore=_IGNORE)
        workspace = cls(target)
        workspace._git_init_commit()
        return workspace

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(key, None)
        try:
            proc = subprocess.run(
                [config.GIT_BIN, "-c", f"core.hooksPath={os.devnull}", *args],
                cwd=str(self.path), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=config.COMMAND_TIMEOUT, env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceError(f"Git operation failed: {exc}") from exc
        if proc.returncode:
            raise WorkspaceError(f"Git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
        return proc

    def _git_init_commit(self) -> None:
        self._git("init", "-q")
        self._git("config", "user.email", "vericoder@example.com")
        self._git("config", "user.name", "VeriCoder")
        # The copied source, including data ignored by its .gitignore, is the
        # baseline. Otherwise reset/clean would delete original ignored files.
        self._git("add", "-f", "-A")
        self._git("commit", "-q", "--allow-empty", "-m", "baseline")
        _BASELINES[str(self.path)] = self._git("rev-parse", "--verify", "HEAD").stdout.strip()

    def reset(self) -> None:
        """Reset to the initial commit, even if the candidate moved HEAD."""
        self._git("reset", "--hard", "-q", self.base_commit)
        self._git("clean", "-fdxq")

    def changed_files(self) -> list[str]:
        from verifier.diff_analyzer import DiffAnalyzer
        result = DiffAnalyzer().analyze(self.path, base_commit=self.base_commit)
        if not result.valid:
            raise WorkspaceError(result.error)
        return result.changed_files

    def capture(self) -> dict[str, bytes]:
        """Capture file contents for replaying a paired first attempt."""
        return _workspace_files(self.path)

    def restore_snapshot(self, snapshot: dict[str, bytes]) -> None:
        self.reset()
        for name in set(self.capture()) - set(snapshot):
            (self.path / name).unlink()
        # Files may replace an entire former directory tree. Remove empty
        # directories bottom-up before materialising the captured file map.
        for directory in sorted(self.path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if not directory.is_dir() or ".git" in directory.relative_to(self.path).parts:
                continue
            try:
                directory.rmdir()
            except OSError:
                pass  # Non-empty directories are still used by the snapshot.
        for name, content in snapshot.items():
            path = (self.path / name).resolve()
            if self.path not in path.parents or ".git" in Path(name).parts:
                raise WorkspaceError(f"Snapshot path escapes workspace: {name}")
            if path.is_dir():
                path.rmdir()  # Obsolete file contents were removed above.
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def cleanup(self) -> None:
        self.baseline_for(self.path)
        if self.path.exists():
            _force_remove(self.path)
        _BASELINES.pop(str(self.path), None)

