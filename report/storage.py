"""SQLite persistence for experiment runs (design doc section 5.6)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import config
from core.models import utcnow
from feedback.loop import LoopResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment TEXT NOT NULL,
    task_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    agent TEXT,
    success INTEGER NOT NULL,
    first_attempt_success INTEGER NOT NULL,
    retries INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    out_of_scope INTEGER NOT NULL,
    test_modified INTEGER NOT NULL,
    trace_anomalies INTEGER NOT NULL,
    failed_requirements INTEGER NOT NULL,
    manual_intervention INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class ResultStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or config.DATABASE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
            for name, definition in {
                "run_id": "TEXT NOT NULL DEFAULT 'legacy'",
                "condition": "TEXT NOT NULL DEFAULT ''",
                "repeat_index": "INTEGER NOT NULL DEFAULT 0",
                "verdict": "TEXT NOT NULL DEFAULT 'LEGACY'",
                "retry_tokens": "INTEGER NOT NULL DEFAULT 0",
                "duration_ms": "INTEGER NOT NULL DEFAULT 0",
                "human_intervention_count": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")

    def save(self, experiment: str, result: LoopResult, repository: str = "", agent: str = "") -> None:
        report = result.final_report
        diff = (report.diff_result if report else {}) or {}
        trace = (report.trace_result if report else {}) or {}
        requirements = (report.requirement_result if report else {}) or {}
        if report and report.agent:
            agent = report.agent

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    experiment, task_id, repository, agent, success,
                    first_attempt_success, retries, total_tokens,
                    out_of_scope, test_modified, trace_anomalies,
                    failed_requirements, manual_intervention, created_at, payload,
                    run_id, condition, repeat_index, verdict, retry_tokens,
                    duration_ms, human_intervention_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    experiment,
                    result.task_id,
                    repository,
                    agent,
                    1 if result.success else 0,
                    1 if result.first_attempt_success else 0,
                    result.retries,
                    result.total_tokens,
                    1 if diff.get("out_of_scope_files") else 0,
                    1 if diff.get("test_files_modified") else 0,
                    len(trace.get("anomalies", [])),
                    requirements.get("failed_count", 0),
                    1 if result.manual_intervention else 0,
                    utcnow(),
                    json.dumps(result.to_dict(), ensure_ascii=False),
                    result.run_id or "unbatched",
                    result.condition or experiment,
                    result.repeat_index,
                    report.verdict if report else "INVALID",
                    sum(a.tokens for a in result.attempts[1:]),
                    sum(a.duration_ms for a in result.attempts),
                    len(result.human_interventions),
                ),
            )

    def rows(self, experiment: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs"
        params: list[Any] = []
        filters = []
        if experiment:
            filters.append("experiment = ?")
            params.append(experiment)
        if run_id:
            filters.append("run_id = ?")
            params.append(run_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY id ASC"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, params)]

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM runs")
