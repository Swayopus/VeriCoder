"""Host-side validation of reviewed Python requirement execution receipts.

This detects early exits and incomplete execution. It is not an adversarial
proof: arbitrary Python in the same process can tamper with a local protocol.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from sandbox.execution import IO_DIRECTORY_ENV, TRUSTED_HELPERS, run_command


@dataclass
class RequirementExecution:
    passed: bool
    message: str
    valid: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Any]:
        yield self.passed
        yield self.message


def run_python_check(repo_dir: str | Path, code: str, timeout: int = 60) -> RequirementExecution:
    nonce = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="vericoder-check-") as scratch:
        directory = Path(scratch)
        code_path, report_path = directory / "check.py", directory / "receipt.json"
        code_path.write_text(code, encoding="utf-8")
        try:
            proc = run_command(
                [sys.executable, "-B", str(TRUSTED_HELPERS / "requirement_runner.py"),
                 str(code_path), str(report_path), nonce],
                cwd=repo_dir, timeout=timeout, read_only=True,
                env={IO_DIRECTORY_ENV: scratch, "PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONPATH": "", "PYTHONOPTIMIZE": ""},
            )
        except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError) as exc:
            return RequirementExecution(False, f"Requirement execution unavailable: {exc}", False)
        output = (proc.stdout + "\n" + proc.stderr).strip()[-1200:]
        try:
            receipt = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(receipt, dict):
                return RequirementExecution(False, "Malformed requirement completion receipt", False)
        except (OSError, ValueError):
            return RequirementExecution(False, "Missing requirement completion receipt\n" + output, False)
        complete = (receipt.get("protocol") == 1 and receipt.get("nonce") == nonce
                    and receipt.get("completed") is True)
        valid = complete and receipt.get("valid") is True
        passed = valid and receipt.get("passed") is True and proc.returncode == 0
        if complete and receipt.get("passed") is True and proc.returncode != 0:
            valid = False
        message = receipt.get("message") or output or "Requirement assertions completed"
        return RequirementExecution(passed, str(message), valid, receipt)
