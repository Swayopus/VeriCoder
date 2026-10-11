"""Import real SWE-bench instances and delegate grading to its official harness.

The import is data only. Repository code is never executed by this bridge itself.
Sources: https://huggingface.co/docs/dataset-viewer/en/rows and
https://www.swebench.com/SWE-bench/guides/evaluation/ .
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlencode

import requests

from core.artifacts import validate_run_id, write_json
from core.models import utcnow


VIEWER = "https://datasets-server.huggingface.co/rows"
REQUIRED = ("instance_id", "repo", "base_commit", "problem_statement", "patch", "test_patch", "version", "FAIL_TO_PASS", "PASS_TO_PASS")


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("SWE-bench instances must be a nonempty list")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or any(field not in row for field in REQUIRED):
            raise ValueError(f"Every instance must contain: {', '.join(REQUIRED)}")
        instance_id = row["instance_id"]
        if not isinstance(instance_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,200}", instance_id):
            raise ValueError("Invalid instance_id")
        if instance_id in seen:
            raise ValueError(f"Duplicate instance_id: {instance_id}")
        seen.add(instance_id)
        for name in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            tests = json.loads(row[name]) if isinstance(row[name], str) else row[name]
            if not isinstance(tests, list) or not all(isinstance(test, str) for test in tests):
                raise ValueError(f"{instance_id}: {name} must be a list of test names")
        if not isinstance(row["base_commit"], str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", row["base_commit"]):
            raise ValueError(f"{instance_id}: base_commit must be a full commit hash")
    return rows


def _read_json_rows(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(path.read_text(encoding="utf-8"))


def _write_instances(rows, dataset, split, output, source):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Refusing to overwrite imported instances: {output}")
    _validate_rows(rows)
    return write_json(output, {
        "schema_version": 1, "kind": "swebench_instances", "imported_at": utcnow(),
        "dataset": dataset, "split": split, "source": source, "count": len(rows),
        "sha256": _digest(rows), "instance_ids": [row["instance_id"] for row in rows],
        "selection": "ordered source slice; not a random or representative sample",
        "contains_gold_patches": True, "instances": rows,
    })


def import_instances(input_path, dataset, split, output, source=None) -> Path:
    """Import local JSON/JSONL, retaining a content hash and explicit origin."""
    raw = _read_json_rows(input_path)
    rows = raw.get("instances") if isinstance(raw, dict) else raw
    return _write_instances(rows, dataset, split, output, source or str(Path(input_path).resolve()))


def fetch_instances(dataset, split, limit, output) -> Path:
    """Download the first N complete rows from the public HF Dataset Viewer."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be positive")
    if Path(output).exists():
        raise ValueError(f"Refusing to overwrite imported instances: {output}")
    rows, sources = [], []
    while len(rows) < limit:
        url = VIEWER + "?" + urlencode({"dataset": dataset, "config": "default", "split": split,
                                        "offset": len(rows), "length": min(100, limit - len(rows))})
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not download public SWE-bench rows ({type(exc).__name__}); no benchmark was imported") from exc
        page = payload.get("rows", [])
        if not page or payload.get("partial"):
            raise ValueError("Dataset Viewer returned an incomplete slice")
        if any(item.get("truncated_cells") for item in page):
            raise ValueError("Dataset Viewer truncated instance data; refusing an incomplete benchmark")
        rows.extend(item["row"] for item in page)
        sources.append(url)
    return _write_instances(rows[:limit], dataset, split, output, sources)


def _predictions(path, expected_ids):
    raw = _read_json_rows(path)
    rows = list(raw.values()) if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("Predictions must be a nonempty JSON list/dictionary or JSONL")
    ids = []
    for row in rows:
        if not isinstance(row, dict) or row.get("instance_id") not in expected_ids:
            raise ValueError("Prediction contains an unknown or missing instance_id")
        if not isinstance(row.get("model_patch"), str):
            raise ValueError("Prediction model_patch must be a string (an empty patch is allowed)")
        model = row.get("model_name_or_path")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,200}", model):
            raise ValueError("Prediction model_name_or_path must be a safe model identifier")
        ids.append(row["instance_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate prediction instance_id")
    if set(ids) != set(expected_ids):
        raise ValueError("Provide exactly one prediction per imported instance")
    return rows


def evaluate_instances(instances_path, predictions_path, run_id, output_root, gold=False) -> dict:
    """Run official grading, or persist a blocked result when prerequisites fail.

Gold mode checks the harness with reference patches; it is never agent evidence.
    """
    validate_run_id(run_id)
    if gold and predictions_path:
        raise ValueError("Choose either gold mode or predictions_path")
    if not gold and not predictions_path:
        raise ValueError("predictions_path is required outside gold mode")
    source = Path(instances_path).resolve()
    envelope = _read_json_rows(source)
    if not isinstance(envelope, dict) or envelope.get("kind") != "swebench_instances":
        raise ValueError("Import instances with benchmark fetch/import before evaluation")
    rows = _validate_rows(envelope.get("instances"))
    if envelope.get("sha256") != _digest(rows):
        raise ValueError("Imported instances failed SHA-256 integrity validation")
    ids = [row["instance_id"] for row in rows]
    predictions = None if gold else _predictions(predictions_path, ids)
    root = Path(output_root).resolve() / run_id
    if root.exists():
        raise ValueError(f"Refusing to reuse an evaluation run directory: {root}")
    root.mkdir(parents=True, exist_ok=False)
    dataset_file = write_json(root / "instances.json", rows)
    prediction_file = "gold" if gold else str(write_json(root / "predictions.json", predictions))
    command = [sys.executable, "-m", "swebench.harness.run_evaluation", "--dataset_name", str(dataset_file),
               "--split", envelope["split"], "--predictions_path", prediction_file,
               "--instance_ids", *ids, "--run_id", run_id, "--max_workers", "1"]
    result = {"schema_version": 1, "kind": "swebench_evaluation", "run_id": run_id,
              "created_at": utcnow(), "dataset": envelope["dataset"], "split": envelope["split"],
              "instances_source": str(source), "instances_sha256": _digest(rows), "instance_ids": ids,
              "gold_mode": gold, "evidence_kind": "reference_patch_harness_check" if gold else "agent_predictions",
              "predictions_sha256": None if gold else _digest(predictions), "command": command,
              "cwd": str(root), "status": "blocked", "reasons": [], "returncode": None,
              "official_result_files": [], "scores": None}
    try:
        result["swebench_version"] = importlib.metadata.version("swebench")
    except importlib.metadata.PackageNotFoundError:
        result["swebench_version"] = None
    if importlib.util.find_spec("swebench") is None:
        result["reasons"].append("The swebench package is not installed in this Python environment")
    docker = shutil.which("docker")
    if not docker:
        result["reasons"].append("Docker CLI is not installed")
    else:
        try:
            probe = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=20)
            if probe.returncode:
                result["reasons"].append("Docker daemon is unavailable")
            result["docker_probe"] = {"returncode": probe.returncode, "stdout": probe.stdout, "stderr": probe.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["reasons"].append(f"Docker readiness check failed: {type(exc).__name__}")
    result_path = root / "evaluation.json"
    if result["reasons"]:
        write_json(result_path, result)
        return result
    result["status"] = "running"
    write_json(result_path, result)
    # Provider credentials are unrelated to grading and need not reach the harness.
    environment = {key: value for key, value in os.environ.items() if not key.upper().endswith("API_KEY")}
    environment["PYTHONUTF8"] = "1"
    try:
        with (root / "harness.stdout.log").open("w", encoding="utf-8") as stdout, (root / "harness.stderr.log").open("w", encoding="utf-8") as stderr:
            process = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr, env=environment, timeout=14400)
        result["returncode"] = process.returncode
        # Support current and older official harness report locations. Preserve raw
        # reports; return code zero alone is never interpreted as a resolved task.
        report_paths = sorted({path for path in (root / "logs" / "evaluation" / run_id).rglob("*.json")
                               if path.name in {"results.json", "report.json"}} |
                              set(root.glob(f"*.{run_id}.json")))
        result["official_result_files"] = [str(path.relative_to(root)) for path in report_paths]
        result["status"] = "completed" if process.returncode == 0 and report_paths else "failed"
        if process.returncode:
            result["reasons"].append("Official harness exited with a nonzero status; see harness.stderr.log")
        elif not report_paths:
            result["reasons"].append("Harness exited zero without writing an official result report")
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["status"] = "failed"
        result["reasons"].append(f"Harness execution failed: {type(exc).__name__}")
    result["finished_at"] = utcnow()
    write_json(result_path, result)
    return result
