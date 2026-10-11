"""Versioned, replayable evidence bundles. Never store credentials here."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from core.models import Task, utcnow


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def validate_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value):
        raise ValueError("run_id must be a short filename-safe identifier")
    return value


def write_json(path: str | Path, value: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def task_manifest(task: Task) -> dict[str, Any]:
    hashes = {}
    paths = [p for p in Path(task.repo_dir).rglob('*') if p.is_file()
             and not {'.git', '__pycache__', '.pytest_cache'}.intersection(p.parts)]
    paths += [Path(task.task_dir) / f"task{task.task_id}.yaml", Path(task.task_dir) / "checks.py"]
    for path in sorted(paths):
        if path.is_file() and "__pycache__" not in path.parts:
            scope = "repository" if path.is_relative_to(Path(task.repo_dir)) else "definition"
            base = Path(task.repo_dir) if scope == "repository" else Path(task.task_dir)
            hashes[f"{scope}/{path.relative_to(base).as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    version = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"task": task.to_dict(), "sha256": version, "file_hashes": hashes}


def save_task_source(root: str | Path, task: Task, provenance: dict[str, Any]) -> Path:
    """Archive the hashed seed and oracle files, never the candidate's credentials."""
    target = Path(root) / 'sources' / (provenance['sha256'] + '.zip')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, expected in provenance['file_hashes'].items():
                scope, relative = name.split('/', 1)
                path = Path(task.repo_dir if scope == 'repository' else task.task_dir) / relative
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f'Task source changed during evidence capture: {name}')
                archive.writestr(name, content)
        temporary.replace(target)
    return target


class EvidenceBundle:
    def __init__(self, root: str | Path, run_id: str, configuration: dict[str, Any]):
        self.path = Path(root) / validate_run_id(run_id)
        self.path.mkdir(parents=True, exist_ok=False)
        framework_root = Path(__file__).resolve().parents[1]
        sources = {}
        for directory in ('agent', 'core', 'experiments', 'feedback', 'report', 'sandbox', 'tools', 'trace', 'verifier'):
            for source in (framework_root / directory).rglob('*'):
                if source.is_file() and source.suffix in {'.py', '.ini'}:
                    sources[source.relative_to(framework_root).as_posix()] = source.read_bytes()
        for name in ('config.py', 'vericoder.py', 'pyproject.toml', 'requirements.txt', 'Dockerfile'):
            source = framework_root / name
            if source.is_file():
                sources[name] = source.read_bytes()
        with zipfile.ZipFile(self.path / 'framework.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(sources.items()):
                archive.writestr(name, content)
        write_json(self.path / "manifest.json", {
            "schema_version": 2, "run_id": run_id, "created_at": utcnow(),
            "python": platform.python_version(), "platform": platform.platform(),
            "configuration": configuration,
            "framework_file_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in sources.items()},
        })

    def save_task(self, task: Task, condition: str, result: dict[str, Any]) -> Path:
        name = f"{task.repository}__{task.task_id}"
        provenance = task_manifest(task)
        snapshot = save_task_source(self.path, task, provenance)
        provenance['source_archive'] = snapshot.relative_to(self.path).as_posix()
        return write_json(self.path / condition / f"{name}.json", {
            "schema_version": 2, "provenance": provenance, "result": result,
        })
