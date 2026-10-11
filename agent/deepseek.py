"""DeepSeek Coding Agent.

Architecture::

    DeepSeek API  +  Tool Executor  +  Trace Middleware  =  DeepSeekAgent

The model never touches the shell.  It emits ``tool_calls`` which are
executed by :class:`ToolExecutor`, so the recorded trace reflects what really
happened rather than what the model claims.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import config
from agent.base import CodingAgent, build_patch
from core.models import AgentResult, Patch, Task
from tools.executor import ToolExecutor
from trace.recorder import TraceRecorder

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file relative to the repository root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a unique substring in a file with new text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List entries of a directory relative to the repository root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the fixed pytest action specified by this task. No shell commands are accepted.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM_PROMPT = """You are a coding agent working inside a repository.
Use the provided file tools to inspect and modify files, and run_tests to execute
the fixed test suite. Git metadata and arbitrary shell commands are unavailable.
Keep changes minimal and scoped to the task. Do not modify test files unless the
task explicitly requires it. When you believe the task is complete, stop calling
tools and reply with a short summary."""


class DeepSeekAgent(CodingAgent):
    name = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_steps: int | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        max_api_retries: int = 1,
    ) -> None:
        self.api_key = api_key or config.DEEPSEEK_API_KEY
        self.model = model or config.DEEPSEEK_MODEL
        self.base_url = (base_url or config.DEEPSEEK_BASE_URL).rstrip("/")
        self.max_steps = config.DEEPSEEK_MAX_STEPS if max_steps is None else max_steps
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        self.max_tokens = max_tokens
        if isinstance(max_api_retries, bool) or not isinstance(max_api_retries, int) or max_api_retries < 0:
            raise ValueError("max_api_retries must be a non-negative integer")
        self.max_api_retries = max_api_retries
        self.temperature = temperature

    def _redact(self, value: Any) -> Any:
        """Keep accidental provider echoes of the credential out of evidence."""
        if isinstance(value, str):
            return value.replace(self.api_key, "[REDACTED]") if self.api_key else value
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    # -- HTTP --------------------------------------------------------------
    def _chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        import requests

        if not self.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Use ScriptedAgent for offline runs."
            )
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "tools": TOOL_SPECS,
                "tool_choice": "auto",
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    def _chat_with_retries(self, messages: list[dict[str, Any]], metadata: dict[str, Any],
                           step: int) -> dict[str, Any]:
        import requests

        for retry_index in range(self.max_api_retries + 1):
            metadata["request_count"] += 1
            request_number = metadata["request_count"]
            try:
                payload = self._chat(messages)
            except Exception as exc:
                transport_error = isinstance(exc, (requests.ConnectionError, requests.Timeout))
                will_retry = transport_error and retry_index < self.max_api_retries
                metadata["request_failures"].append({
                    "request_number": request_number, "step": step,
                    "attempt": retry_index + 1, "type": type(exc).__name__,
                    "message": self._redact(str(exc)), "retry": will_retry,
                })
                # A lost response may already have been generated and billed.
                # Only returned provider usage contributes to the token total.
                metadata["usage_complete"] = False
                if not will_retry:
                    raise
                metadata["transport_retry_count"] += 1
                time.sleep(0.25)
            else:
                metadata["successful_requests"].append({"request_number": request_number, "step": step})
                return payload
        raise RuntimeError("API retry budget exhausted")  # Defensive, normally unreachable.

    # -- agent loop --------------------------------------------------------
    def run(
        self,
        task: Task,
        repo_dir: str,
        feedback: Optional[dict[str, Any]] = None,
    ) -> AgentResult:
        recorder = TraceRecorder(task_id=task.task_id, agent=self.name)
        tools = ToolExecutor(repo_dir, recorder, test_command=task.test_command)

        user_prompt = self._build_prompt(task, feedback)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        total_tokens = 0
        metadata: dict[str, Any] = {
            "requested_model": self.model, "models_seen": [], "temperature": self.temperature,
            "max_steps": self.max_steps, "max_tokens": self.max_tokens,
            "max_api_retries": self.max_api_retries,
            "request_count": 0, "transport_retry_count": 0,
            "request_failures": [], "successful_requests": [],
            "usage_complete": True, "usage_accounting": "provider_reported_only",
            "responses": [], "messages": messages,
            "stop_reason": "max_steps", "execution_scope": "structured_files_and_task_tests",
        }
        error = ""

        try:
            for step_index in range(self.max_steps):
                payload = self._chat_with_retries(messages, metadata, step_index + 1)
                metadata["responses"].append(payload)
                actual_model = payload.get("model")
                if actual_model and actual_model not in metadata["models_seen"]:
                    metadata["models_seen"].append(actual_model)
                usage = payload.get("usage") or {}
                reported_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
                if isinstance(reported_tokens, int) and not isinstance(reported_tokens, bool) and reported_tokens >= 0:
                    total_tokens += reported_tokens
                else:
                    metadata["usage_complete"] = False
                message = payload["choices"][0]["message"]
                messages.append(message)

                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    metadata["stop_reason"] = "model_finished"
                    metadata["finish_reason"] = payload["choices"][0].get("finish_reason")
                    if metadata["finish_reason"] == "length":
                        error = "Model response was truncated before completion"
                        metadata["stop_reason"] = "response_truncated"
                    break
                for call in tool_calls:
                    output = self._execute_tool(tools, call)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": output,
                        }
                    )
        except Exception as exc:  # network / API error
            error = self._redact(str(exc))
            metadata["stop_reason"] = "api_or_protocol_error"

        if metadata["stop_reason"] == "max_steps":
            error = f"Agent reached the {self.max_steps}-step limit without completing"
        metadata["error"] = error
        try:
            patch = build_patch(repo_dir, source=self.name)
        except Exception as exc:
            patch = Patch(source=self.name)
            safe_error = self._redact(str(exc))
            error = "; ".join(part for part in (error, f"patch capture failed: {safe_error}") if part)
            metadata["patch_error"] = safe_error

        metadata["error"] = error

        recorder.add_tokens(total_tokens)
        trace = recorder.finalize()
        return AgentResult(
            patch=patch,
            trace=trace,
            tokens=total_tokens,
            error=error,
            metadata=self._redact(metadata),
        )

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _build_prompt(task: Task, feedback: Optional[dict[str, Any]]) -> str:
        parts = [
            f"Task {task.task_id} ({task.repository}): {task.description}",
            f"Allowed files: {', '.join(task.allowed_files) or 'unspecified'}",
        ]
        if task.requirements:
            parts.append("Requirements: " + "; ".join(task.requirements))
        if feedback:
            parts.append(
                "Previous verification failed. Feedback:\n"
                + json.dumps(feedback, ensure_ascii=False, indent=2)
            )
        return "\n\n".join(parts)

    def _execute_tool(self, tools: ToolExecutor, call: dict[str, Any]) -> str:
        name = call["function"]["name"]
        raw_args = call["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            tools.trace.record("tool_call", target=name, status="fail", detail="invalid JSON arguments",
                               data={"category": "tool", "completed": False, "raw_arguments": raw_args})
            return f"ERROR: invalid JSON arguments: {raw_args}"

        try:
            if name == "read_file":
                return tools.read_file(args["path"])
            if name == "write_file":
                tools.write_file(args["path"], args["content"])
                return "ok"
            if name == "edit_file":
                tools.str_replace(args["path"], args["old_string"], args["new_string"])
                return "ok"
            if name == "list_dir":
                return "\n".join(tools.list_dir(args.get("path", ".")))
            if name == "run_tests":
                result = tools.run_tests()
                return json.dumps({"returncode": result.returncode, "ok": result.ok,
                                   "output": result.tail()}, ensure_ascii=False)
            if name == "run_command":  # compatibility with an old model response
                result = tools.run_command(args["command"])
                return json.dumps({"returncode": result.returncode, "ok": result.ok,
                                   "output": result.tail()}, ensure_ascii=False)
            tools.trace.record("tool_call", target=name, status="denied", detail="unknown tool",
                               data={"category": "tool", "completed": False})
            return f"ERROR: unknown tool {name}"
        except Exception as exc:
            tools.trace.record("tool_call_error", target=name, status="fail", detail=str(exc),
                               data={"category": "tool", "completed": False})
            return f"ERROR: {exc}"
