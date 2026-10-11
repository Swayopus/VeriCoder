from pathlib import Path

import pytest
import yaml

import config
from tasks.loader import TaskLoader

TASK001 = Path(config.TASKS_DIR) / "todo" / "task001.yaml"


def test_load_task_binds_checks():
    task = TaskLoader().load(TASK001)
    assert task.task_id == "001"
    assert task.repository == "todo-app"
    names = [name for name, _ in task.requirement_checks]
    assert names == ["check_due_date_in_response", "check_old_api_compatible"]
    assert all(callable(func) for _, func in task.requirement_checks)


def test_load_all_discovers_suites():
    tasks = TaskLoader().load_all()
    repositories = {task.repository for task in tasks}
    assert {"todo-app", "blog-system", "mini-shop"} <= repositories
    assert len(tasks) >= 5


def test_repo_dir_resolves():
    task = TaskLoader().load(TASK001)
    assert Path(task.repo_dir).is_dir()
    assert (Path(task.repo_dir) / "models.py").is_file()


def _definition(tmp_path, **changes):
    repositories = tmp_path / "repositories"
    (repositories / "sample").mkdir(parents=True, exist_ok=True)
    definitions = tmp_path / "tasks" / "sample"
    definitions.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": "001", "repository": "sample", "description": "A reviewed contract",
        "allowed_files": ["api.py"], "requirements": ["check_result"],
    }
    data.update(changes)
    path = definitions / "task001.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (definitions / "checks.py").write_text("def check_result(repo_dir):\n    return True, 'ok'\n", encoding="utf-8")
    return TaskLoader(tmp_path / "tasks", repositories), path


def test_missing_requirement_is_configuration_error(tmp_path):
    loader, path = _definition(tmp_path, requirements=["missing_check"])
    with pytest.raises(ValueError, match="no executable implementation"):
        loader.load(path)


def test_duplicate_identity_is_rejected_before_experiment(tmp_path):
    loader, path = _definition(tmp_path)
    path.with_name("task_duplicate.yaml").write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="Duplicate task identity"):
        loader.load_all()


@pytest.mark.parametrize("field,value", [
    ("repository", "../outside"), ("task_id", "../../escaped"),
    ("allowed_files", ["../outside.py"]), ("allowed_files", ["C:\\outside.py"]),
    ("allowed_files", [".GIT/config"]), ("requirements", []),
    ("requirements", ["check_result", "check_result"]),
    ("metadata", {"expected_test_nodes": "test_one.py::test_case"}),
])
def test_invalid_contract_configuration_fails_early(tmp_path, field, value):
    loader, path = _definition(tmp_path, **{field: value})
    with pytest.raises(ValueError):
        loader.load(path)
