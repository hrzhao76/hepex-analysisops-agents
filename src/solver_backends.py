from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from agent_02_scifi_oh.loop import SciFiLoop
from agent_03a_scifi_native.loop import NativeSciFiLoop as NativeSciFiLoop03A
from agent_03a_scifi_native.native_worker import NativeSciFiWorker as NativeSciFiWorker03A
from agent_03b_scifi_native.loop import NativeSciFiLoop as NativeSciFiLoop03B
from agent_03b_scifi_native.native_worker import NativeSciFiWorker as NativeSciFiWorker03B
from agent_03b_scifi_native.prompt_builder import build_general_sam_prompt
from agent_03c_scifi_native.loop import NativeSciFiLoop as NativeSciFiLoop03C
from agent_03c_scifi_native.native_worker import NativeSciFiWorker as NativeSciFiWorker03C
from agent_03c_scifi_native.prompt_builder import build_v2_sam_prompt
from bundle_runtime import extract_required_output_names, request_mode


logger = logging.getLogger(__name__)

DEFAULT_SOLVER_BACKEND = "agent_1_oh"

StatusCallback = Callable[[str], Awaitable[None]]


class SolverBackend(Protocol):
    name: str

    async def run(
        self,
        prompt: str,
        req_json: dict[str, Any] | None,
        *,
        system_prompt: str,
        status: StatusCallback,
        input_manifest: dict[str, Any] | None = None,
        work_dir: Path | None = None,
    ) -> str:
        ...


async def noop_status(_: str) -> None:
    return None


def json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if abs(size) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TiB"


def short_list(values: list[str], *, limit: int = 6) -> str:
    if not values:
        return "none"
    head = values[:limit]
    suffix = "" if len(values) <= limit else f", +{len(values) - limit} more"
    return ", ".join(head) + suffix


def resolve_solver_backend_name(req_json: dict[str, Any] | None) -> str:
    if not isinstance(req_json, dict):
        return DEFAULT_SOLVER_BACKEND

    candidates = [
        req_json.get("solver_backend"),
        req_json.get("solver_agent"),
    ]

    constraints = req_json.get("constraints", {})
    if isinstance(constraints, dict):
        candidates.extend(
            [
                constraints.get("solver_backend"),
                constraints.get("solver_agent"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return DEFAULT_SOLVER_BACKEND


def summarize_manifest(input_manifest: dict[str, Any] | None) -> str:
    if input_manifest is None:
        return "Input manifest: not provided."
    files = input_manifest.get("files", [])
    if not isinstance(files, list):
        files = []
    total_bytes = 0
    has_sizes = False
    examples: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        size = item.get("size_bytes")
        if isinstance(size, (int, float)):
            total_bytes += size
            has_sizes = True
        logical_name = item.get("logical_name")
        path = item.get("path")
        if isinstance(logical_name, str) and logical_name:
            examples.append(logical_name)
        elif isinstance(path, str) and path:
            examples.append(Path(path).name)

    shared_input_dir = input_manifest.get("shared_input_dir") or "unknown"
    manifest_path = input_manifest.get("input_manifest_path") or "unknown"
    size_text = format_bytes(total_bytes if has_sizes else None)
    return (
        f"Input manifest: {len(files)} file(s), total_size={size_text}, "
        f"shared_input_dir={shared_input_dir}, manifest={manifest_path}, "
        f"examples={short_list(examples, limit=4)}."
    )


def summarize_request(req_json: dict[str, Any] | None, work_dir: Path | None) -> str:
    if req_json is None:
        return "Plain text request; no benchmark task metadata was parsed."
    data_info = req_json.get("data", {})
    constraints = req_json.get("constraints", {})
    if not isinstance(data_info, dict):
        data_info = {}
    if not isinstance(constraints, dict):
        constraints = {}
    task_id = req_json.get("task_id") or "unknown"
    task_type = req_json.get("task_type") or "unknown"
    mode = request_mode(req_json)
    solver_backend = resolve_solver_backend_name(req_json)
    response_format = constraints.get("response_format") or "unspecified"
    input_strategy = data_info.get("input_strategy") or constraints.get("input_strategy") or "unspecified"
    max_files = data_info.get("max_files") or constraints.get("max_files") or "unspecified"
    work_dir_text = str(work_dir) if work_dir is not None else str(Path.cwd())
    return (
        f"Task request: task_id={task_id}, task_type={task_type}, mode={mode}, "
        f"solver_backend={solver_backend}, response_format={response_format}, "
        f"input_strategy={input_strategy}, max_files={max_files}, work_dir={work_dir_text}."
    )


def summarize_contract(req_json: dict[str, Any] | None) -> str:
    if req_json is None:
        return "Submission contract: not present."
    contract = req_json.get("submission_contract", {})
    if not isinstance(contract, dict):
        return "Submission contract: malformed or not present."
    required_outputs = contract.get("required_outputs", [])
    names: list[str] = []
    if isinstance(required_outputs, list):
        for item in required_outputs:
            if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str):
                names.append(item["canonical_filename"])
    return (
        f"Submission contract: {len(names)} required output(s): "
        f"{short_list(names, limit=8)}."
    )


def summarize_response(final_text: str) -> str:
    text = final_text.strip()
    try:
        payload = json.loads(text)
    except Exception:
        return f"Solver response: non-JSON text, {len(text)} character(s)."
    if not isinstance(payload, dict):
        return f"Solver response: JSON {type(payload).__name__}, {len(text)} character(s)."
    status = payload.get("status", "unknown")
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict):
        names = [str(name) for name in artifacts.keys()]
        return (
            f"Solver response: status={status}, "
            f"{len(names)} artifact(s): {short_list(names, limit=8)}."
        )
    error = payload.get("error")
    if isinstance(error, str) and error:
        clipped = error if len(error) <= 220 else error[:217] + "..."
        return f"Solver response: status={status}, error={clipped}"
    return f"Solver response: status={status}, no artifact map."


def _is_submission_bundle_json(text: str) -> bool:
    try:
        payload = json.loads(text.strip())
    except Exception:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("artifacts"), dict)


def _should_recover_submission_bundle(
    req_json: dict[str, Any] | None,
    final_text: str,
) -> bool:
    try:
        payload = json.loads(final_text.strip())
    except Exception:
        return True
    if not isinstance(payload, dict):
        return True
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return True
    if payload.get("status") != "ok":
        return True
    required_names = set(extract_required_output_names(req_json))
    return bool(required_names - set(artifacts))


def _read_artifact(path: Path) -> Any:
    if path.suffix.lower() == ".md":
        return path.read_text(encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def recover_submission_bundle_from_outputs(
    req_json: dict[str, Any] | None,
    work_dir: Path | None,
) -> dict[str, Any] | None:
    """Build a bundle from solver output files when stdout is not parseable JSON."""
    if not isinstance(req_json, dict) or work_dir is None:
        return None

    required_names = extract_required_output_names(req_json)
    if not required_names:
        return None

    search_dirs = [work_dir / "outputs", work_dir / "artifacts", work_dir]
    artifacts: dict[str, Any] = {}
    for name in required_names:
        artifact_path = next((base / name for base in search_dirs if (base / name).is_file()), None)
        if artifact_path is None:
            return None
        try:
            artifacts[name] = _read_artifact(artifact_path)
        except Exception as exc:
            logger.warning("Failed to recover artifact %s from %s: %s", name, artifact_path, exc)
            return None

    return {"status": "ok", "artifacts": artifacts}


def resolve_work_dir(req_json: dict[str, Any] | None) -> Path | None:
    if not req_json:
        return None

    data_info = req_json.get("data", {})
    constraints = req_json.get("constraints", {})
    candidates = [
        data_info.get("work_dir") if isinstance(data_info, dict) else None,
        data_info.get("output_dir") if isinstance(data_info, dict) else None,
        constraints.get("work_dir") if isinstance(constraints, dict) else None,
        constraints.get("output_dir") if isinstance(constraints, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            work_dir = Path(candidate).expanduser()
            work_dir.mkdir(parents=True, exist_ok=True)
            return work_dir
    return None


def debug_log_path(work_dir: Path | None = None) -> Path:
    return (work_dir or Path.cwd()) / "debug_oh_output.log"


def scifi_oh_debug_log_path(work_dir: Path | None = None) -> Path:
    return (work_dir or Path.cwd()) / "debug_scifi_oh_output.log"


def scifi_native_debug_log_path(work_dir: Path | None = None) -> Path:
    return (work_dir or Path.cwd()) / "debug_scifi_native_output.log"


def debug_log(blocks: list[tuple[str, str]], work_dir: Path | None = None) -> None:
    log_path = debug_log_path(work_dir)
    with log_path.open("a", encoding="utf-8") as f:
        for title, content in blocks:
            f.write(f"{title}:\n{content}\n")
        f.write("=" * 40 + "\n")


def write_debug_log(path: Path, blocks: list[tuple[str, str]]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for title, content in blocks:
            f.write(f"{title}:\n{content}\n")
        f.write("=" * 40 + "\n")


def print_debug_log_to_container_log(path: Path, *, env_limit_name: str = "SCIFI_OH_PRINT_DEBUG_LOG_MAX_CHARS") -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        logger.info("SciFi-OH debug log not found: %s", path)
        return
    except Exception as exc:
        logger.warning("Failed to print SciFi-OH debug log %s: %s", path, exc)
        return

    raw_limit = os.environ.get(env_limit_name, "0")
    try:
        limit = max(0, int(raw_limit))
    except ValueError:
        limit = 0

    rendered = text
    suffix = ""
    if limit and len(text) > limit:
        rendered = text[-limit:]
        suffix = f"; showing last {limit} chars"

    logger.info(
        "===== BEGIN %s (%s chars%s) =====\n%s\n===== END %s =====",
        path.name,
        len(text),
        suffix,
        rendered,
        path.name,
    )


class OpenHarnessSolverBackend:
    name = DEFAULT_SOLVER_BACKEND

    async def run(
        self,
        prompt: str,
        req_json: dict[str, Any] | None,
        *,
        system_prompt: str,
        status: StatusCallback = noop_status,
        input_manifest: dict[str, Any] | None = None,
        work_dir: Path | None = None,
    ) -> str:
        retry_delay = 2.0
        max_retries = 5
        final_text = None
        if work_dir is None:
            work_dir = resolve_work_dir(req_json)
        env = os.environ.copy()
        if work_dir is not None:
            env["HEPEX_SOLVER_WORK_DIR"] = str(work_dir)
            env["HEPEX_OUTPUT_DIR"] = str(work_dir)

        await status(f"Solver backend {self.name}: prepared OpenHarness. {summarize_request(req_json, work_dir)}")
        if input_manifest is not None:
            await status(summarize_manifest(input_manifest))
        await status(f"Solver backend {self.name}: debug log: {debug_log_path(work_dir)}")

        for attempt in range(max_retries):
            try:
                cmd = [
                    "oh",
                    "--permission-mode",
                    "full_auto",
                    "--dangerously-skip-permissions",
                    "--system-prompt",
                    system_prompt,
                    "--print",
                    prompt,
                ]

                await status(f"Solver backend {self.name}: starting OpenHarness attempt {attempt + 1}/{max_retries}.")

                debug_log(
                    [
                        ("--- Backend ---", self.name),
                        ("--- Request Metadata ---", json_dump(req_json or {})),
                        ("--- Attempt ---", str(attempt + 1)),
                        ("--- Work Dir ---", str(work_dir or Path.cwd())),
                        ("--- Prompt ---", prompt),
                    ],
                    work_dir,
                )

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(work_dir) if work_dir is not None else None,
                    env=env,
                )

                stdout, stderr = await process.communicate()
                stdout_text = stdout.decode(errors="replace")
                stderr_text = stderr.decode(errors="replace")

                await status(
                    (
                        f"Solver backend {self.name}: OpenHarness attempt {attempt + 1}/{max_retries} "
                        f"finished: exit={process.returncode}, stdout={len(stdout_text)} chars, "
                        f"stderr={len(stderr_text)} chars."
                    )
                )

                debug_log(
                    [
                        ("--- Backend ---", self.name),
                        ("--- Attempt Result ---", str(attempt + 1)),
                        ("STDOUT", stdout_text),
                        ("STDERR", stderr_text),
                    ],
                    work_dir,
                )

                if process.returncode == 0 and stdout_text.strip():
                    final_text = stdout_text.strip()
                    if not _is_submission_bundle_json(final_text):
                        recovered_bundle = recover_submission_bundle_from_outputs(req_json, work_dir)
                        if recovered_bundle is not None:
                            final_text = json_dump(recovered_bundle)
                            await status(
                                (
                                    f"Solver backend {self.name}: recovered submission_bundle_v1 "
                                    "from solver output files after non-JSON stdout."
                                )
                            )
                    await status(summarize_response(final_text))
                    break

                err_str = stderr_text.strip()
                retryable_error = (
                    "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str
                    or "timed out" in err_str.lower()
                    or "timeout" in err_str.lower()
                )
                if retryable_error and attempt < max_retries - 1:
                    logger.warning(
                        "Solver backend %s: retryable OpenHarness error. Retrying %s/%s...",
                        self.name,
                        attempt + 1,
                        max_retries,
                    )
                    await status(
                        (
                            f"Solver backend {self.name}: retryable OpenHarness error on "
                            f"attempt {attempt + 1}/{max_retries}; sleeping {retry_delay:.0f}s before retry."
                        )
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30.0)
                    continue

                if process.returncode == 0 and not stdout_text.strip():
                    err_str = err_str or "OpenHarness returned empty stdout."
                final_text = json_dump(
                    {
                        "status": "error",
                        "error": f"OpenHarness failed with exit code {process.returncode}: {err_str}",
                    }
                )
                await status(summarize_response(final_text))
                break

            except Exception as e:
                await status(
                    (
                        f"Solver backend {self.name}: OpenHarness attempt {attempt + 1}/{max_retries} "
                        f"raised {type(e).__name__}: {e}"
                    )
                )
                if attempt == max_retries - 1:
                    final_text = json_dump(
                        {
                            "status": "error",
                            "error": f"Agent run failed: {type(e).__name__}: {e}",
                        }
                    )
                    await status(summarize_response(final_text))
                else:
                    await status(
                        (
                            f"Solver backend {self.name}: sleeping {retry_delay:.0f}s before retry "
                            f"after {type(e).__name__}."
                        )
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30.0)

        if final_text is None:
            final_text = json_dump(
                {"status": "error", "error": "No final response from solver backend"}
            )
            await status(summarize_response(final_text))

        logger.debug("Output from solver backend %s:\n%s", self.name, final_text)
        return final_text


class SciFiOhLoopSolverBackend:
    name = "agent_2_scifi_oh"

    def _system_prompt(self) -> str:
        prompt_path = Path(__file__).resolve().parent / "agent_02_scifi_oh" / "AGENTS.md"
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning("Failed to read SciFi system prompt from %s: %s", prompt_path, exc)
            return "You are a SciFi-style scientific analysis worker."

    async def run(
        self,
        prompt: str,
        req_json: dict[str, Any] | None,
        *,
        system_prompt: str,
        status: StatusCallback = noop_status,
        input_manifest: dict[str, Any] | None = None,
        work_dir: Path | None = None,
    ) -> str:
        del system_prompt
        if work_dir is None:
            work_dir = resolve_work_dir(req_json)
        env = os.environ.copy()
        if work_dir is not None:
            env["HEPEX_SOLVER_WORK_DIR"] = str(work_dir)
            env["HEPEX_OUTPUT_DIR"] = str(work_dir)

        max_attempts = int(
            os.environ.get("SCIFI_OH_MAX_RETRIES", os.environ.get("SCIFI_MAX_RETRIES", "2"))
        )
        scifi_system_prompt = self._system_prompt()

        log_path = scifi_oh_debug_log_path(work_dir)

        await status(
            (
                f"Solver backend {self.name}: prepared SciFi-OH controller with "
                f"OpenHarness executor. {summarize_request(req_json, work_dir)}"
            )
        )
        if input_manifest is not None:
            await status(summarize_manifest(input_manifest))
        await status(f"Solver backend {self.name}: debug log: {log_path}")

        async def worker(sam_prompt: str, attempt: int, total_attempts: int) -> str:
            cmd = [
                "oh",
                "--permission-mode",
                "full_auto",
                "--dangerously-skip-permissions",
                "--system-prompt",
                scifi_system_prompt,
                "--print",
                sam_prompt,
            ]

            await status(
                (
                    f"Solver backend {self.name}: starting OpenHarness executor attempt "
                    f"{attempt}/{total_attempts} under SciFi-OH controller."
                )
            )

            write_debug_log(
                log_path,
                [
                    ("--- Backend ---", self.name),
                    ("--- Worker Executor ---", "openharness"),
                    ("--- Request Metadata ---", json_dump(req_json or {})),
                    ("--- SciFi-OH Attempt ---", str(attempt)),
                    ("--- Work Dir ---", str(work_dir or Path.cwd())),
                    ("--- SAM Prompt ---", sam_prompt),
                ],
            )

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(work_dir) if work_dir is not None else None,
                    env=env,
                )
                stdout, stderr = await process.communicate()
            except Exception as exc:
                await status(
                    (
                        f"Solver backend {self.name}: SciFi-OH worker attempt {attempt}/{total_attempts} "
                        f"raised {type(exc).__name__} from OpenHarness executor: {exc}."
                    )
                )
                return json_dump(
                    {
                        "status": "error",
                        "error": f"SciFi-OH OpenHarness executor failed: {type(exc).__name__}: {exc}",
                    }
                )

            stdout_text = stdout.decode(errors="replace")
            stderr_text = stderr.decode(errors="replace")

            await status(
                (
                    f"Solver backend {self.name}: SciFi-OH worker attempt {attempt}/{total_attempts} "
                    f"finished via OpenHarness executor: exit={process.returncode}, stdout={len(stdout_text)} chars, "
                    f"stderr={len(stderr_text)} chars."
                )
            )

            write_debug_log(
                log_path,
                [
                    ("--- Backend ---", self.name),
                    ("--- Worker Executor ---", "openharness"),
                    ("--- SciFi-OH Attempt Result ---", str(attempt)),
                    ("STDOUT", stdout_text),
                    ("STDERR", stderr_text),
                ],
            )

            if process.returncode == 0 and stdout_text.strip():
                final_text = stdout_text.strip()
                if not _is_submission_bundle_json(final_text):
                    recovered_bundle = recover_submission_bundle_from_outputs(req_json, work_dir)
                    if recovered_bundle is not None:
                        final_text = json_dump(recovered_bundle)
                        await status(
                            (
                                f"Solver backend {self.name}: recovered submission_bundle_v1 "
                                "from solver output files after non-JSON stdout."
                            )
                        )
                await status(summarize_response(final_text))
                return final_text

            err_str = stderr_text.strip() or "OpenHarness returned empty stdout."
            final_text = json_dump(
                {
                    "status": "error",
                    "error": f"SciFi-OH OpenHarness executor failed with exit code {process.returncode}: {err_str}",
                }
            )
            await status(summarize_response(final_text))
            return final_text

        loop = SciFiLoop(worker=worker, status=status, max_attempts=max_attempts)
        result = await loop.run(
            base_prompt=prompt,
            req_json=req_json,
            input_manifest=input_manifest,
            work_dir=work_dir,
        )
        await status(
            (
                f"Solver backend {self.name}: completed SciFi-OH loop after "
                f"{result.attempts} attempt(s); review={result.review.summary}."
            )
        )
        await status(summarize_response(result.final_text))
        print_debug_log_to_container_log(log_path)
        logger.debug("Output from solver backend %s:\n%s", self.name, result.final_text)
        return result.final_text


class SciFiNativeSolverBackend:
    def __init__(
        self,
        *,
        name: str = "agent_3a_scifi_native",
        prompt_package: str = "agent_03a_scifi_native",
        prompt_builder: Callable[..., str] | None = None,
        loop_class: Callable[..., Any] = NativeSciFiLoop03A,
        worker_class: Callable[..., Any] = NativeSciFiWorker03A,
        enable_scifi_v2_tools: bool = False,
        loop_label: str = "SciFi-native loop",
    ) -> None:
        self.name = name
        self.prompt_package = prompt_package
        self.prompt_builder = prompt_builder
        self.loop_class = loop_class
        self.worker_class = worker_class
        self.enable_scifi_v2_tools = enable_scifi_v2_tools
        self.loop_label = loop_label

    def _system_prompt(self) -> str:
        prompt_path = Path(__file__).resolve().parent / self.prompt_package / "AGENTS.md"
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning("Failed to read native SciFi system prompt from %s: %s", prompt_path, exc)
            return "You are a SciFi-style scientific analysis worker."

    async def run(
        self,
        prompt: str,
        req_json: dict[str, Any] | None,
        *,
        system_prompt: str,
        status: StatusCallback = noop_status,
        input_manifest: dict[str, Any] | None = None,
        work_dir: Path | None = None,
    ) -> str:
        del system_prompt
        if work_dir is None:
            work_dir = resolve_work_dir(req_json)
        if work_dir is not None:
            os.environ["HEPEX_SOLVER_WORK_DIR"] = str(work_dir)
            os.environ["HEPEX_OUTPUT_DIR"] = str(work_dir)

        max_attempts = int(
            os.environ.get("SCIFI_NATIVE_MAX_RETRIES", os.environ.get("SCIFI_MAX_RETRIES", "2"))
        )
        native_system_prompt = self._system_prompt()
        log_path = scifi_native_debug_log_path(work_dir)

        await status(
            (
                f"Solver backend {self.name}: prepared native SciFi controller and worker. "
                f"{summarize_request(req_json, work_dir)}"
            )
        )
        if input_manifest is not None:
            await status(summarize_manifest(input_manifest))
        await status(f"Solver backend {self.name}: debug log: {log_path}")

        async def worker(sam_prompt: str, attempt: int, total_attempts: int) -> str:
            await status(
                (
                    f"Solver backend {self.name}: starting native SciFi worker attempt "
                    f"{attempt}/{total_attempts}."
                )
            )
            write_debug_log(
                log_path,
                [
                    ("--- Backend ---", self.name),
                    ("--- Worker Executor ---", "native_scifi"),
                    ("--- Request Metadata ---", json_dump(req_json or {})),
                    ("--- SciFi Native Attempt ---", str(attempt)),
                    ("--- Work Dir ---", str(work_dir or Path.cwd())),
                    ("--- SAM Prompt ---", sam_prompt),
                ],
            )

            native_worker = self.worker_class(
                system_prompt=native_system_prompt,
                req_json=req_json,
                input_manifest=input_manifest,
                work_dir=work_dir,
                status=status,
                debug_log_path=log_path,
                enable_scifi_v2_tools=self.enable_scifi_v2_tools,
            )
            try:
                final_text = await native_worker.run(sam_prompt)
            except Exception as exc:
                final_text = json_dump(
                    {
                        "status": "error",
                        "error": f"SciFi native worker failed: {type(exc).__name__}: {exc}",
                    }
                )

            if _should_recover_submission_bundle(req_json, final_text):
                recovered_bundle = recover_submission_bundle_from_outputs(req_json, work_dir)
                if recovered_bundle is not None:
                    final_text = json_dump(recovered_bundle)
                    await status(
                        (
                            f"Solver backend {self.name}: recovered submission_bundle_v1 "
                            "from solver output files after non-JSON worker output."
                        )
                    )

            write_debug_log(
                log_path,
                [
                    ("--- Backend ---", self.name),
                    ("--- Worker Executor ---", "native_scifi"),
                    ("--- SciFi Native Attempt Result ---", str(attempt)),
                    ("FINAL_TEXT", final_text),
                ],
            )
            await status(summarize_response(final_text))
            return final_text

        loop_kwargs: dict[str, Any] = {
            "worker": worker,
            "status": status,
            "max_attempts": max_attempts,
            "label": self.loop_label,
        }
        if self.prompt_builder is not None:
            loop_kwargs["prompt_builder"] = self.prompt_builder
        loop = self.loop_class(**loop_kwargs)
        result = await loop.run(
            base_prompt=prompt,
            req_json=req_json,
            input_manifest=input_manifest,
            work_dir=work_dir,
        )
        await status(
            (
                f"Solver backend {self.name}: completed native SciFi loop after "
                f"{result.attempts} attempt(s); review={result.review.summary}."
            )
        )
        await status(summarize_response(result.final_text))
        logger.debug("Output from solver backend %s:\n%s", self.name, result.final_text)
        return result.final_text


_SCIFI_NATIVE_03A = SciFiNativeSolverBackend()
_SCIFI_NATIVE_03B = SciFiNativeSolverBackend(
    name="agent_3b_scifi_native",
    prompt_package="agent_03b_scifi_native",
    prompt_builder=build_general_sam_prompt,
    loop_class=NativeSciFiLoop03B,
    worker_class=NativeSciFiWorker03B,
    loop_label="SciFi-native general loop",
)
_SCIFI_NATIVE_03C = SciFiNativeSolverBackend(
    name="agent_3c_scifi_native",
    prompt_package="agent_03c_scifi_native",
    prompt_builder=build_v2_sam_prompt,
    loop_class=NativeSciFiLoop03C,
    worker_class=NativeSciFiWorker03C,
    enable_scifi_v2_tools=True,
    loop_label="SciFi-native v2 loop",
)


_BACKENDS: dict[str, SolverBackend] = {
    DEFAULT_SOLVER_BACKEND: OpenHarnessSolverBackend(),
    "openharness": OpenHarnessSolverBackend(),
    "oh": OpenHarnessSolverBackend(),
    "agent_2_scifi_oh": SciFiOhLoopSolverBackend(),
    "scifi_oh": SciFiOhLoopSolverBackend(),
    "agent_3a_scifi_native": _SCIFI_NATIVE_03A,
    "agent_03a_scifi_native": _SCIFI_NATIVE_03A,
    "scifi_native": _SCIFI_NATIVE_03A,
    "native_scifi": _SCIFI_NATIVE_03A,
    "agent_3b_scifi_native": _SCIFI_NATIVE_03B,
    "agent_03b_scifi_native": _SCIFI_NATIVE_03B,
    "scifi_native_general": _SCIFI_NATIVE_03B,
    "native_scifi_general": _SCIFI_NATIVE_03B,
    "agent_3c_scifi_native": _SCIFI_NATIVE_03C,
    "agent_03c_scifi_native": _SCIFI_NATIVE_03C,
    "scifi_native_v2": _SCIFI_NATIVE_03C,
    "native_scifi_v2": _SCIFI_NATIVE_03C,
}


def get_solver_backend(name: str | None) -> SolverBackend:
    backend_name = (name or DEFAULT_SOLVER_BACKEND).strip()
    backend = _BACKENDS.get(backend_name)
    if backend is None:
        available = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown solver_backend '{backend_name}'. Available solver backends: {available}")
    return backend
