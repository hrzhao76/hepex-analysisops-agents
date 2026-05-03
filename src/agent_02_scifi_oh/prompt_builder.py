from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent / "skills"


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def detect_task_level(req_json: dict[str, Any] | None) -> str:
    if not isinstance(req_json, dict):
        return "generic"
    contract = req_json.get("submission_contract", {})
    level = contract.get("level") if isinstance(contract, dict) else None
    task_type = str(req_json.get("task_type") or "").lower()
    task_id = str(req_json.get("task_id") or "").lower()
    combined = f"{level or ''} {task_type} {task_id}"
    if "l1" in combined or "hyy_l1" in combined or "t002_hyy_v5_l1" in combined:
        return "l1"
    if "l2" in combined or "hyy_l2" in combined or "t003_hyy_v5_l2" in combined:
        return "l2"
    if "l3" in combined or "hyy_l3" in combined or "t004_hyy_v5_l3" in combined:
        return "l3"
    return "generic"


def _load_skill(name: str) -> str:
    path = SKILL_DIR / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _required_output_names(req_json: dict[str, Any] | None) -> list[str]:
    if not isinstance(req_json, dict):
        return []
    contract = req_json.get("submission_contract", {})
    outputs = contract.get("required_outputs", []) if isinstance(contract, dict) else []
    names: list[str] = []
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str):
                names.append(item["canonical_filename"])
    return names


def build_sam_prompt(
    base_prompt: str,
    req_json: dict[str, Any] | None,
    input_manifest: dict[str, Any] | None,
    *,
    attempt: int,
    max_attempts: int,
    review_feedback: dict[str, Any] | None = None,
) -> str:
    """Render a SciFi-style SAM prompt from the Green task request."""
    task_level = detect_task_level(req_json)
    required_outputs = _required_output_names(req_json)
    data_info = req_json.get("data", {}) if isinstance(req_json, dict) else {}
    contract = req_json.get("submission_contract", {}) if isinstance(req_json, dict) else {}
    constraints = req_json.get("constraints", {}) if isinstance(req_json, dict) else {}

    skills = [_load_skill("bundle_contract_review.md")]
    if task_level == "l1":
        skills.append(_load_skill("hyy_l1.md"))
    elif task_level in {"l2", "l3"}:
        skills.append(_load_skill("hyy_l2_l3.md"))

    feedback_block = ""
    if review_feedback:
        feedback_block = (
            "\n## Independent Review Feedback From Previous Attempt\n"
            "The previous attempt failed deterministic review. Fix every concrete "
            "item below before returning the next bundle.\n\n"
            "```json\n"
            f"{_json_dump(review_feedback)}\n"
            "```\n"
        )

    manifest_block = ""
    if input_manifest is not None:
        manifest_block = (
            "\n### Resolved Input Manifest\n"
            "```json\n"
            f"{_json_dump(input_manifest)}\n"
            "```\n"
        )

    return "\n".join(
        [
            "---",
            "Rank: 2",
            "Skills: hyy_analysis, bundle_contract_review",
            "---",
            "",
            f"# AgentBeats HEPEx {task_level.upper()} Submission Bundle",
            "",
            "## Context",
            f"SciFi-OH loop attempt {attempt} of {max_attempts}.",
            "",
            "### Green/Purple Prepared Prompt",
            base_prompt.strip(),
            "",
            "### Request Metadata",
            "```json",
            _json_dump(
                {
                    "task_id": req_json.get("task_id") if isinstance(req_json, dict) else None,
                    "task_type": req_json.get("task_type") if isinstance(req_json, dict) else None,
                    "detected_task_level": task_level,
                    "required_outputs": required_outputs,
                }
            ),
            "```",
            "",
            "### Submission Contract",
            "```json",
            _json_dump(contract),
            "```",
            "",
            "### Runtime Data",
            "```json",
            _json_dump(data_info),
            "```",
            manifest_block,
            "",
            "### Runtime Constraints",
            "```json",
            _json_dump(constraints),
            "```",
            "",
            "### SciFi-OH Skills",
            "\n\n".join(skill for skill in skills if skill),
            feedback_block,
            "",
            "## Todo",
            "1. Use the runtime manifest and task instructions to run the requested Hyy analysis.",
            "2. Generate any scripts, logs, plots, and intermediate files under the solver work directory.",
            "3. Build every required artifact from actual computation over the provided input files.",
            "4. Return exactly one `submission_bundle_v1` JSON object on stdout.",
            "",
            "## Expect",
            "- The final stdout is parseable JSON, not markdown.",
            "- Top-level JSON has `status` and `artifacts`.",
            "- `artifacts` contains every required canonical filename and no undeclared names.",
            "- JSON artifacts are JSON objects; markdown artifacts are strings.",
            "- Required schema fields and trace fields are present for the detected task level.",
            "- Histogram, residual, fit, interpretation, and trace claims are internally consistent.",
        ]
    ).strip()
