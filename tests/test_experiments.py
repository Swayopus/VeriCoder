from pathlib import Path

import config
from agent.scripted import ScriptedAgent
from experiments.baseline import SPEC as BASELINE_SPEC
from experiments.runner import ExperimentRunner
from experiments.vericoder import SPEC as VERICODER_SPEC
from tasks.loader import TaskLoader

TASK001 = Path(config.TASKS_DIR) / "todo" / "task001.yaml"


def _run(spec, tmp_path, scenario):
    task = TaskLoader().load(TASK001)
    runner = ExperimentRunner(spec, work_root=tmp_path / spec.name)
    return runner.run([task], agent_factory=lambda _task: ScriptedAgent(scenario=scenario))[0]


def test_baseline_cannot_recover_from_sneaky_agent(tmp_path):
    result = _run(BASELINE_SPEC, tmp_path, "modify_test")
    assert result.success is False
    assert result.retries == 0


def test_vericoder_feedback_loop_recovers(tmp_path):
    result = _run(VERICODER_SPEC, tmp_path, "modify_test")
    assert result.success is True
    assert result.retries == 1
    assert result.first_attempt_success is False
