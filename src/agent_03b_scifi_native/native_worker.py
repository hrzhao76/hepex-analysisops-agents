from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

StatusCallback = Callable[[str], Any]


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _tool_call_id(tool_call: Any) -> str:
    return str(getattr(tool_call, "id", "tool_call"))


def _tool_call_name(tool_call: Any) -> str:
    function = getattr(tool_call, "function", None)
    return str(getattr(function, "name", ""))


def _tool_call_arguments(tool_call: Any) -> dict[str, Any]:
    function = getattr(tool_call, "function", None)
    raw = getattr(function, "arguments", "{}")
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_invalid_json_arguments": raw}
    return parsed if isinstance(parsed, dict) else {}


def _assistant_message_dict(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": "assistant",
        "content": _message_content(message),
    }
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": _tool_call_id(call),
                "type": "function",
                "function": {
                    "name": _tool_call_name(call),
                    "arguments": getattr(getattr(call, "function", None), "arguments", "{}"),
                },
            }
            for call in tool_calls
        ]
    return payload


class NativeSciFiWorker:
    """Small SciFi-style native tool loop for submission-bundle tasks.

    This is deliberately a compact AgentBeats adapter, not a full copy of the
    upstream SciFi runtime. The worker owns model calls and deterministic tools;
    the outer SciFiLoop still owns independent review and retry.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        req_json: dict[str, Any] | None,
        input_manifest: dict[str, Any] | None,
        work_dir: Path | None,
        status: StatusCallback,
        debug_log_path: Path | None = None,
        enable_scifi_v2_tools: bool = False,
        shared_env_root: str | Path | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.req_json = req_json or {}
        self.input_manifest = input_manifest or {}
        self.work_dir = (work_dir or Path.cwd()).resolve()
        self.status = status
        self.max_iterations = int(os.environ.get("SCIFI_NATIVE_MAX_ITERATIONS", "30"))
        self.max_bash_seconds = int(os.environ.get("SCIFI_NATIVE_MAX_BASH_SECONDS", "300"))
        self.max_tool_chars = int(os.environ.get("SCIFI_NATIVE_MAX_TOOL_CHARS", "12000"))
        self.tool_log_chars = int(os.environ.get("SCIFI_NATIVE_TOOL_LOG_CHARS", "4000"))
        self.model = (
            os.environ.get("SCIFI_NATIVE_MODEL")
            or os.environ.get("HEPEX_AGENT_MODEL")
            or os.environ.get("HEPEX_OPENAI_MODEL")
            or "gpt-5"
        )
        self.debug_log_path = debug_log_path
        self.enable_scifi_v2_tools = enable_scifi_v2_tools
        shared_root = (
            shared_env_root
            or os.environ.get("SCIFI_NATIVE_SHARED_ENV_ROOT")
            or "/mnt/sci_envs"
        )
        self.shared_env_root = Path(shared_root).expanduser()
        self.active_env_path: Path | None = None
        self.active_env_aliases: dict[str, str] = {}
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _debug_log(self, blocks: list[tuple[str, str]]) -> None:
        if self.debug_log_path is None:
            return
        with self.debug_log_path.open("a", encoding="utf-8") as f:
            for title, content in blocks:
                f.write(f"{title}:\n{content}\n")
            f.write("=" * 40 + "\n")

    def _client(self) -> OpenAI:
        base_url = os.environ.get("SCIFI_NATIVE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        kwargs: dict[str, Any] = {}
        if base_url:
            kwargs["base_url"] = base_url
        api_key = os.environ.get("SCIFI_NATIVE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key
        return OpenAI(**kwargs)

    def _allowed_read_roots(self) -> list[Path]:
        roots = [self.work_dir]
        if self.enable_scifi_v2_tools:
            roots.append(self.shared_env_root)
        if self.active_env_path is not None:
            roots.append(self.active_env_path)
        data_info = self.req_json.get("data", {})
        for candidate in [
            self.input_manifest.get("shared_input_dir"),
            self.input_manifest.get("input_manifest_path"),
            data_info.get("shared_input_dir") if isinstance(data_info, dict) else None,
            data_info.get("input_manifest_path") if isinstance(data_info, dict) else None,
        ]:
            if isinstance(candidate, str) and candidate.strip():
                path = Path(candidate).expanduser()
                roots.append(path if path.is_dir() else path.parent)
        return [root.resolve() for root in roots if root.exists()]

    def _resolve_env_path(self, raw_path: str) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("env_path must be a non-empty string")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            work_candidate = (self.work_dir / path).resolve()
            shared_candidate = (self.shared_env_root / path).resolve()
            path = work_candidate if work_candidate.exists() else shared_candidate
        resolved = path.resolve()
        allowed_roots = [self.shared_env_root.resolve(), self.work_dir]
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        root_text = ", ".join(str(root) for root in allowed_roots)
        raise PermissionError(f"env_path is outside allowed roots: {resolved}; allowed roots: {root_text}")

    @staticmethod
    def _read_env_manifest_payload(env_path: Path) -> dict[str, Any]:
        manifest_path = env_path / ".manifest.json"
        if manifest_path.is_file():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {"manifest_error": f"{type(exc).__name__}: {exc}"}
        purpose_path = env_path.parent.parent / "PURPOSE.md"
        if purpose_path.is_file():
            return {"purpose": purpose_path.read_text(encoding="utf-8", errors="replace")[:4000]}
        return {}

    def _resolve_path(self, raw_path: str, *, write: bool) -> Path:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path must be a non-empty string")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.work_dir / path
        resolved = path.resolve()
        roots = [self.work_dir] if write else self._allowed_read_roots()
        for root in roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        root_text = ", ".join(str(root) for root in roots)
        raise PermissionError(f"path is outside allowed roots: {resolved}; allowed roots: {root_text}")

    async def _tool_bash(self, args: dict[str, Any]) -> dict[str, Any]:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command is required")
        timeout = args.get("timeout_seconds", self.max_bash_seconds)
        try:
            timeout_seconds = int(timeout)
        except Exception:
            timeout_seconds = self.max_bash_seconds
        timeout_seconds = max(1, min(timeout_seconds, self.max_bash_seconds))
        env = os.environ.copy()
        env["HEPEX_SOLVER_WORK_DIR"] = str(self.work_dir)
        env["HEPEX_OUTPUT_DIR"] = str(self.work_dir)
        path_prefixes = []
        active_env = self.active_env_path
        if active_env is not None:
            env.pop("VIRTUAL_ENV", None)
            env["CONDA_PREFIX"] = str(active_env)
            env["MAMBA_ROOT_PREFIX"] = str(active_env.parent.parent)
            active_bin = active_env / "bin"
            if active_bin.exists():
                path_prefixes.append(str(active_bin))
                active_python = active_bin / "python"
                if active_python.exists():
                    env["SCIFI_NATIVE_PYTHON"] = str(active_python)
            active_lib = active_env / "lib"
            if active_lib.exists():
                env["LD_LIBRARY_PATH"] = os.pathsep.join(
                    [str(active_lib), env.get("LD_LIBRARY_PATH", "")]
                )
            for key, value in self.active_env_aliases.items():
                alias_path = Path(value)
                env[key] = str(active_env / alias_path) if not alias_path.is_absolute() else str(alias_path)
        app_venv = Path("/home/agent/.venv")
        if (app_venv / "bin" / "python").exists():
            path_prefixes.append(str(app_venv / "bin"))
            if active_env is None:
                env["VIRTUAL_ENV"] = str(app_venv)
            env.setdefault("SCIFI_NATIVE_PYTHON", str(app_venv / "bin" / "python"))
        else:
            env.setdefault("SCIFI_NATIVE_PYTHON", sys.executable)
        path_prefixes.append(str(Path(sys.executable).resolve().parent))
        env["PATH"] = os.pathsep.join(path_prefixes + [env.get("PATH", "")])
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.work_dir),
            env=env,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
        return {
            "active_env": str(active_env) if active_env is not None else None,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }

    async def _tool_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", "")), write=False)
        offset = max(0, int(args.get("offset", 0) or 0))
        limit = max(1, min(int(args.get("limit", self.max_tool_chars) or self.max_tool_chars), self.max_tool_chars))
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"path": str(path), "content": text[offset : offset + limit], "size_chars": len(text)}

    async def _tool_write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", "")), write=True)
        content = args.get("content", "")
        if not isinstance(content, str):
            content = _json_dump(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path), "bytes_written": len(content.encode("utf-8"))}

    async def _tool_list_dir(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", ".")), write=False)
        if not path.is_dir():
            raise NotADirectoryError(str(path))
        entries = []
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "type": "dir" if child.is_dir() else "file",
                    "size_bytes": child.stat().st_size if child.is_file() else None,
                }
            )
        return {"path": str(path), "entries": entries[:200], "truncated": len(entries) > 200}

    async def _tool_list_shared_envs(self, args: dict[str, Any]) -> dict[str, Any]:
        del args
        root = self.shared_env_root.resolve()
        envs: list[dict[str, Any]] = []
        if root.is_dir():
            for prefix in sorted(root.iterdir(), key=lambda item: item.name):
                envs_dir = prefix / "envs"
                if not envs_dir.is_dir():
                    continue
                for env_path in sorted(envs_dir.iterdir(), key=lambda item: item.name):
                    if not env_path.is_dir():
                        continue
                    manifest = self._read_env_manifest_payload(env_path)
                    envs.append(
                        {
                            "prefix": prefix.name,
                            "env": env_path.name,
                            "path": str(env_path),
                            "purpose": manifest.get("purpose", ""),
                            "binaries": manifest.get("binaries", {}),
                            "aliases": manifest.get("aliases", {}),
                        }
                    )
        writable_parent = root if root.exists() else root.parent
        return {
            "root": str(root),
            "exists": root.exists(),
            "writable": os.access(writable_parent, os.W_OK) if writable_parent.exists() else False,
            "envs": envs,
        }

    async def _tool_read_env_manifest(self, args: dict[str, Any]) -> dict[str, Any]:
        env_path = self._resolve_env_path(str(args.get("env_path", "")))
        if not env_path.is_dir():
            raise NotADirectoryError(str(env_path))
        return {
            "env_path": str(env_path),
            "manifest": self._read_env_manifest_payload(env_path),
        }

    async def _tool_activate_env(self, args: dict[str, Any]) -> dict[str, Any]:
        env_path = self._resolve_env_path(str(args.get("env_path", "")))
        if not env_path.is_dir():
            raise NotADirectoryError(str(env_path))
        manifest = self._read_env_manifest_payload(env_path)
        aliases = manifest.get("aliases", {})
        self.active_env_path = env_path
        self.active_env_aliases = {
            str(key): str(value)
            for key, value in aliases.items()
            if isinstance(key, str) and isinstance(value, str)
        } if isinstance(aliases, dict) else {}
        return {
            "active_env": str(env_path),
            "bin_exists": (env_path / "bin").is_dir(),
            "aliases": self.active_env_aliases,
            "purpose": manifest.get("purpose", ""),
        }

    async def _tool_compact(self, args: dict[str, Any]) -> dict[str, Any]:
        text = args.get("text", "")
        if not isinstance(text, str):
            text = _json_dump(text)
        try:
            max_chars = int(args.get("max_chars", 4000) or 4000)
        except Exception:
            max_chars = 4000
        max_chars = max(400, min(max_chars, self.max_tool_chars))
        if len(text) <= max_chars:
            compacted = text
        else:
            head = max_chars // 2
            tail = max_chars - head
            compacted = (
                text[:head]
                + f"\n...[compact omitted {len(text) - max_chars} chars]...\n"
                + text[-tail:]
            )
        return {
            "original_chars": len(text),
            "max_chars": max_chars,
            "content": compacted,
        }

    def _required_artifact_names(self) -> list[str]:
        contract = self.req_json.get("submission_contract", {})
        if not isinstance(contract, dict):
            return []
        outputs = contract.get("required_outputs", [])
        if not isinstance(outputs, list):
            return []
        names = []
        for item in outputs:
            if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str):
                names.append(item["canonical_filename"])
        return names

    def _artifact_type_map(self) -> dict[str, str]:
        contract = self.req_json.get("submission_contract", {})
        if not isinstance(contract, dict):
            return {}
        mapping: dict[str, str] = {}
        for section in ("required_outputs", "optional_outputs"):
            outputs = contract.get(section, [])
            if not isinstance(outputs, list):
                continue
            for item in outputs:
                if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str):
                    mapping[item["canonical_filename"]] = str(item.get("type", "json"))
        return mapping

    def _recover_bundle_from_outputs(self) -> dict[str, Any] | None:
        required_names = self._required_artifact_names()
        if not required_names:
            return None
        type_map = self._artifact_type_map()
        search_dirs = [self.work_dir / "outputs", self.work_dir / "artifacts", self.work_dir]
        artifacts: dict[str, Any] = {}
        for name in required_names:
            artifact_path = next((base / name for base in search_dirs if (base / name).is_file()), None)
            if artifact_path is None:
                return None
            try:
                if type_map.get(name) in {"markdown", "text"} or artifact_path.suffix.lower() == ".md":
                    artifacts[name] = artifact_path.read_text(encoding="utf-8")
                else:
                    artifacts[name] = json.loads(artifact_path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return {"status": "ok", "artifacts": artifacts}

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if "_invalid_json_arguments" in args:
            raise ValueError(f"invalid JSON tool arguments: {args['_invalid_json_arguments']}")
        if name == "bash":
            return await self._tool_bash(args)
        if name == "read_file":
            return await self._tool_read_file(args)
        if name == "write_file":
            return await self._tool_write_file(args)
        if name == "list_dir":
            return await self._tool_list_dir(args)
        if self.enable_scifi_v2_tools and name == "list_shared_envs":
            return await self._tool_list_shared_envs(args)
        if self.enable_scifi_v2_tools and name == "read_env_manifest":
            return await self._tool_read_env_manifest(args)
        if self.enable_scifi_v2_tools and name == "activate_env":
            return await self._tool_activate_env(args)
        if self.enable_scifi_v2_tools and name == "compact":
            return await self._tool_compact(args)
        raise ValueError(f"unknown tool: {name}")

    def _tools(self) -> list[dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "Run a bash command in the solver work directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "timeout_seconds": {"type": "integer"},
                        },
                        "required": ["command"],
                    },
                },
            },
        ]
        if self.enable_scifi_v2_tools:
            tools.extend(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "list_shared_envs",
                            "description": "List reusable shared micromamba/conda environments under the configured SciFi shared env root.",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "read_env_manifest",
                            "description": "Read the manifest for a candidate shared environment.",
                            "parameters": {
                                "type": "object",
                                "properties": {"env_path": {"type": "string"}},
                                "required": ["env_path"],
                            },
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "activate_env",
                            "description": "Activate a shared or local env for all subsequent bash calls.",
                            "parameters": {
                                "type": "object",
                                "properties": {"env_path": {"type": "string"}},
                                "required": ["env_path"],
                            },
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "compact",
                            "description": "Compact long text deterministically by keeping the head and tail.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "max_chars": {"type": "integer"},
                                },
                                "required": ["text"],
                            },
                        },
                    },
                ]
            )
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a UTF-8 text file from the work directory or declared input directory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "offset": {"type": "integer"},
                                "limit": {"type": "integer"},
                            },
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Write a UTF-8 text file under the solver work directory.",
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
                        "name": "list_dir",
                        "description": "List a directory under the work directory or declared input directory.",
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
                        "name": "done",
                        "description": "Return the final submission_bundle_v1 JSON string.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "final_json": {
                                    "type": "string",
                                    "description": "The complete final submission_bundle_v1 JSON object as a string.",
                                }
                            },
                            "required": ["final_json"],
                        },
                    },
                },
            ]
        )
        return tools

    async def run(self, sam_prompt: str) -> str:
        client = self._client()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": sam_prompt},
        ]

        last_content = ""
        for iteration in range(1, self.max_iterations + 1):
            status_result = self.status(
                f"SciFi native worker: model iteration {iteration}/{self.max_iterations}."
            )
            if inspect.isawaitable(status_result):
                await status_result
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self._tools(),
                tool_choice="auto",
            )
            choice = response.choices[0]
            message = choice.message
            last_content = _message_content(message).strip()
            tool_calls = getattr(message, "tool_calls", None) or []
            messages.append(_assistant_message_dict(message))

            if not tool_calls:
                if last_content.startswith("{") and last_content.endswith("}"):
                    return last_content
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue using tools. When the task is complete, call the done tool "
                            "with exactly one submission_bundle_v1 JSON object."
                        ),
                    }
                )
                continue

            for call in tool_calls:
                name = _tool_call_name(call)
                args = _tool_call_arguments(call)
                call_id = _tool_call_id(call)
                if name == "done":
                    final_json = args.get("final_json")
                    if isinstance(final_json, str) and final_json.strip():
                        self._debug_log(
                            [
                                ("--- Native Tool Call ---", "done"),
                                ("ARGS", _truncate(_json_dump(args), self.tool_log_chars)),
                            ]
                        )
                        return final_json.strip()
                    return _json_dump({"status": "error", "error": "done tool missing final_json"})

                try:
                    result = await self._execute_tool(name, args)
                    content = _truncate(_json_dump({"ok": True, "result": result}), self.max_tool_chars)
                except Exception as exc:
                    content = _truncate(
                        _json_dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}),
                        self.max_tool_chars,
                    )
                self._debug_log(
                    [
                        ("--- Native Tool Call ---", name),
                        ("ARGS", _truncate(_json_dump(args), self.tool_log_chars)),
                        ("RESULT", _truncate(content, self.tool_log_chars)),
                    ]
                )
                messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
                recovered_bundle = self._recover_bundle_from_outputs()
                if recovered_bundle is not None:
                    try:
                        from agent_02_scifi_oh.review import review_submission_bundle

                        recovered_text = _json_dump(recovered_bundle)
                        review = review_submission_bundle(
                            self.req_json,
                            recovered_text,
                            self.input_manifest,
                            self.work_dir,
                        )
                        if review.passed:
                            final_payload = review.bundle or recovered_bundle
                            self._debug_log(
                                [
                                    ("--- Native Auto-Recovered Bundle ---", "PASS"),
                                    ("ARTIFACTS", ", ".join(sorted(final_payload["artifacts"]))),
                                ]
                            )
                            return _json_dump(final_payload)
                    except Exception as exc:
                        self._debug_log(
                            [
                                ("--- Native Auto-Recovered Bundle ---", "ERROR"),
                                ("ERROR", f"{type(exc).__name__}: {exc}"),
                            ]
                        )

        return _json_dump(
            {
                "status": "error",
                "error": "SciFi native worker exhausted its iteration budget before returning a bundle.",
                "last_message": last_content,
            }
        )
