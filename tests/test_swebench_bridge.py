import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from experiments import swebench


def instance(index=1):
    return {"instance_id": f"example__project-{index}", "repo": "example/project",
            "base_commit": "a" * 40, "problem_statement": "Fix behavior", "patch": "gold patch",
            "test_patch": "test patch", "version": "1.0", "FAIL_TO_PASS": '["test_bug"]',
            "PASS_TO_PASS": '["test_regression"]'}


def imported(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps([instance()]), encoding="utf-8")
    return swebench.import_instances(source, "example/dataset", "test", tmp_path / "instances.json")


def predictions(tmp_path, rows=None):
    path = tmp_path / "predictions.jsonl"
    values = rows if rows is not None else [{"instance_id": instance()["instance_id"],
                                           "model_name_or_path": "provider/model", "model_patch": "candidate"}]
    path.write_text("\n".join(json.dumps(row) for row in values), encoding="utf-8")
    return path


def mock_dependencies(monkeypatch, available=True):
    monkeypatch.setattr(swebench.shutil, "which", lambda name: "docker" if available else None)
    monkeypatch.setattr(swebench.importlib.util, "find_spec", lambda name: object() if available else None)


def test_import_records_and_checks_hash(tmp_path, monkeypatch):
    path = imported(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sha256"] == swebench._digest(data["instances"])
    assert data["instance_ids"] == [instance()["instance_id"]]
    assert data["contains_gold_patches"] is True
    data["instances"][0]["patch"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        swebench.evaluate_instances(path, None, "test", tmp_path / "runs", gold=True)


def test_fetch_keeps_complete_source_rows_and_rejects_overwrite(tmp_path, monkeypatch):
    urls = []
    def get(url, timeout):
        urls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"rows": [{"row": instance(i), "truncated_cells": []} for i in range(10)], "partial": False})
    monkeypatch.setattr(swebench.requests, "get", get)
    output = tmp_path / "download.json"
    swebench.fetch_instances("princeton-nlp/SWE-bench_Lite", "test", 10, output)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["count"] == 10
    assert data["source"] == urls
    assert "length=10" in urls[0] and "offset=0" in urls[0]
    with pytest.raises(ValueError, match="overwrite"):
        swebench.fetch_instances("princeton-nlp/SWE-bench_Lite", "test", 10, output)
    assert len(urls) == 1


@pytest.mark.parametrize("payload", [{"rows": [], "partial": False},
                                    {"rows": [{"row": instance(), "truncated_cells": ["patch"]}]},
                                    {"rows": [{"row": instance()}], "partial": True}])
def test_fetch_rejects_incomplete_data(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(swebench.requests, "get", lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload))
    with pytest.raises(ValueError):
        swebench.fetch_instances("dataset", "test", 1, tmp_path / "bad.json")
    assert not (tmp_path / "bad.json").exists()


def test_missing_dependencies_persist_blocked_without_invented_scores(tmp_path, monkeypatch):
    path = imported(tmp_path)
    mock_dependencies(monkeypatch, False)
    monkeypatch.setattr(swebench.subprocess, "run", lambda *a, **kw: pytest.fail("must not execute anything"))
    result = swebench.evaluate_instances(path, None, "blocked", tmp_path / "runs", gold=True)
    saved = json.loads((tmp_path / "runs/blocked/evaluation.json").read_text(encoding="utf-8"))
    assert saved == result
    assert saved["status"] == "blocked"
    assert len(saved["reasons"]) == 2 and saved["scores"] is None and saved["returncode"] is None
    assert saved["evidence_kind"] == "reference_patch_harness_check"
    assert "--dataset_name" in saved["command"]


def test_predictions_validated_before_launch(tmp_path):
    path = imported(tmp_path)
    bad = predictions(tmp_path, [{"instance_id": "unknown", "model_patch": "", "model_name_or_path": "x"}])
    with pytest.raises(ValueError, match="unknown"):
        swebench.evaluate_instances(path, bad, "bad", tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("report_name,returncode,status", [("report.json", 0, "completed"),
                                                         ("run_metadata.json", 0, "failed"),
                                                         (None, 0, "failed"), (None, 1, "failed")])
def test_official_harness_command_and_evidence(tmp_path, monkeypatch, report_name, returncode, status):
    path = imported(tmp_path)
    pred = predictions(tmp_path)
    mock_dependencies(monkeypatch)
    calls = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential-must-not-reach-harness")
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == "docker":
            return subprocess.CompletedProcess(argv, 0, stdout="1.0", stderr="")
        assert "DEEPSEEK_API_KEY" not in kwargs["env"]
        if report_name:
            report = kwargs["cwd"] / "logs/evaluation/study/provider__model/example__project-1" / report_name
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({"example__project-1": {"resolved": True}}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, returncode)
    monkeypatch.setattr(swebench.subprocess, "run", run)
    result = swebench.evaluate_instances(path, pred, "study", tmp_path / "runs")
    command = calls[1][0]
    assert command[1:3] == ["-m", "swebench.harness.run_evaluation"]
    assert command[command.index("--dataset_name") + 1].endswith("instances.json")
    assert result["status"] == status and result["scores"] is None
    assert result["evidence_kind"] == "agent_predictions"
    assert result["returncode"] == returncode
    with pytest.raises(ValueError, match="reuse"):
        swebench.evaluate_instances(path, pred, "study", tmp_path / "runs")


def test_unavailable_docker_daemon_prevents_harness(tmp_path, monkeypatch):
    path = imported(tmp_path)
    mock_dependencies(monkeypatch)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="daemon missing")
    monkeypatch.setattr(swebench.subprocess, "run", run)
    result = swebench.evaluate_instances(path, None, "daemon", tmp_path / "runs", gold=True)
    assert result["status"] == "blocked" and len(calls) == 1
    assert result["reasons"] == ["Docker daemon is unavailable"]


def test_network_failure_does_not_create_fake_instances(tmp_path, monkeypatch):
    def get(*args, **kwargs):
        raise swebench.requests.ConnectTimeout("offline")
    monkeypatch.setattr(swebench.requests, "get", get)
    with pytest.raises(RuntimeError, match="no benchmark was imported"):
        swebench.fetch_instances("dataset", "test", 10, tmp_path / "missing.json")
    assert not (tmp_path / "missing.json").exists()


def test_import_jsonl_and_duplicate_ids(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(json.dumps(instance(i)) for i in range(2)), encoding="utf-8")
    path = swebench.import_instances(source, "dataset", "test", tmp_path / "good.json", source="official fixture")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["count"] == 2 and data["source"] == "official fixture"
    source.write_text("\n".join(json.dumps(instance()) for i in range(2)), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate instance_id"):
        swebench.import_instances(source, "dataset", "test", tmp_path / "bad.json")
