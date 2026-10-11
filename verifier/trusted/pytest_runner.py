"""Launch pytest with a completion plugin loaded before candidate imports."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


class CompletionPlugin:
    def __init__(self, path: str, nonce: str) -> None:
        self.path = Path(path)
        self.receipt = {
            "protocol": 1, "nonce": nonce, "completed": False,
            "collection_completed": False, "nodes": [], "reports": [],
            "collection_errors": [],
            "collection_error_details": [],
        }

    def pytest_collection_finish(self, session):
        self.receipt["collection_completed"] = True
        self.receipt["nodes"] = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.receipt["collection_errors"].append(str(report.longrepr))
            node = report.nodeid.split('::', 1)[0]
            # A normal test-module import/collection failure is candidate failure.
            # Session traversal and paths outside the workspace are infrastructure.
            path = Path(node)
            resolved = (Path.cwd() / path).resolve()
            candidate = bool(node and path.suffix == '.py' and resolved.is_relative_to(Path.cwd()))
            self.receipt['collection_error_details'].append({
                'nodeid': report.nodeid, 'origin': 'candidate' if candidate else 'infrastructure',
                'message': str(report.longrepr),
            })

    def pytest_runtest_logreport(self, report):
        self.receipt["reports"].append({
            "nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
            "message": str(report.longrepr) if report.failed else "",
        })

    def pytest_sessionfinish(self, session, exitstatus):
        self.receipt["session_exitstatus"] = int(exitstatus)

    def save_completed(self, exitstatus):
        # Called only after pytest.main returned, not by candidate pytest hooks.
        self.receipt["completed"] = True
        self.receipt["exitstatus"] = int(exitstatus)
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")


def main() -> int:
    report_path, nonce, *pytest_args = sys.argv[1:]
    plugin = CompletionPlugin(report_path, nonce)
    # pytest has already been imported from the installed trusted environment.
    sys.path.insert(0, os.getcwd())
    status = pytest.main(pytest_args, plugins=[plugin])
    plugin.save_completed(status)
    return int(status)


if __name__ == "__main__":
    raise SystemExit(main())
