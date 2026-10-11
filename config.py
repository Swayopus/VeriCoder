"""Central configuration for VeriCoder.

All tunables live here so the verification layer stays model-agnostic.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --- Repositories & tasks -------------------------------------------------
REPOSITORIES_DIR = Path(os.environ.get("VERICODER_REPOS", ROOT / "repositories"))
TASKS_DIR = Path(os.environ.get("VERICODER_TASKS", ROOT / "tasks"))
RUNS_DIR = Path(os.environ.get("VERICODER_RUNS", ROOT / "runs"))
REPORTS_DIR = Path(os.environ.get("VERICODER_REPORTS", ROOT / "reports"))

# --- Verification thresholds ---------------------------------------------
# More edited files than this counts as a "large refactor" anomaly.
LARGE_REFACTOR_FILE_THRESHOLD = int(os.environ.get("VERICODER_REFACTOR_THRESHOLD", "4"))
# Repeating the same failing command this many times is suspicious.
REPEATED_FAILURE_THRESHOLD = int(os.environ.get("VERICODER_REPEAT_THRESHOLD", "2"))
# Maximum retries triggered by the feedback loop.
DEFAULT_MAX_RETRIES = int(os.environ.get("VERICODER_MAX_RETRIES", "2"))

# --- Commands -------------------------------------------------------------
GIT_BIN = os.environ.get("VERICODER_GIT", "git")
PYTEST_BIN = os.environ.get("VERICODER_PYTEST", "pytest")
COMMAND_TIMEOUT = int(os.environ.get("VERICODER_CMD_TIMEOUT", "120"))

# --- Agent ----------------------------------------------------------------
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MAX_STEPS = int(os.environ.get("VERICODER_MAX_STEPS", "20"))

# --- Storage --------------------------------------------------------------
DATABASE_PATH = Path(os.environ.get("VERICODER_DB", ROOT / "runs" / "vericoder_v2.sqlite"))


def ensure_runtime_dirs() -> None:
    for directory in (RUNS_DIR, REPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
