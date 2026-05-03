from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_02_scifi_oh.loop import SciFiLoop
from agent_02_scifi_oh.prompt_builder import build_sam_prompt
from agent_02_scifi_oh.review import L1_CUT_IDS, L1_STAGE_IDS, review_submission_bundle
from solver_backends import get_solver_backend


def _l1_contract() -> dict:
    return {
        "version": 2,
        "level": "l1",
        "required_outputs": [
            {"canonical_filename": "diphoton_mass_spectrum.json", "type": "json"},
            {"canonical_filename": "diphoton_fit_summary.json", "type": "json"},
            {"canonical_filename": "data_minus_background.json", "type": "json"},
            {"canonical_filename": "interpretation.md", "type": "markdown"},
            {"canonical_filename": "submission_trace.json", "type": "json"},
        ],
        "schemas": {
            "diphoton_mass_spectrum.json": {
                "required_fields": ["bin_edges", "bin_counts", "bin_uncertainties"]
            },
            "diphoton_fit_summary.json": {
                "required_fields": [
                    "signal_model_family",
                    "background_model_family",
                    "fit_range",
                    "signal_peak_position",
                ]
            },
            "data_minus_background.json": {
                "required_fields": ["bin_centers", "residual_counts", "residual_uncertainties"]
            },
            "interpretation.md": {"constraints": {"non_empty": True, "min_characters": 20}},
            "submission_trace.json": {
                "required_fields": [
                    "workflow_stages",
                    "cuts_applied",
                    "observable_constructed",
                    "fit_model_family_used",
                    "output_files_generated",
                    "reported_result",
                    "baseline_assumptions_used",
                    "object_definition",
                    "derived_observables",
                    "primary_observable",
                    "histogram_definition",
                    "input_files_used",
                    "input_file_count",
                    "selected_events_total",
                    "cutflow_summary",
                ]
            },
        },
    }


def _l1_request(tmp_path: Path | None = None) -> dict:
    data = {
        "work_dir": str(tmp_path / "solver_work") if tmp_path is not None else "",
        "output_dir": str(tmp_path / "solver_work") if tmp_path is not None else "",
        "input_manifest_path": str(tmp_path / "input_manifest.json") if tmp_path is not None else "",
    }
    return {
        "role": "task_request",
        "task_id": "t002_hyy_v5_l1",
        "task_type": "hyy_l1",
        "mode": "call_white",
        "prompt": "Run strict L1 Hyy.",
        "submission_contract": _l1_contract(),
        "data": data,
        "constraints": {"response_format": "submission_bundle_v1", "solver_backend": "agent_2_scifi_oh"},
    }


def _manifest(tmp_path: Path) -> dict:
    root_file = tmp_path / "events.root"
    root_file.write_text("placeholder", encoding="utf-8")
    manifest = {
        "shared_input_dir": str(tmp_path),
        "input_manifest_path": str(tmp_path / "input_manifest.json"),
        "files": [{"logical_name": "events.root", "path": str(root_file), "size_bytes": 11}],
        "read_only_for_solver": True,
    }
    (tmp_path / "input_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _valid_l1_artifacts() -> dict:
    output_names = [
        "diphoton_mass_spectrum.json",
        "diphoton_fit_summary.json",
        "data_minus_background.json",
        "interpretation.md",
        "submission_trace.json",
    ]
    return {
        "diphoton_mass_spectrum.json": {
            "bin_edges": [100.0, 101.0],
            "bin_counts": [1],
            "bin_uncertainties": [1.0],
        },
        "diphoton_fit_summary.json": {
            "signal_model_family": "gaussian",
            "background_model_family": "polynomial",
            "fit_range": [100.0, 160.0],
            "signal_peak_position": 125.0,
        },
        "data_minus_background.json": {
            "bin_centers": [100.5],
            "residual_counts": [0.0],
            "residual_uncertainties": [1.0],
        },
        "interpretation.md": "A computed L1 spectrum reports a modest localized feature near 125 GeV.",
        "submission_trace.json": {
            "workflow_stages": [
                {"stage_id": stage_id, "order_index": idx + 1, "status": "ok"}
                for idx, stage_id in enumerate(L1_STAGE_IDS)
            ],
            "cuts_applied": [
                {"cut_id": cut_id, "value": True, "applied": True}
                for cut_id in sorted(L1_CUT_IDS)
            ],
            "observable_constructed": {"name": "m_yy", "inputs": ["photon_pt", "photon_eta"]},
            "fit_model_family_used": {
                "signal": "gaussian",
                "background": "polynomial",
                "background_order": 4,
                "fit_range_GeV": [100.0, 160.0],
                "weighting_scheme": "inverse_sqrt_bin_count",
            },
            "output_files_generated": output_names,
            "reported_result": {"signal_peak_position": 125.0},
            "baseline_assumptions_used": ["strict L1 test"],
            "object_definition": {
                "type": "photon_pair",
                "multiplicity": 2,
                "ordering_principle": "leading_subleading_photon_pair",
            },
            "derived_observables": [{"name": "m_yy"}],
            "primary_observable": {"name": "m_yy", "inputs": ["photon_pt"], "construction": "test"},
            "histogram_definition": {
                "observable": "m_yy",
                "range": [100.0, 160.0],
                "bin_width": 1.0,
                "uncertainty_model": "sqrt_n_statistical_uncertainty",
            },
            "input_files_used": ["events.root"],
            "input_file_count": 1,
            "selected_events_total": 1,
            "cutflow_summary": {"input_events": 1, "selected_events": 1},
        },
    }


def _bundle(artifacts: dict) -> str:
    return json.dumps({"status": "ok", "artifacts": artifacts})


def test_scifi_oh_backend_registry_accepts_names():
    assert get_solver_backend("agent_2_scifi_oh").name == "agent_2_scifi_oh"
    assert get_solver_backend("scifi_oh").name == "agent_2_scifi_oh"


def test_unsuffixed_scifi_names_are_reserved_for_future_backend():
    with pytest.raises(ValueError, match="Unknown solver_backend 'agent_2_scifi'"):
        get_solver_backend("agent_2_scifi")
    with pytest.raises(ValueError, match="Unknown solver_backend 'scifi'"):
        get_solver_backend("scifi")


def test_scifi_prompt_builder_renders_sam_sections(tmp_path):
    req = _l1_request(tmp_path)
    manifest = _manifest(tmp_path)
    prompt = build_sam_prompt(
        "Base benchmark prompt",
        req,
        manifest,
        attempt=1,
        max_attempts=2,
    )

    assert "## Context" in prompt
    assert "## Todo" in prompt
    assert "## Expect" in prompt
    assert "Base benchmark prompt" in prompt
    assert "submission_bundle_v1" in prompt
    assert "events.root" in prompt
    assert "Hyy L1 Strict Skill" in prompt


def test_scifi_review_accepts_valid_l1_bundle(tmp_path):
    result = review_submission_bundle(_l1_request(tmp_path), _bundle(_valid_l1_artifacts()))

    assert result.passed
    assert result.feedback["retry_instruction"] == "independent review passed; no retry required"


def test_scifi_review_rejects_missing_l1_provenance(tmp_path):
    artifacts = _valid_l1_artifacts()
    artifacts["submission_trace.json"].pop("input_files_used")

    result = review_submission_bundle(_l1_request(tmp_path), _bundle(artifacts))

    assert not result.passed
    assert any("input_files_used" in item for item in result.feedback["schema_or_type_errors"])


def test_scifi_review_rejects_unknown_and_missing_artifacts(tmp_path):
    artifacts = _valid_l1_artifacts()
    artifacts.pop("data_minus_background.json")
    artifacts["extra.json"] = {}

    result = review_submission_bundle(_l1_request(tmp_path), _bundle(artifacts))

    assert not result.passed
    assert result.feedback["missing_required_artifacts"] == ["data_minus_background.json"]
    assert any("undeclared artifact" in item for item in result.feedback["schema_or_type_errors"])


@pytest.mark.asyncio
async def test_scifi_loop_retries_with_feedback(tmp_path):
    req = _l1_request(tmp_path)
    prompts: list[str] = []

    async def status(_: str) -> None:
        return None

    async def worker(prompt: str, attempt: int, total_attempts: int) -> str:
        assert total_attempts == 2
        prompts.append(prompt)
        artifacts = _valid_l1_artifacts()
        if attempt == 1:
            artifacts["submission_trace.json"].pop("input_files_used")
        return _bundle(artifacts)

    loop = SciFiLoop(worker=worker, status=status, max_attempts=2)
    result = await loop.run(
        base_prompt="Base prompt",
        req_json=req,
        input_manifest=None,
        work_dir=tmp_path,
    )

    assert result.review.passed
    assert result.attempts == 2
    assert len(prompts) == 2
    assert "Independent Review Feedback From Previous Attempt" in prompts[1]
    assert "input_files_used" in prompts[1]
    assert json.loads(result.final_text)["status"] == "ok"


@pytest.mark.asyncio
async def test_scifi_oh_backend_retries_invalid_l1_trace(tmp_path, monkeypatch, caplog):
    req = _l1_request(tmp_path)
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("agent_2_scifi_oh")
    calls = {"count": 0}
    statuses: list[str] = []
    caplog.set_level(logging.INFO, logger="solver_backends")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            calls["count"] += 1
            artifacts = _valid_l1_artifacts()
            if calls["count"] == 1:
                artifacts["submission_trace.json"].pop("input_files_used")
            return _bundle(artifacts).encode("utf-8"), b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        assert cmd[0] == "oh"
        return FakeProcess()

    async def status(text: str) -> None:
        statuses.append(text)

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("SCIFI_OH_MAX_RETRIES", "2")

    final_text = await backend.run(
        "Base benchmark prompt",
        req,
        system_prompt="ignored",
        status=status,
        input_manifest=manifest,
        work_dir=work_dir,
    )

    assert calls["count"] == 2
    assert json.loads(final_text)["status"] == "ok"
    status_text = "\n".join(statuses)
    assert "Independent review FAIL" in status_text
    assert "retrying worker with independent review feedback" in status_text
    assert "Independent review PASS" in status_text
    assert str(work_dir / "debug_scifi_oh_output.log") in status_text
    debug_text = (work_dir / "debug_scifi_oh_output.log").read_text(encoding="utf-8")
    assert "--- Worker Executor ---" in debug_text
    assert "openharness" in debug_text
    assert "===== BEGIN debug_scifi_oh_output.log" in caplog.text
    assert "===== END debug_scifi_oh_output.log" in caplog.text
    assert not (work_dir / "debug_oh_output.log").exists()
    assert not (work_dir / "debug_scifi_output.log").exists()


@pytest.mark.asyncio
async def test_scifi_oh_backend_recovers_bundle_from_output_files(tmp_path, monkeypatch):
    req = _l1_request(tmp_path)
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("scifi_oh")
    artifacts = _valid_l1_artifacts()

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            output_dir = work_dir / "artifacts"
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, payload in artifacts.items():
                path = output_dir / name
                if name.endswith(".md"):
                    path.write_text(payload, encoding="utf-8")
                else:
                    path.write_text(json.dumps(payload), encoding="utf-8")
            return b"non-json worker transcript", b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    statuses: list[str] = []

    async def status(text: str) -> None:
        statuses.append(text)

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setenv("SCIFI_OH_MAX_RETRIES", "1")

    final_text = await backend.run(
        "Base benchmark prompt",
        req,
        system_prompt="ignored",
        status=status,
        input_manifest=manifest,
        work_dir=work_dir,
    )

    bundle = json.loads(final_text)
    assert bundle["status"] == "ok"
    assert sorted(bundle["artifacts"]) == sorted(artifacts)
    assert "recovered submission_bundle_v1 from solver output files" in "\n".join(statuses)
