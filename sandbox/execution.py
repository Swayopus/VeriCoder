"""One execution backend for tools and verification.

``local`` executes candidate code on the host and is not a security sandbox.
``docker`` requires the prebuilt runtime image; failure never falls back to local.
Completion receipts detect incomplete runs, not arbitrary malicious Python code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Mapping, Sequence

TRUSTED_HELPERS = Path(__file__).resolve().parents[1] / "verifier" / "trusted"
DEFAULT_IMAGE = "vericoder-runtime:local"
IO_DIRECTORY_ENV = "VERICODER_TRUSTED_IO_DIR"
LOCAL_ENV_ALLOWLIST = {
    'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE',
    'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH',
    'APPDATA', 'LOCALAPPDATA', 'LANG', 'LANGUAGE', 'TZ', 'NUMBER_OF_PROCESSORS',
}


class ExecutionBackendError(RuntimeError):
    """The requested execution environment could not run the command."""


def _mapped_path(value: str, mounts: list[tuple[Path, str]]) -> str:
    if value == sys.executable:
        return "python"
    candidate = Path(value)
    if not candidate.is_absolute():
        return value
    for source, destination in mounts:
        try:
            suffix = candidate.resolve().relative_to(source)
        except (ValueError, OSError):
            continue
        return destination + ("/" + suffix.as_posix() if suffix.parts else "")
    return value


def run_command(
    argv: Sequence[str],
    cwd: str | Path,
    timeout: int | float,
    env: Mapping[str, str] | None = None,
    read_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run an argv vector without a shell; ``env`` overrides child variables.

    Docker receives explicit overrides only, not host credentials or the project
    source tree. Trusted verification helpers and temporary receipt IO are the
    only mounts in addition to the candidate workspace.
    """
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("run_command requires a nonempty argv sequence")
    command = [str(arg) for arg in argv]
    workspace = Path(cwd).resolve()
    overrides = dict(env or {})
    io_directory = overrides.pop(IO_DIRECTORY_ENV, None)
    backend = os.environ.get("VERICODER_EXECUTION_BACKEND", "local").lower()
    if backend == "local":
        # Generated code does not need provider/API credentials from the parent.
        # This is environment hygiene, not protection against host filesystem access.
        child_env = {key: value for key, value in os.environ.items()
                     if key.upper() in LOCAL_ENV_ALLOWLIST or key.upper().startswith('LC_')}
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        child_env.update(overrides)
        return subprocess.run(
            command, cwd=str(workspace), timeout=timeout,
            env=child_env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            shell=False,
        )
    if backend != "docker":
        raise ExecutionBackendError(f"Unknown execution backend: {backend!r}")
    return run_docker_command(command, workspace, timeout, env=env, read_only=read_only)


def run_docker_command(
    argv: Sequence[str], cwd: str | Path, timeout: int | float,
    env: Mapping[str, str] | None = None, read_only: bool = False,
    image: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Explicit Docker entry point also used by the legacy facade."""
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("run_docker_command requires a nonempty argv sequence")
    command = [str(arg) for arg in argv]
    workspace = Path(cwd).resolve()
    overrides = dict(env or {})
    io_directory = overrides.pop(IO_DIRECTORY_ENV, None)
    docker = shutil.which("docker")
    if not docker:
        raise ExecutionBackendError("Docker backend selected, but docker is unavailable")

    name = "vericoder-" + uuid.uuid4().hex
    mounts = [(workspace, "/workspace"), (TRUSTED_HELPERS.resolve(), "/vericoder_trusted")]
    docker_args = [
        docker, "run", "--rm", "--pull", "never", "--name", name,
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128",
        "--memory", "1g", "--cpus", "1", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
        "-v", f"{workspace}:/workspace" + (":ro" if read_only else ":rw"),
        "-v", f"{TRUSTED_HELPERS.resolve()}:/vericoder_trusted:ro", "-w", "/workspace",
    ]
    if io_directory:
        io_path = Path(io_directory).resolve()
        if not io_path.is_dir():
            raise ExecutionBackendError("Trusted receipt IO directory does not exist")
        mounts.append((io_path, "/vericoder_io"))
        docker_args += ["-v", f"{io_path}:/vericoder_io:rw"]
    for key, value in overrides.items():
        if "=" in key or "\x00" in key or "\x00" in str(value):
            raise ValueError("Invalid environment variable")
        docker_args += ["-e", f"{key}={_mapped_path(str(value), mounts)}"]
    image = image or os.environ.get("VERICODER_DOCKER_IMAGE", DEFAULT_IMAGE)
    docker_args += ["--entrypoint", "", image]
    docker_args += [_mapped_path(arg, mounts) for arg in command]
    try:
        proc = subprocess.run(
            docker_args, timeout=timeout, capture_output=True, text=True,
            encoding="utf-8", errors="replace", shell=False,
        )
    except subprocess.TimeoutExpired:
        # Killing only the docker client leaves its container running.
        try:
            subprocess.run(
                [docker, "rm", "-f", name], timeout=15,
                capture_output=True, text=True, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    if proc.returncode in {125, 126, 127}:
        raise ExecutionBackendError(
            f"Docker execution unavailable ({proc.returncode}): {proc.stderr[-1000:]}"
        )
    return subprocess.CompletedProcess(command, proc.returncode, proc.stdout, proc.stderr)
