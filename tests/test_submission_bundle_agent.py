from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from a2a.utils import new_agent_text_message

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent import PurpleAgent


class DummyUpdater:
    def __init__(self) -> None:
        self.status_updates: list[str] = []
        self.status_messages: list[str] = []
        self.artifacts: list[dict[str, str]] = []

    async def update_status(self, state, message) -> None:
        value = getattr(state, "value", str(state))
        self.status_updates.append(str(value))
        try:
            self.status_messages.append(message.parts[0].root.text)
        except Exception:
            self.status_messages.append("")

    async def add_artifact(self, parts, name: str) -> None:
        text = parts[0].root.text
        self.artifacts.append({"name": name, "text": text})


def _write_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "input_manifest.json"
    shared_input_dir = tmp_path / "shared_input"
    shared_input_dir.mkdir()
    root_file = shared_input_dir / "events.root"
    root_file.write_text("placeholder", encoding="utf-8")
    manifest = {
        "task_id": "t002_hyy_v5_l1",
        "shared_input_dir": str(shared_input_dir),
        "input_manifest_path": str(manifest_path),
        "files": [
            {
                "logical_name": "events.root",
                "path": str(root_file),
                "size_bytes": root_file.stat().st_size,
            }
        ],
        "read_only_for_solver": True,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _bundle_request(manifest_path: Path | str, *, mode: str = "call_white", work_dir: Path | None = None) -> dict:
    data = {
        "release": "2025e-13tev-beta",
        "dataset": "data",
        "skim": "GamGam",
        "shared_input_dir": str(Path(manifest_path).parent / "shared_input"),
        "input_manifest_path": str(manifest_path),
        "read_only_for_solver": True,
    }
    if work_dir is not None:
        data["work_dir"] = str(work_dir)
        data["output_dir"] = str(work_dir)

    return {
        "role": "task_request",
        "task_id": "t002_hyy_v5_l1",
        "task_type": "hyy_l1",
        "mode": mode,
        "prompt": "Solve the task using the provided contract and input manifest.",
        "submission_contract": {
            "required_outputs": [
                {"canonical_filename": "diphoton_mass_spectrum.json", "type": "json"},
                {"canonical_filename": "diphoton_fit_summary.json", "type": "json"},
                {"canonical_filename": "data_minus_background.json", "type": "json"},
                {"canonical_filename": "interpretation.md", "type": "markdown"},
                {"canonical_filename": "submission_trace.json", "type": "json"},
            ]
        },
        "data": data,
        "constraints": {
            "response_format": "submission_bundle_v1",
            "allow_purple_network": False,
        },
    }


@pytest.mark.asyncio
async def test_submission_bundle_mock_mode_returns_minimal_bundle(tmp_path):
    manifest_path = _write_manifest(tmp_path)
    payload = _bundle_request(manifest_path, mode="mock")
    updater = DummyUpdater()

    await PurpleAgent().run(new_agent_text_message(json.dumps(payload)), updater)

    assert updater.status_updates[-1] == "completed"
    bundle = json.loads(updater.artifacts[-1]["text"])
    assert bundle["status"] == "ok"
    assert "submission_trace.json" in bundle["artifacts"]
    assert "interpretation.md" in bundle["artifacts"]


@pytest.mark.asyncio
async def test_submission_bundle_call_white_augments_prompt_and_preserves_oh_invocation(tmp_path, monkeypatch):
    manifest_path = _write_manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    payload = _bundle_request(manifest_path, mode="call_white", work_dir=work_dir)
    updater = DummyUpdater()
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            response = {
                "status": "ok",
                "artifacts": {
                    "diphoton_mass_spectrum.json": {"bin_edges": [100, 101], "bin_counts": [1], "bin_uncertainties": [1]},
                    "diphoton_fit_summary.json": {
                        "signal_model_family": "gaussian",
                        "background_model_family": "polynomial",
                        "fit_range": [100, 160],
                        "signal_peak_position": 125.0,
                    },
                    "data_minus_background.json": {
                        "bin_centers": [125],
                        "residual_counts": [1],
                        "residual_uncertainties": [1],
                    },
                    "interpretation.md": "A small Higgs-like excess is visible near 125 GeV.",
                    "submission_trace.json": {
                        "workflow_stages": [],
                        "cuts_applied": [],
                        "observable_constructed": {"name": "m_yy", "inputs": ["events.root"]},
                        "fit_model_family_used": {
                            "signal": "gaussian",
                            "background": "polynomial",
                            "background_order": 4,
                            "fit_range_GeV": [100, 160],
                            "weighting_scheme": "sqrtN",
                        },
                        "output_files_generated": [
                            "diphoton_mass_spectrum.json",
                            "diphoton_fit_summary.json",
                            "data_minus_background.json",
                            "interpretation.md",
                            "submission_trace.json",
                        ],
                        "reported_result": {"signal_peak_position": 125.0},
                        "baseline_assumptions_used": ["test"],
                        "object_definition": {"type": "diphoton", "multiplicity": 2, "ordering_principle": "leading_pt"},
                        "derived_observables": [{"name": "m_yy"}],
                        "primary_observable": {"name": "m_yy", "inputs": ["events.root"], "construction": "test"},
                        "histogram_definition": {
                            "observable": "m_yy",
                            "range": [100, 160],
                            "bin_width": 1.0,
                            "uncertainty_model": "sqrtN",
                        },
                    },
                },
            }
            return json.dumps(response).encode("utf-8"), b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    await PurpleAgent().run(new_agent_text_message(json.dumps(payload)), updater)

    cmd = captured["cmd"]
    assert cmd[:6] == (
        "oh",
        "--permission-mode",
        "full_auto",
        "--dangerously-skip-permissions",
        "--system-prompt",
        PurpleAgent().system_prompt,
    )
    prompt = cmd[-1]
    assert "submission_contract JSON" in prompt
    assert "Resolved input_manifest JSON" in prompt
    assert "Working directory requirements" in prompt
    assert "- solver_backend: agent_1_oh" in prompt
    assert "events.root" in prompt
    assert "Do not wrap the final JSON in markdown fences." in prompt
    assert captured["kwargs"]["cwd"] == str(work_dir)
    assert captured["kwargs"]["env"]["HEPEX_SOLVER_WORK_DIR"] == str(work_dir)
    assert captured["kwargs"]["env"]["HEPEX_OUTPUT_DIR"] == str(work_dir)
    assert work_dir.is_dir()
    status_text = "\n".join(updater.status_messages)
    assert "Task request: task_id=t002_hyy_v5_l1" in status_text
    assert "solver_backend=agent_1_oh" in status_text
    assert "Input manifest: 1 file(s)" in status_text
    assert "Submission contract: 5 required output(s)" in status_text
    assert "Solver backend agent_1_oh: starting OpenHarness attempt 1/5" in status_text
    assert "OpenHarness attempt 1/5 finished: exit=0" in status_text
    assert "Solver response: status=ok, 5 artifact(s)" in status_text
    assert str(work_dir / "debug_oh_output.log") in status_text

    bundle = json.loads(updater.artifacts[-1]["text"])
    assert updater.status_updates[-1] == "completed"
    assert bundle["status"] == "ok"
    assert "diphoton_fit_summary.json" in bundle["artifacts"]


@pytest.mark.asyncio
async def test_submission_bundle_call_white_recovers_from_solver_output_files(tmp_path, monkeypatch):
    manifest_path = _write_manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    payload = _bundle_request(manifest_path, mode="call_white", work_dir=work_dir)
    updater = DummyUpdater()

    artifacts = {
        "diphoton_mass_spectrum.json": {
            "bin_edges": [100, 101],
            "bin_counts": [1],
            "bin_uncertainties": [1],
        },
        "diphoton_fit_summary.json": {
            "signal_model_family": "gaussian",
            "background_model_family": "polynomial",
            "fit_range": [100, 160],
            "signal_peak_position": 125.0,
        },
        "data_minus_background.json": {
            "bin_centers": [125],
            "residual_counts": [1],
            "residual_uncertainties": [1],
        },
        "interpretation.md": "Recovered from solver output files.",
        "submission_trace.json": {
            "workflow_stages": [],
            "cuts_applied": [],
            "observable_constructed": {"name": "m_yy", "inputs": ["events.root"]},
            "fit_model_family_used": {"signal": "gaussian", "background": "polynomial"},
            "output_files_generated": [
                "diphoton_mass_spectrum.json",
                "diphoton_fit_summary.json",
                "data_minus_background.json",
                "interpretation.md",
                "submission_trace.json",
            ],
            "reported_result": {"signal_peak_position": 125.0},
            "baseline_assumptions_used": ["test"],
            "object_definition": {"type": "diphoton"},
            "derived_observables": [{"name": "m_yy"}],
            "primary_observable": {"name": "m_yy"},
            "histogram_definition": {"observable": "m_yy"},
            "input_files_used": ["events.root"],
            "input_file_count": 1,
            "selected_events_total": 1,
            "cutflow_summary": {"input_events": 1, "selected_events": 1},
        },
    }

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            output_dir = work_dir / "artifacts"
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, payload in artifacts.items():
                path = output_dir / name
                if name.endswith(".md"):
                    path.write_text(str(payload), encoding="utf-8")
                else:
                    path.write_text(json.dumps(payload), encoding="utf-8")
            return b'{"status":"ok","artifacts":{', b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    await PurpleAgent().run(new_agent_text_message(json.dumps(payload)), updater)

    status_text = "\n".join(updater.status_messages)
    assert "recovered submission_bundle_v1 from solver output files" in status_text

    bundle = json.loads(updater.artifacts[-1]["text"])
    assert updater.status_updates[-1] == "completed"
    assert bundle["status"] == "ok"
    assert sorted(bundle["artifacts"].keys()) == sorted(artifacts.keys())
    assert bundle["artifacts"]["interpretation.md"] == "Recovered from solver output files."


@pytest.mark.asyncio
async def test_submission_bundle_call_white_retries_empty_timeout_response(tmp_path, monkeypatch):
    manifest_path = _write_manifest(tmp_path)
    payload = _bundle_request(manifest_path, mode="call_white", work_dir=tmp_path / "solver_work")
    updater = DummyUpdater()
    calls = {"count": 0}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            calls["count"] += 1
            if calls["count"] == 1:
                return b"", b"API error: Request timed out."
            return b'{"status":"ok","artifacts":{"interpretation.md":"ok"}}', b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return FakeProcess()

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("solver_backends.asyncio.sleep", fake_sleep)

    await PurpleAgent().run(new_agent_text_message(json.dumps(payload)), updater)

    assert calls["count"] == 2
    status_text = "\n".join(updater.status_messages)
    assert "retryable OpenHarness error on attempt 1/5" in status_text
    assert "starting OpenHarness attempt 2/5" in status_text
    bundle = json.loads(updater.artifacts[-1]["text"])
    assert bundle["status"] == "ok"


@pytest.mark.asyncio
async def test_submission_bundle_mock_mode_requires_manifest_path(tmp_path):
    payload = _bundle_request(tmp_path / "missing.json", mode="mock")
    payload["data"]["input_manifest_path"] = ""
    updater = DummyUpdater()

    await PurpleAgent().run(new_agent_text_message(json.dumps(payload)), updater)

    bundle = json.loads(updater.artifacts[-1]["text"])
    assert updater.status_updates[-1] == "completed"
    assert bundle["status"] == "error"
    assert "input_manifest_path" in bundle["error"]
