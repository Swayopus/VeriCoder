"""CLI preflight must prevent hidden retries, overwritten evidence and false success."""
import vericoder
import experiments.evaluation
import experiments.swebench


def test_eval_refuses_existing_evidence_before_running(tmp_path, monkeypatch):
    output = tmp_path / 'existing.json'
    output.write_text('original evidence')
    called = []
    monkeypatch.setattr(experiments.evaluation, 'run_evaluation', lambda *a, **k: called.append(True))
    assert vericoder.main(['eval', '--suite', 'todo', '--task', '001', '--out', str(output)]) == 2
    assert not called and output.read_text() == 'original evidence'


def test_invalid_agent_budget_is_rejected_before_call(monkeypatch):
    called = []
    monkeypatch.setattr(vericoder, '_agent_factory', lambda args: called.append(True))
    assert vericoder.main(['study', '--agent', 'deepseek', '--max-steps', '0']) == 2
    assert not called


def test_blocked_external_harness_returns_failure_status(monkeypatch, tmp_path):
    monkeypatch.setattr(experiments.swebench, 'evaluate_instances',
                        lambda *a, **k: {'status': 'blocked', 'returncode': None, 'scores': None})
    assert vericoder.main(['benchmark', 'evaluate', '--instances', 'fixture.json',
                          '--gold', '--out', str(tmp_path)]) == 2
