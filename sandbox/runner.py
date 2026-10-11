"""Compatibility facade for explicit Docker execution; never falls back."""

from __future__ import annotations

import shutil
import shlex
from dataclasses import dataclass
from pathlib import Path

import config
from sandbox.execution import run_docker_command


@dataclass
class SandboxResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class DockerSandbox:
    def __init__(self, image: str = "vericoder-runtime:local", timeout: int | None = None) -> None:
        self.image = image
        self.timeout = timeout or config.COMMAND_TIMEOUT

    def available(self) -> bool:
        return shutil.which("docker") is not None

    def run(self, workspace: str | Path, command: str) -> SandboxResult:
        if not self.available():
            raise RuntimeError("Docker is not installed or not on PATH")
        proc = run_docker_command(shlex.split(command), workspace, self.timeout, image=self.image)
        return SandboxResult(
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
