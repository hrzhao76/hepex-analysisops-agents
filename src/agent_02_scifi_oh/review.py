from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from .prompt_builder import detect_task_level


JSON_TYPES = {"json", "table_json", "image_ref"}
TEXT_TYPES = {"markdown", "text"}

L1_STAGE_IDS = [
    "data_loading",
    "event_selection",
    "diphoton_mass_construction",
    "spectrum_histogramming",
    "uncertainty_assignment",
    "spectrum_fitting",
    "signal_interpretation",
]

L1_CUT_IDS = {
    "at_least_two_photons",
    "leading_photon_tight_id",
    "subleading_photon_tight_id",
    "leading_photon_pt",
    "subleading_photon_pt",
    "leading_photon_isolation",
    "subleading_photon_isolation",
    "leading_photon_eta_transition_veto",
    "subleading_photon_eta_transition_veto",
    "diphoton_mass_nonzero",
    "leading_photon_pt_over_m_yy",
    "subleading_photon_pt_over_m_yy",
}

L2_L3_STAGE_FAMILIES = {
    "data_access",
    "object_or_event_selection",
    "observable_construction",
    "spectrum_or_summary_construction",
    "inference_or_signal_localization",
    "residual_or_background_subtraction",
    "validation",
    "interpretation",
}


@dataclass
class ReviewResult:
    passed: bool
    feedback: dict[str, Any]
    bundle: dict[str, Any] | None = None

    @property
    def summary(self) -> str:
        if self.passed:
            return "PASS"
        counts = {
            key: len(value)
            for key, value in self.feedback.items()
            if isinstance(value, list) and value
        }
        return "FAIL " + ", ".join(f"{key}={value}" for key, value in counts.items())


def _artifact_entries(contract: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for section in ("required_outputs", "optional_outputs"):
        values = contract.get(section, [])
        if isinstance(values, list):
            entries.extend(item for item in values if isinstance(item, dict))
    return entries


def _required_names(contract: dict[str, Any]) -> list[str]:
    outputs = contract.get("required_outputs", [])
    if not isinstance(outputs, list):
        return []
    return [
        item["canonical_filename"]
        for item in outputs
        if isinstance(item, dict) and isinstance(item.get("canonical_filename"), str)
    ]


def _declared_type_map(contract: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in _artifact_entries(contract):
        name = item.get("canonical_filename")
        if isinstance(name, str):
            mapping[name] = str(item.get("type", "json"))
    return mapping


def _get_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _first_number(payload: dict[str, Any], names: list[str]) -> float | None:
    for name in names:
        value = _get_path(payload, name)
        number = _as_number(value)
        if number is not None:
            return number
    return None


def _check_required_schema_fields(
    artifacts: dict[str, Any],
    contract: dict[str, Any],
    errors: list[str],
) -> None:
    schemas = contract.get("schemas", {})
    if not isinstance(schemas, dict):
        return
    for name, schema in schemas.items():
        if name not in artifacts or not isinstance(schema, dict):
            continue
        artifact = artifacts[name]
        if not isinstance(artifact, dict):
            continue
        required = schema.get("required_fields", [])
        if isinstance(required, list):
            for field in required:
                if isinstance(field, str) and field not in artifact:
                    errors.append(f"{name} missing required field {field}")
        nested = schema.get("nested_required_fields", {})
        if isinstance(nested, dict):
            for field, nested_schema in nested.items():
                if not isinstance(nested_schema, dict) or field not in artifact:
                    continue
                nested_required = nested_schema.get("required_fields", [])
                if not isinstance(nested_required, list):
                    continue
                values = artifact[field]
                if isinstance(values, list):
                    for idx, value in enumerate(values):
                        if not isinstance(value, dict):
                            errors.append(f"{name}.{field}[{idx}] must be an object")
                            continue
                        for nested_field in nested_required:
                            if isinstance(nested_field, str) and nested_field not in value:
                                errors.append(
                                    f"{name}.{field}[{idx}] missing required field {nested_field}"
                                )
                elif isinstance(values, dict):
                    for nested_field in nested_required:
                        if isinstance(nested_field, str) and nested_field not in values:
                            errors.append(f"{name}.{field} missing required field {nested_field}")


def _check_array_alignment(artifacts: dict[str, Any], errors: list[str]) -> None:
    spectrum = artifacts.get("diphoton_mass_spectrum.json")
    if isinstance(spectrum, dict):
        edges = spectrum.get("bin_edges_gev", spectrum.get("bin_edges"))
        counts = spectrum.get("bin_counts")
        uncertainties = spectrum.get("bin_uncertainties")
        if isinstance(edges, list) and isinstance(counts, list) and len(edges) != len(counts) + 1:
            errors.append("diphoton_mass_spectrum edges length must equal counts length + 1")
        if (
            isinstance(counts, list)
            and isinstance(uncertainties, list)
            and len(counts) != len(uncertainties)
        ):
            errors.append("diphoton_mass_spectrum counts and uncertainties length mismatch")

    residual = artifacts.get("data_minus_background.json")
    if isinstance(residual, dict):
        residual_counts = residual.get("residual_counts")
        residual_uncertainties = residual.get("residual_uncertainties")
        edges = residual.get("bin_edges_gev", residual.get("bin_edges"))
        centers = residual.get("bin_centers")
        if isinstance(edges, list) and isinstance(residual_counts, list) and len(edges) != len(residual_counts) + 1:
            errors.append("data_minus_background edges length must equal residual length + 1")
        if isinstance(centers, list) and isinstance(residual_counts, list) and len(centers) != len(residual_counts):
            errors.append("data_minus_background centers and residual length mismatch")
        if (
            isinstance(residual_counts, list)
            and isinstance(residual_uncertainties, list)
            and len(residual_counts) != len(residual_uncertainties)
        ):
            errors.append("data_minus_background residual and uncertainty length mismatch")


def _check_peak_consistency(artifacts: dict[str, Any], errors: list[str]) -> None:
    fit = artifacts.get("diphoton_fit_summary.json")
    trace = artifacts.get("submission_trace.json")
    if not isinstance(fit, dict) or not isinstance(trace, dict):
        return
    fit_peak = _first_number(
        fit,
        [
            "signal_peak_position",
            "signal_peak_gev",
            "gaussian_mean_gev",
            "signal_peak_mass_GeV",
            "signal_peak_mass_gev",
        ],
    )
    trace_peak = _first_number(
        trace,
        [
            "reported_result.signal_peak_position",
            "reported_result.signal_peak_gev",
            "result_summary.signal_peak_gev",
        ],
    )
    if fit_peak is not None and trace_peak is not None and abs(fit_peak - trace_peak) > 1e-6:
        errors.append(
            f"signal peak mismatch between fit summary ({fit_peak}) and trace ({trace_peak})"
        )


def _check_l1(artifacts: dict[str, Any], errors: list[str]) -> None:
    trace = artifacts.get("submission_trace.json")
    fit = artifacts.get("diphoton_fit_summary.json")
    if not isinstance(trace, dict):
        errors.append("L1 submission_trace.json must be a JSON object")
        return

    for field in ("input_files_used", "input_file_count", "selected_events_total", "cutflow_summary"):
        if field not in trace:
            errors.append(f"L1 trace missing {field}")

    input_files = trace.get("input_files_used")
    input_count = trace.get("input_file_count")
    if isinstance(input_files, list) and isinstance(input_count, int) and len(input_files) != input_count:
        errors.append("L1 input_file_count must match len(input_files_used)")

    selected_total = trace.get("selected_events_total")
    cutflow = trace.get("cutflow_summary")
    if isinstance(cutflow, dict) and isinstance(selected_total, int):
        selected_cutflow = cutflow.get("selected_events")
        if isinstance(selected_cutflow, int) and selected_total != selected_cutflow:
            errors.append("L1 selected_events_total must match cutflow_summary.selected_events")

    stages = trace.get("workflow_stages")
    if not isinstance(stages, list):
        errors.append("L1 workflow_stages must be a list")
    else:
        actual = [item.get("stage_id") for item in stages if isinstance(item, dict)]
        if actual != L1_STAGE_IDS:
            errors.append(f"L1 workflow_stages must match strict baseline order {L1_STAGE_IDS}")

    cuts = trace.get("cuts_applied")
    if not isinstance(cuts, list):
        errors.append("L1 cuts_applied must be a list")
    else:
        actual_cuts = {item.get("cut_id") for item in cuts if isinstance(item, dict)}
        missing = sorted(L1_CUT_IDS - actual_cuts)
        if missing:
            errors.append(f"L1 cuts_applied missing baseline cuts: {missing}")

    fit_family = trace.get("fit_model_family_used")
    if not isinstance(fit_family, dict):
        errors.append("L1 trace missing fit_model_family_used object")
    else:
        if str(fit_family.get("signal", "")).lower() != "gaussian":
            errors.append("L1 fit_model_family_used.signal must be gaussian")
        if str(fit_family.get("background", "")).lower() != "polynomial":
            errors.append("L1 fit_model_family_used.background must be polynomial")
        if fit_family.get("background_order") != 4:
            errors.append("L1 fit_model_family_used.background_order must be 4")
        fit_range = fit_family.get("fit_range_GeV")
        if fit_range != [100.0, 160.0] and fit_range != [100, 160]:
            errors.append("L1 fit_model_family_used.fit_range_GeV must be [100.0, 160.0]")

    if isinstance(fit, dict):
        if str(fit.get("signal_model_family", "")).lower() != "gaussian":
            errors.append("L1 diphoton_fit_summary signal_model_family must be gaussian")
        if str(fit.get("background_model_family", "")).lower() != "polynomial":
            errors.append("L1 diphoton_fit_summary background_model_family must be polynomial")


def _check_l2_l3(artifacts: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    trace = artifacts.get("submission_trace.json")
    interpretation = artifacts.get("interpretation.md")
    if not isinstance(trace, dict):
        errors.append("L2/L3 submission_trace.json must be a JSON object")
        return

    for field in (
        "workflow_stages",
        "data_scope",
        "scientific_decisions",
        "observable_constructed",
        "inference_strategy",
        "validation_actions",
        "output_files_generated",
    ):
        if field not in trace:
            errors.append(f"L2/L3 trace missing {field}")

    stages = trace.get("workflow_stages")
    if isinstance(stages, list):
        families = {item.get("family") for item in stages if isinstance(item, dict)}
        missing = sorted(L2_L3_STAGE_FAMILIES - families)
        if missing:
            errors.append(f"L2/L3 workflow stage families missing: {missing}")

    fit = artifacts.get("diphoton_fit_summary.json")
    if isinstance(fit, dict) and isinstance(interpretation, str):
        peak = _first_number(
            fit,
            [
                "signal_peak_gev",
                "gaussian_mean_gev",
                "signal_peak_position",
                "signal_peak_mass_GeV",
                "signal_peak_mass_gev",
            ],
        )
        if peak is not None and not (123.0 <= peak <= 127.0):
            lower_text = interpretation.lower()
            overclaim_terms = ("discovery", "clear higgs", "observed higgs", "definitive")
            if any(term in lower_text for term in overclaim_terms):
                warnings.append(
                    "interpretation appears to overclaim a Higgs-like result while the peak is outside 123-127 GeV"
                )


def _feedback(
    missing: list[str],
    schema_errors: list[str],
    trace_errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    retry_parts = []
    if missing:
        retry_parts.append("add every missing required artifact")
    if schema_errors:
        retry_parts.append("fix JSON/markdown types, required fields, and array alignment")
    if trace_errors:
        retry_parts.append("fix submission_trace consistency and task-specific trace fields")
    if warnings:
        retry_parts.append("make interpretation scientifically cautious and consistent")
    retry_instruction = (
        "; ".join(retry_parts)
        if retry_parts
        else "independent review passed; no retry required"
    )
    return {
        "missing_required_artifacts": missing,
        "schema_or_type_errors": schema_errors,
        "trace_consistency_errors": trace_errors,
        "scientific_consistency_warnings": warnings,
        "retry_instruction": retry_instruction,
    }


def review_submission_bundle(
    req_json: dict[str, Any] | None,
    final_text: str,
    input_manifest: dict[str, Any] | None = None,
    work_dir: Any | None = None,
) -> ReviewResult:
    del input_manifest, work_dir
    missing: list[str] = []
    schema_errors: list[str] = []
    trace_errors: list[str] = []
    warnings: list[str] = []

    try:
        bundle = json.loads(final_text.strip())
    except Exception as exc:
        schema_errors.append(f"solver response is not parseable JSON: {exc}")
        return ReviewResult(False, _feedback(missing, schema_errors, trace_errors, warnings))

    if not isinstance(bundle, dict):
        schema_errors.append("submission bundle must be a JSON object")
        return ReviewResult(False, _feedback(missing, schema_errors, trace_errors, warnings))

    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        schema_errors.append("submission bundle requires an artifacts object")
        return ReviewResult(False, _feedback(missing, schema_errors, trace_errors, warnings), bundle=bundle)

    contract = req_json.get("submission_contract", {}) if isinstance(req_json, dict) else {}
    if not isinstance(contract, dict):
        contract = {}
    required = set(_required_names(contract))
    declared_types = _declared_type_map(contract)
    declared = set(declared_types)

    missing.extend(sorted(required - set(artifacts)))
    unknown = sorted(set(artifacts) - declared)
    if unknown:
        schema_errors.append(f"bundle contains undeclared artifact(s): {unknown}")

    for name, payload in artifacts.items():
        art_type = declared_types.get(name, "json")
        if art_type in TEXT_TYPES:
            if not isinstance(payload, str):
                schema_errors.append(f"{name} must be a string for {art_type} output")
        elif art_type in JSON_TYPES:
            if not isinstance(payload, dict):
                schema_errors.append(f"{name} must be a JSON object for {art_type} output")

    interpretation = artifacts.get("interpretation.md")
    if isinstance(interpretation, str):
        min_chars = (
            contract.get("schemas", {})
            .get("interpretation.md", {})
            .get("constraints", {})
            .get("min_characters", 1)
            if isinstance(contract.get("schemas"), dict)
            else 1
        )
        if len(interpretation.strip()) < int(min_chars):
            schema_errors.append(f"interpretation.md must be at least {min_chars} characters")

    _check_required_schema_fields(artifacts, contract, schema_errors)
    _check_array_alignment(artifacts, schema_errors)
    _check_peak_consistency(artifacts, trace_errors)

    level = detect_task_level(req_json)
    if level == "l1":
        _check_l1(artifacts, trace_errors)
    elif level in {"l2", "l3"}:
        _check_l2_l3(artifacts, trace_errors, warnings)

    passed = not missing and not schema_errors and not trace_errors
    return ReviewResult(
        passed=passed,
        feedback=_feedback(missing, schema_errors, trace_errors, warnings),
        bundle=bundle,
    )

