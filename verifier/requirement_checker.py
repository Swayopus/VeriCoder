"""Requirement Checks — executable assertions, not LLM judgement.

Task definitions reference named check functions (loaded per repository from
``tasks/<repository>/checks.py``).  Every check is a callable receiving the
repository directory and returning either ``bool`` or ``(bool, message)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

RequirementCheck = Callable[[str], Any]


@dataclass
class RequirementResult:
    name: str
    passed: bool
    message: str = ""
    valid: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "message": self.message,
                "valid": self.valid, "metadata": self.metadata}


@dataclass
class RequirementSummary:
    results: list[RequirementResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.valid and all(r.passed for r in self.results)

    @property
    def valid(self) -> bool:
        return bool(self.results) and all(r.valid for r in self.results)

    @property
    def failed(self) -> list[RequirementResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "results": [r.to_dict() for r in self.results],
            "failed_count": len(self.failed),
            "valid": self.valid,
            "invalid_count": sum(not r.valid for r in self.results),
            "integrity_error": "No requirement checks were provided" if not self.results else "",
        }


class RequirementChecker:
    def run(
        self,
        checks: list[tuple[str, RequirementCheck]],
        repo_dir: str | Path,
    ) -> RequirementSummary:
        summary = RequirementSummary()
        repo_dir = str(repo_dir)
        for name, check in checks:
            try:
                outcome = check(repo_dir)
            except Exception as exc:  # the trusted check itself did not return a result
                summary.results.append(
                    RequirementResult(name=name, passed=False, message=f"check raised: {exc}",
                                      valid=False)
                )
                continue

            if hasattr(outcome, "valid") and hasattr(outcome, "passed"):
                passed, message = outcome.passed, outcome.message
                valid, metadata = outcome.valid, getattr(outcome, "metadata", {})
            elif isinstance(outcome, tuple):
                passed, message = outcome[0], outcome[1] if len(outcome) > 1 else ""
                valid, metadata = True, {"protocol": "trusted_callable"}
            else:
                passed, message = bool(outcome), ""
                valid, metadata = True, {"protocol": "trusted_callable"}
            summary.results.append(
                RequirementResult(name=name, passed=bool(passed) and bool(valid),
                                  message=str(message), valid=bool(valid), metadata=metadata)
            )
        return summary
