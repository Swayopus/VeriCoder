"""Contract fixtures validate task oracles, not an agent's measured performance."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.scripted import ScriptedAgent
from core.models import Task
from core.workspace import Workspace
from tasks.loader import TaskLoader
from verifier.requirement_checker import RequirementChecker
from verifier.test_validator import TestValidator as CandidateTestValidator


TASKS = TaskLoader().load_all()
TASK_IDS = [f"{task.repository}-{task.task_id}" for task in TASKS]
BASELINE_TESTS = {
    "todo-app": "test_todo.py", "blog-system": "test_blog.py",
    "mini-shop": "test_shop.py", "payments-api": "test_bank.py",
    "auth-service": "test_auth.py",
}


def _workspace(tmp_path, task, scenario="good"):
    workspace = Workspace.prepare(task.repo_dir, tmp_path / f"{task.repository}-{task.task_id}")
    result = ScriptedAgent(scenario, recover_on_retry=False).run(task, str(workspace.path))
    assert not result.error
    return workspace


@pytest.mark.parametrize("task", TASKS, ids=TASK_IDS)
def test_every_good_reference_satisfies_the_full_task_contract(tmp_path, task):
    workspace = _workspace(tmp_path, task)
    tests = CandidateTestValidator(
        task.test_command, expected_nodes=task.metadata["expected_test_nodes"]
    ).run(workspace.path)
    assert tests.valid and tests.passed, tests.to_dict()
    requirements = RequirementChecker().run(task.requirement_checks, workspace.path)
    assert requirements.valid and requirements.passed, requirements.to_dict()


@pytest.mark.parametrize("task", TASKS, ids=TASK_IDS)
def test_every_partial_reference_still_has_an_executable_contract_violation(tmp_path, task):
    workspace = _workspace(tmp_path, task, "omit_requirement")
    requirements = RequirementChecker().run(task.requirement_checks, workspace.path)
    assert requirements.valid and not requirements.passed, requirements.to_dict()


def test_all_task_definitions_bind_reviewed_checks_and_baseline_regressions():
    assert len(TASKS) == 30
    for task in TASKS:
        assert BASELINE_TESTS[task.repository] in task.test_command.split()
        assert len(task.requirement_checks) == len(set(task.requirements))
        assert all(check.__module__.startswith("vericoder_checks_") for _, check in task.requirement_checks)
        assert task.metadata["expected_test_nodes_source"] == "seed_test_ast"
        assert task.metadata["expected_test_nodes"]
        path = Path(task.task_dir) / "checks.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        adapter = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run")
        assert len(adapter.body) == 1 and isinstance(adapter.body[0], ast.Return)
        assert adapter.body[0].value.func.id == "run_python_check"


def _task(repository, task_id):
    return next(task for task in TASKS if task.repository == repository and task.task_id == task_id)


def _change(workspace, filename, old, new):
    path = workspace.path / filename
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new), encoding="utf-8")


def _assert_contract_rejects(workspace, task, name):
    result = dict(task.requirement_checks)[name](str(workspace.path))
    assert result.valid and not result.passed, result


def test_amount_contract_detects_transfer_validation_omitted(tmp_path):
    task = _task("payments-api", "005")
    workspace = _workspace(tmp_path, task)
    path = workspace.path / "api.py"
    content = path.read_text(encoding="utf-8")
    before, transfer = content.split('    @app.post("/transfers")', 1)
    old = (
        "        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:\n"
        '            return jsonify({"error": "amount must be positive"}), 400\n'
    )
    assert old in transfer
    transfer = transfer.replace(old, "", 1)
    path.write_text(before + '    @app.post("/transfers")' + transfer, encoding="utf-8")
    _assert_contract_rejects(workspace, task, "check_negative_amount")
    _assert_contract_rejects(workspace, task, "check_zero_amount")
    _assert_contract_rejects(workspace, task, "check_nonnumeric_amount")


def test_ledger_contract_detects_transfers_missing_from_ledger(tmp_path):
    task = _task("payments-api", "002")
    workspace = _workspace(tmp_path, task)
    for account, kind in [("from_id", "transfer_out"), ("to_id", "transfer_in")]:
        _change(workspace, "models.py", f'        self._record({account}, "{kind}", amount)\n', "")
    _assert_contract_rejects(workspace, task, "check_ledger")


def test_statement_contract_detects_missing_count(tmp_path):
    task = _task("payments-api", "006")
    workspace = _workspace(tmp_path, task)
    _change(workspace, "api.py", ', "count": len(transactions)', "")
    _assert_contract_rejects(workspace, task, "check_statement_count")


def test_rate_limit_contract_detects_permanent_lockout(tmp_path):
    task = _task("auth-service", "006")
    workspace = _workspace(tmp_path, task)
    anchor = "        user = store.authenticate(username, password)\n"
    old_bug = (
        "        if store.login_failures.get(username, 0) >= 3:\n"
        '            return jsonify({"error": "too many failed attempts"}), 429\n'
    )
    _change(workspace, "api.py", anchor, old_bug + anchor)
    _assert_contract_rejects(workspace, task, "check_rate_limit")


def test_hash_contract_detects_fixed_placeholder(tmp_path):
    task = _task("auth-service", "001")
    workspace = _workspace(tmp_path, task)
    _change(
        workspace, "models.py",
        'generate_password_hash(password, method="pbkdf2:sha256:600000")',
        '"x" * 64',
    )
    _assert_contract_rejects(workspace, task, "check_password_hashed")


def test_hash_login_contract_detects_accepting_wrong_password(tmp_path):
    task = _task("auth-service", "001")
    workspace = _workspace(tmp_path, task)
    _change(
        workspace, "models.py",
        "user is None or not check_password_hash(user.password, password)",
        "user is None",
    )
    _assert_contract_rejects(workspace, task, "check_login_after_hash")


def test_priority_contract_detects_missing_put_support(tmp_path):
    task = _task("todo-app", "006")
    workspace = _workspace(tmp_path, task)
    _change(workspace, "api.py", '                priority=data.get("priority"),\n', "")
    _assert_contract_rejects(workspace, task, "check_priority_roundtrip")


def test_pagination_contract_detects_returning_the_first_page_every_time(tmp_path):
    task = _task("todo-app", "002")
    workspace = _workspace(tmp_path, task)
    _change(workspace, "api.py", "start = (page_num - 1) * limit_num", "start = 0")
    _assert_contract_rejects(workspace, task, "check_pagination")


def test_stock_contract_detects_ignoring_duplicate_cart_entries(tmp_path):
    task = _task("mini-shop", "001")
    workspace = _workspace(tmp_path, task)
    _change(
        workspace, "models.py",
        'quantities[product_id] = quantities.get(product_id, 0) + entry["quantity"]',
        'quantities[product_id] = entry["quantity"]',
    )
    _assert_contract_rejects(workspace, task, "check_stock_guard")


def test_weakening_candidate_tests_does_not_weaken_trusted_auth_contract(tmp_path):
    task = _task("auth-service", "007")
    workspace = _workspace(tmp_path, task, "modify_test")
    requirements = RequirementChecker().run(task.requirement_checks, workspace.path)
    assert requirements.valid and not requirements.passed, requirements.to_dict()


def test_expected_node_manifest_preserves_authored_values_and_skips_parametrization(tmp_path):
    task = Task("custom", "custom", "custom", repo_dir=str(tmp_path), test_command="python -m pytest test_custom.py")
    path = tmp_path / "test_custom.py"
    path.write_text('import pytest\n@pytest.mark.parametrize("n", [1, 2])\ndef test_one(n):\n    assert n\n', encoding="utf-8")
    TaskLoader._bind_expected_nodes(task)
    assert "expected_test_nodes" not in task.metadata
    assert "parameterised" in task.metadata["expected_test_nodes_source"]
    task.metadata["expected_test_nodes"] = ["reviewed-id"]
    TaskLoader._bind_expected_nodes(task)
    assert task.metadata["expected_test_nodes"] == ["reviewed-id"]


def test_expected_node_manifest_includes_test_class_methods(tmp_path):
    (tmp_path / "test_custom.py").write_text(
        "def test_function():\n    pass\n\nclass TestGroup:\n    def test_method(self):\n        pass\n",
        encoding="utf-8",
    )
    task = Task("custom", "custom", "custom", repo_dir=str(tmp_path), test_command="python -m pytest test_custom.py")
    TaskLoader._bind_expected_nodes(task)
    assert task.metadata["expected_test_nodes"] == [
        "test_custom.py::TestGroup::test_method", "test_custom.py::test_function",
    ]
