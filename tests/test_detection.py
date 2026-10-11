from types import SimpleNamespace

from report.detection import (
    Observation,
    bootstrap_ci,
    cumulative_prediction,
    evaluate,
    metrics_for,
    signals_from_report,
)


def _obs(label, tests=False, diff=False, trace=False, requirements=False):
    return Observation(
        task_id="001",
        repository="demo",
        mutation="m",
        label=label,
        signals={
            "tests": tests,
            "diff": diff,
            "trace": trace,
            "requirements": requirements,
        },
    )


def test_signals_from_report():
    report = SimpleNamespace(
        test_result={"passed": True},
        diff_result={"out_of_scope_files": ["a.py"], "test_files_modified": []},
        trace_result={"suspicious": False},
        requirement_result={"failed_count": 0},
    )
    assert signals_from_report(report) == {
        "tests": False,
        "diff": True,
        "trace": False,
        "requirements": False,
    }


def test_cumulative_detection_is_monotonic():
    obs = _obs(label=1, requirements=True)
    assert cumulative_prediction(obs, "tests") is False
    assert cumulative_prediction(obs, "requirements") is True


def test_confusion_and_metrics():
    observations = [
        _obs(label=0),  # TN
        _obs(label=1, tests=True),  # caught by tests
        _obs(label=1, diff=True),  # caught by diff
        _obs(label=1, requirements=True),  # caught only by requirements
        _obs(label=0, diff=True),  # false positive for diff+
    ]

    tests_only = metrics_for(observations, "tests")
    assert (tests_only.tp, tests_only.fp, tests_only.fn, tests_only.tn) == (1, 0, 2, 2)
    assert tests_only.recall == 1 / 3

    diff_stage = metrics_for(observations, "diff")
    assert (diff_stage.tp, diff_stage.fp, diff_stage.fn, diff_stage.tn) == (3, 1, 0, 1)
    assert diff_stage.false_positive_rate == 1 / 2

    full = metrics_for(observations, "trace")
    assert (full.tp, full.fp, full.fn, full.tn) == (3, 1, 0, 1)
    assert full.recall == 1.0
    assert full.f1 == 2 * (3 / 4) * 1.0 / ((3 / 4) + 1.0)


def test_evaluate_returns_one_metric_per_stage():
    stages = [m.stage for m in evaluate([_obs(label=0)])]
    assert stages == ["tests", "requirements", "diff", "trace"]


def test_bootstrap_ci_is_bounded_and_deterministic():
    observations = [_obs(label=1, tests=True) for _ in range(5)] + [_obs(label=0) for _ in range(5)]
    lo, hi = bootstrap_ci(observations, "requirements", "recall", seed=1)
    assert 0.0 <= lo <= hi <= 1.0
    assert (lo, hi) == bootstrap_ci(observations, "requirements", "recall", seed=1)
