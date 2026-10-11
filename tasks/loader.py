"""Task loader.

Reads ``taskNNN.yaml`` definitions, resolves the target repository, and binds
named requirement checks from ``checks.py`` next to the YAML file.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import shlex
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

import yaml

import config
from core.models import Task

PathLike = str | Path


class TaskLoader:
    def __init__(
        self,
        tasks_dir: PathLike | None = None,
        repositories_dir: PathLike | None = None,
    ) -> None:
        self.tasks_dir = Path(tasks_dir or config.TASKS_DIR)
        self.repositories_dir = Path(repositories_dir or config.REPOSITORIES_DIR)

    # -- discovery ---------------------------------------------------------
    def discover(self, repository: str | None = None) -> list[Path]:
        base = self.tasks_dir / repository if repository else self.tasks_dir
        return sorted(p for p in base.glob("**/task*.yaml"))

    def load_all(self, repository: str | None = None) -> list[Task]:
        tasks = [self.load(path) for path in self.discover(repository)]
        identities: set[tuple[str, str]] = set()
        for task in tasks:
            identity = (task.repository.casefold(), task.task_id.casefold())
            if identity in identities:
                raise ValueError(f"Duplicate task identity: {task.repository}/{task.task_id}")
            identities.add(identity)
        return tasks

    def load(self, path: PathLike) -> Task:
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Task definition must be a YAML mapping: {path}")
        for field in ("task_id", "repository", "description"):
            if field not in data or not str(data[field]).strip():
                raise ValueError(f"Task definition has no {field}: {path}")
        for field in ("task_id", "repository"):
            value = str(data[field])
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
                raise ValueError(f"{field} must be a safe identifier: {path}")
        repo_dir = (self.repositories_dir / str(data["repository"])).resolve()
        if not repo_dir.is_relative_to(self.repositories_dir.resolve()) or not repo_dir.is_dir():
            raise ValueError(f"Task repository is missing or outside repositories_dir: {path}")
        for field in ("allowed_files", "requirements"):
            value = data.get(field, [])
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise ValueError(f"{field} must be a list of nonempty strings: {path}")
            if len(value) != len(set(value)):
                raise ValueError(f"{field} contains duplicate entries: {path}")
        if not data.get("requirements"):
            raise ValueError(f"Task needs at least one executable requirement: {path}")
        for filename in data.get("allowed_files", []):
            relative = PurePosixPath(filename.replace("\\", "/"))
            if (
                PureWindowsPath(filename).drive or relative.is_absolute()
                or ".." in relative.parts or ".git" in [part.casefold() for part in relative.parts]
                or not relative.parts
            ):
                raise ValueError(f"allowed_files must stay inside the candidate repository: {path}")
        if data.get("metadata") is not None and not isinstance(data["metadata"], dict):
            raise ValueError(f"metadata must be a mapping: {path}")
        test_command = data.get("test_command", "python -m pytest -q")
        if not isinstance(test_command, str) or not test_command.strip():
            raise ValueError(f"test_command must be a nonempty string: {path}")
        metadata = dict(data.get("metadata") or {})
        if "expected_test_nodes" in metadata:
            nodes = metadata["expected_test_nodes"]
            if not isinstance(nodes, list) or not nodes or not all(isinstance(node, str) and node for node in nodes):
                raise ValueError(f"expected_test_nodes must be a nonempty list of node IDs: {path}")
            if len(nodes) != len(set(nodes)):
                raise ValueError(f"expected_test_nodes contains duplicates: {path}")
        requirement_names = list(data.get("requirements") or [])

        task = Task(
            task_id=str(data["task_id"]),
            repository=str(data["repository"]),
            description=data.get("description", ""),
            allowed_files=list(data.get("allowed_files") or []),
            requirements=requirement_names,
            test_command=test_command,
            max_retries=int(data.get("max_retries", config.DEFAULT_MAX_RETRIES)),
            metadata=metadata,
            repo_dir=str(repo_dir),
            task_dir=str(path.parent),
        )
        if task.max_retries < 0:
            raise ValueError(f"max_retries must not be negative: {path}")
        self._bind_expected_nodes(task)
        self._bind_checks(task, path.parent, requirement_names)
        return task

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _bind_expected_nodes(task: Task) -> None:
        """Snapshot simple reviewed seed tests before the candidate may edit them.

        Runtime collection must contain these nodes; additional legitimate tests
        are allowed. Parameterised/dynamic collections need a reviewed explicit
        manifest instead of guessing their generated IDs.
        """
        if "expected_test_nodes" in task.metadata:
            task.metadata.setdefault("expected_test_nodes_source", "authored")
            return
        try:
            argv = shlex.split(task.test_command, posix=os.name != "nt")
            files = [part.strip('"') for part in argv if part.endswith(".py")]
            if not files:
                task.metadata["expected_test_nodes_source"] = "not_inferred: no explicit test files"
                return
            nodes = []
            for filename in files:
                tree = ast.parse((Path(task.repo_dir) / filename).read_text(encoding="utf-8"))
                if any(
                    isinstance(node, ast.FunctionDef) and node.name == "pytest_generate_tests"
                    or isinstance(node, ast.Attribute) and node.attr == "parametrize"
                    for node in ast.walk(tree)
                ):
                    task.metadata["expected_test_nodes_source"] = "not_inferred: dynamic or parameterised tests"
                    return
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                        nodes.append(f"{Path(filename).as_posix()}::{node.name}")
                    elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                        for method in node.body:
                            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_"):
                                nodes.append(f"{Path(filename).as_posix()}::{node.name}::{method.name}")
            if nodes:
                task.metadata["expected_test_nodes"] = sorted(set(nodes))
                task.metadata["expected_test_nodes_source"] = "seed_test_ast"
            else:
                task.metadata["expected_test_nodes_source"] = "not_inferred: no simple test nodes"
        except (OSError, SyntaxError, ValueError):
            task.metadata["expected_test_nodes_source"] = "not_inferred: unreadable test definition"

    def _bind_checks(self, task: Task, task_dir: Path, names: list[str]) -> None:
        module = self._load_module(task_dir / "checks.py")
        checks: list[tuple[str, Callable[..., Any]]] = []
        for name in names:
            func = getattr(module, name, None) if module else None
            if callable(func):
                checks.append((name, func))
            else:
                raise ValueError(f"Requirement '{name}' has no executable implementation in {task_dir / 'checks.py'}")
        task.requirement_checks = checks

    @staticmethod
    def _load_module(path: Path):
        if not path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            f"vericoder_checks_{path.parent.name}", path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
