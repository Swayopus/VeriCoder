"""Candidate pytest sessions must not traverse changing sibling workspaces."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

import pytest

from tools.executor import ToolExecutor
from trace.recorder import TraceRecorder
from verifier.test_validator import TestValidator


@pytest.mark.parametrize('runner', ['validator', 'tool'])
def test_candidate_session_ignores_ancestor_configuration(tmp_path, runner, monkeypatch):
    monkeypatch.setenv('VERICODER_EXECUTION_BACKEND', 'local')
    (tmp_path / 'conftest.py').write_text("raise RuntimeError('host conftest loaded')\n")
    (tmp_path / 'pytest.ini').write_text('[pytest]\naddopts = --unknown-host-option\n')
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    (candidate / 'conftest.py').write_text(
        'import pytest\n@pytest.fixture\ndef local_value():\n    return 42\n')
    (candidate / 'test_api.py').write_text('def test_ok(local_value):\n    assert local_value == 42\n')
    command = 'python -m pytest test_api.py -q'
    if runner == 'validator':
        result = TestValidator(command).run(candidate)
        assert result.passed and result.valid, result.output
    else:
        result = ToolExecutor(candidate, TraceRecorder(), test_command=command).run_tests()
        assert result.ok, result.tail()


def test_candidate_import_error_remains_functional_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('VERICODER_EXECUTION_BACKEND', 'local')
    (tmp_path / 'test_bad.py').write_text('import nonexistent_candidate_module\n')
    result = TestValidator('python -m pytest test_bad.py -q').run(tmp_path)
    assert not result.passed and result.valid
    assert result.receipt['collection_error_details'][0]['origin'] == 'candidate'


def test_external_directory_collection_failure_is_invalid():
    receipt = {'protocol': 1, 'nonce': 'n', 'completed': True,
               'exitstatus': 2, 'session_exitstatus': 2,
               'collection_errors': ['sibling disappeared'],
               'collection_error_details': [{'origin': 'infrastructure'}]}
    assert 'outside candidate' in TestValidator()._validate_receipt(receipt, 'n', 2)


def test_parallel_sessions_do_not_depend_on_sibling_lifetimes(tmp_path, monkeypatch):
    monkeypatch.setenv('VERICODER_EXECUTION_BACKEND', 'local')
    def verify(index):
        candidate = tmp_path / str(index)
        candidate.mkdir()
        (candidate / 'test_ok.py').write_text('def test_ok():\n    assert True\n')
        try:
            result = TestValidator('python -m pytest test_ok.py -q').run(candidate)
            return result.passed and result.valid, result.output
        finally:
            assert candidate.resolve().is_relative_to(tmp_path.resolve())
            shutil.rmtree(candidate)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(verify, range(24)))
    assert all(passed for passed, _ in results), [output for passed, output in results if not passed]
