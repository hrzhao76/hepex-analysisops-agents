from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from bundle_runtime import (
    build_minimal_submission_bundle,
    error_response,
    is_submission_bundle_request,
    load_input_manifest,
    parse_task_request,
    request_mode,
    should_mock_submission_bundle,
)
from solver_backends import (
    get_solver_backend,
    resolve_solver_backend_name,
    resolve_work_dir,
    summarize_contract,
    summarize_manifest,
    summarize_request,
    summarize_response,
)

logger = logging.getLogger(__name__)


class PurpleAgent:
    def __init__(self):
        self.app_name = "hepex_analysisops"
        prompt_candidates = [
            Path(__file__).resolve().parent / "agent_01_oh" / "AGENTS.md",
            Path("./AGENTS.md"),
        ]
        try:
            for prompt_path in prompt_candidates:
                if prompt_path.exists():
                    self.system_prompt = prompt_path.read_text(encoding="utf-8").strip()
                    break
            else:
                raise FileNotFoundError("No AGENTS.md prompt found")
        except Exception as e:
            logger.error(f"Failed to read OpenHarness system prompt: {e}")
            self.system_prompt = "You are a physics analysis agent."

    @staticmethod
    def _json_dump(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    async def _working_status(updater: TaskUpdater | None, text: str) -> None:
        logger.info("Purple solver status: %s", text)
        if updater is None:
            return
        try:
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(text),
            )
        except Exception:
            logger.exception("Failed to emit Purple solver status update")

    def _build_bundle_prompt(
        self,
        prompt: str,
        req_json: dict[str, Any],
        input_manifest: dict[str, Any] | None,
    ) -> str:
        contract = req_json.get("submission_contract", {})
        data_info = req_json.get("data", {})
        constraints = req_json.get("constraints", {})
        mode = request_mode(req_json)
        solver_backend = resolve_solver_backend_name(req_json)

        sections = [
            prompt.strip(),
            "",
            "Additional runtime context from the benchmark:",
            f"- request_mode: {mode}",
            f"- solver_backend: {solver_backend}",
            f"- task_id: {req_json.get('task_id', '')}",
            f"- task_type: {req_json.get('task_type', '')}",
            "",
            "Working directory requirements:",
            "- If request.data.work_dir or request.data.output_dir is set, use that directory as the analysis root.",
            "- Put generated scripts, logs, plots, and intermediate task outputs under that analysis root.",
            "- Do not write new task outputs into $HOME/output directly when an analysis root is provided.",
            "- Reusable downloaded input data may still be cached separately when needed.",
            "",
            "You must return exactly one JSON object with this top-level shape:",
            '{',
            '  "status": "ok" | "error",',
            '  "artifacts": { "canonical_filename": <json-object-or-markdown-string>, ... }',
            '}',
            "",
            "Hard requirements:",
            "- Do not wrap the final JSON in markdown fences.",
            "- The artifact keys must include every submission_contract.required_outputs[*].canonical_filename.",
            "- The artifact keys may also include declared submission_contract.optional_outputs[*].canonical_filename.",
            "- Do not include artifact keys that are not declared in the submission contract.",
            "- JSON artifacts must be JSON objects, and markdown artifacts must be plain strings.",
            "- If the task cannot be completed, return a JSON object with status=\"error\" and an explanatory error field.",
            "",
            "submission_contract JSON:",
            self._json_dump(contract),
            "",
            "request.data JSON:",
            self._json_dump(data_info),
            "",
            "request.constraints JSON:",
            self._json_dump(constraints),
        ]

        if input_manifest is not None:
            sections.extend(
                [
                    "",
                    "Resolved input_manifest JSON:",
                    self._json_dump(input_manifest),
                ]
            )

        return "\n".join(sections).strip()

    def _prepare_request(
        self, input_payload: str
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None, str | None]:
        req_json = parse_task_request(input_payload, logger)
        if req_json is None:
            return None, input_payload, None, None

        prompt = req_json.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            logger.warning("Received request without a usable 'prompt' field")
            prompt = input_payload

        input_manifest = None
        if is_submission_bundle_request(req_json):
            manifest_path = req_json.get("data", {}).get("input_manifest_path")
            if isinstance(manifest_path, str) and manifest_path.strip():
                try:
                    input_manifest = load_input_manifest(req_json)
                except Exception as exc:
                    return (
                        req_json,
                        prompt,
                        None,
                        self._json_dump(error_response(str(exc))),
                    )
            elif should_mock_submission_bundle(req_json):
                return (
                    req_json,
                    prompt,
                    None,
                    self._json_dump(
                        error_response(
                            "Missing required data.input_manifest_path for submission_bundle_v1 request."
                        )
                    ),
                )

            if should_mock_submission_bundle(req_json):
                bundle = build_minimal_submission_bundle(req_json, input_manifest or {})
                return req_json, prompt, input_manifest, self._json_dump(bundle)

            prompt = self._build_bundle_prompt(prompt, req_json, input_manifest)

        return req_json, prompt, input_manifest, None

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        input_payload = get_message_text(message)
        req_json, prompt, input_manifest, early_response = self._prepare_request(input_payload)
        work_dir = resolve_work_dir(req_json)
        solver_backend_name = resolve_solver_backend_name(req_json)

        status_text = "Running analysis agent via OpenHarness..."
        if req_json and is_submission_bundle_request(req_json):
            bundle_mode = request_mode(req_json)
            if early_response is not None and should_mock_submission_bundle(req_json):
                status_text = "Preparing deterministic submission_bundle_v1 response."
            else:
                manifest_note = ""
                if input_manifest is not None:
                    manifest_note = f" ({len(input_manifest.get('files', []))} manifest file(s) visible)"
                status_text = (
                    f"Running submission_bundle_v1 request via solver_backend={solver_backend_name} "
                    f"[{bundle_mode}]{manifest_note}."
                )

        await updater.update_status(
            TaskState.working,
            new_agent_text_message(status_text),
        )
        await self._working_status(updater, summarize_request(req_json, work_dir))
        if req_json and is_submission_bundle_request(req_json):
            await self._working_status(updater, summarize_contract(req_json))
        if input_manifest is not None:
            await self._working_status(updater, summarize_manifest(input_manifest))

        try:
            if early_response is not None:
                final_text = early_response
                await self._working_status(updater, summarize_response(final_text))
            else:
                solver_backend = get_solver_backend(solver_backend_name)
                final_text = await solver_backend.run(
                    prompt,
                    req_json,
                    system_prompt=self.system_prompt,
                    status=lambda text: self._working_status(updater, text),
                    input_manifest=input_manifest,
                    work_dir=work_dir,
                )

            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=final_text))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.completed, new_agent_text_message("Done."))

        except Exception as e:
            err = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=self._json_dump(err)))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.failed, new_agent_text_message(err["error"]))


WhiteAgent = PurpleAgent
