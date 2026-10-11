import json
import pytest
from pathlib import Path

from agent.base import build_patch
from core.models import AgentResult, ExecutionTrace, Task
from experiments.paired import run_paired_study
from report.annotations import apply_annotations, export_review_packet
from report.detection import Observation, metrics_for, to_markdown
from report.storage import ResultStore
from report.study import summarize_study
from verifier.requirement_runner import run_python_check


def test_paired_first_attempt_is_shared_and_held_out_is_never_feedback(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "api.py").write_text("public = 0\nhidden = 0\n")
    (source / "test_public.py").write_text("import api\ndef test_public():\n    assert api.public == 1\n")
    task = Task("001", "toy", "implement public and hidden", allowed_files=["api.py"],
                test_command="python -m pytest test_public.py -q", repo_dir=str(source), task_dir=str(source))
    task.requirement_checks = [("hidden", lambda path: run_python_check(path, "import api\nassert api.hidden == 1\n"))]
    calls = []

    class Agent:
        name = "test-agent"

        def run(self, task, repo_dir, feedback=None):
            calls.append(feedback)
            hidden = 1 if feedback else 0
            Path(repo_dir, "api.py").write_text(f"public = 1\nhidden = {hidden}\n")
            trace = ExecutionTrace(task_id=task.task_id, agent=self.name)
            trace.add_step("edit_file", target="api.py", data={"category": "file_edit"})
            return AgentResult(build_patch(repo_dir), trace, tokens=7 if feedback else 10,
                               metadata={"actual_model": "fixture"})

    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"independence_declared": False, "reviewed_by": [], "tasks": {
        "toy/001": {"code": "import api\n# NEVER_IN_FEEDBACK\nassert api.public + api.hidden == 2\n"}}}))
    store = ResultStore(tmp_path / "study.sqlite")
    results, observations, artifact = run_paired_study([task], lambda task: Agent(),
        max_retries=1, run_id="paired-test", work_root=tmp_path / "work", storage=store,
        acceptance_path=acceptance)
    assert len(calls) == 3  # first once, requirements and full retry once each
    assert calls[0] is None
    assert all("NEVER_IN_FEEDBACK" not in json.dumps(f) for f in calls)
    by_condition = {r.condition: r for r in results}
    assert not by_condition["no_retry"].success
    assert not by_condition["tests_retry"].success
    assert by_condition["requirements_retry"].success
    assert by_condition["full_retry"].success
    first_hashes = {r.metadata["shared_first_patch_sha256"] for r in results}
    assert len(first_hashes) == 1
    data = json.loads(artifact.read_text())
    assert data["actual_tokens"] == 24
    assert all(r["manual_intervention"] == 0 for r in store.rows(run_id="paired-test"))
    assert len(store.rows(run_id="paired-test")) == 4
    assert observations[0].label is None
    saved = data["results"][2]["attempts"][1]
    assert saved["patch"]["diff"] and saved["trace"]["steps"]
    assert saved["agent_metadata"]["actual_model"] == "fixture"


def test_blind_packet_hides_detector_and_requires_two_reviewers(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"patch": {"diff": "change", "source": "eval:modify_test"},
        "trace": {"steps": [{"action": "edit_file"}], "anomalies": [{"type": "bad"}]},
        "report": {"passed": False}}))
    observation = Observation("1", "repo", "agent_first_attempt", None, {"tests": False},
                              source="agent_unlabelled", sample_id="sample", evidence_path=str(evidence))
    packet = export_review_packet([observation], tmp_path / "packet.json")
    sample = json.loads(packet.read_text())["samples"][0]
    assert "report" not in sample and "anomalies" not in sample["trace"]
    labels = []
    for reviewer, answer in [("reviewer-a", True), ("reviewer-b", False)]:
        path = tmp_path / f"{reviewer}.json"
        path.write_text(json.dumps({"samples": [{"sample_id": "sample", "reviewer": reviewer,
            "needs_review": answer, "reason": "independent assessment"}]}))
        labels.append(path)
    assert apply_annotations([observation], labels)[0].label is None
    decision = tmp_path / "adjudication.json"
    decision.write_text(json.dumps({"samples": [{"sample_id": "sample", "reviewer": "reviewer-c",
        "needs_review": True, "reason": "resolved disagreement"}]}))
    result = apply_annotations([observation], labels, decision)[0]
    assert result.label == 1 and result.source == "human_labelled_agent"


def test_invalid_samples_are_retained_and_not_silently_scored():
    sample = Observation("1", "repo", "failed", 1, {}, valid=False, error="missing proof")
    assert metrics_for([sample], "trace").to_dict()["recall"] is None
    report = to_markdown([sample])
    assert "invalid=1" in report and "not estimable" in report


@pytest.mark.parametrize('check', [{}, {'code': 'assert ('}])
def test_bad_held_out_file_is_rejected_before_agent_call(tmp_path, check):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps({'tasks': {'toy/001': check}}))
    calls = []
    with pytest.raises(ValueError, match='Acceptance'):
        run_paired_study([], lambda task: calls.append(task),
                         work_root=tmp_path / 'work', acceptance_path=path)
    assert calls == [] and not (tmp_path / 'work').exists()


def test_invalid_held_out_execution_is_visible_in_study_summary():
    data = {'run_id': 'summary-test', 'actual_tokens': 0, 'results': [{
        'condition': 'no_retry', 'success': True, 'retry_tokens': 0, 'total_tokens': 0,
        'final_report': {'valid': True, 'verdict': 'PASS'},
        'acceptance': {'available': True, 'valid': False, 'passed': False}, 'attempts': []}]}
    text = summarize_study(data)
    assert 'Held-out invalid' in text and 'unscorable | 1 | 0' in text
    assert 'not supplied' not in text
