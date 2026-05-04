from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_03a_scifi_native.loop import NativeSciFiLoop as NativeSciFiLoop03A
from agent_03a_scifi_native.native_worker import NativeSciFiWorker as NativeSciFiWorker03A
from agent_03b_scifi_native.loop import NativeSciFiLoop as NativeSciFiLoop03B
from agent_03b_scifi_native.native_worker import NativeSciFiWorker as NativeSciFiWorker03B
from agent_03b_scifi_native.prompt_builder import build_general_sam_prompt
from agent_03c_scifi_native.loop import NativeSciFiLoop as NativeSciFiLoop03C
from agent_03c_scifi_native.native_worker import NativeSciFiWorker as NativeSciFiWorker03C
from agent_03c_scifi_native.prompt_builder import build_v2_sam_prompt
from solver_backends import get_solver_backend


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


def _l1_request(tmp_path: Path) -> dict:
    return {
        "role": "task_request",
        "task_id": "t002_hyy_v5_l1",
        "task_type": "hyy_l1",
        "mode": "call_white",
        "prompt": "Run strict L1 Hyy.",
        "submission_contract": _l1_contract(),
        "data": {
            "work_dir": str(tmp_path / "solver_work"),
            "output_dir": str(tmp_path / "solver_work"),
            "input_manifest_path": str(tmp_path / "input_manifest.json"),
        },
        "constraints": {"response_format": "submission_bundle_v1"},
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


class _FakeFunction:
    def __init__(self, name: str, arguments: dict | str) -> None:
        self.name = name
        self.arguments = arguments if isinstance(arguments, str) else json.dumps(arguments)


class _FakeToolCall:
    type = "function"

    def __init__(self, name: str, arguments: dict | str, call_id: str = "tool-call") -> None:
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    content = ""

    def __init__(self, tool_call: _FakeToolCall) -> None:
        self.tool_calls = [tool_call]


class _FakeChoice:
    def __init__(self, tool_call: _FakeToolCall) -> None:
        self.message = _FakeMessage(tool_call)


class _FakeResponse:
    def __init__(self, tool_call: _FakeToolCall) -> None:
        self.choices = [_FakeChoice(tool_call)]


def test_scifi_native_backend_registry_accepts_names():
    assert get_solver_backend("agent_3a_scifi_native").name == "agent_3a_scifi_native"
    assert get_solver_backend("agent_03a_scifi_native").name == "agent_3a_scifi_native"
    assert get_solver_backend("scifi_native").name == "agent_3a_scifi_native"
    assert get_solver_backend("native_scifi").name == "agent_3a_scifi_native"
    assert get_solver_backend("agent_3b_scifi_native").name == "agent_3b_scifi_native"
    assert get_solver_backend("agent_03b_scifi_native").name == "agent_3b_scifi_native"
    assert get_solver_backend("scifi_native_general").name == "agent_3b_scifi_native"
    assert get_solver_backend("native_scifi_general").name == "agent_3b_scifi_native"
    assert get_solver_backend("agent_3c_scifi_native").name == "agent_3c_scifi_native"
    assert get_solver_backend("agent_03c_scifi_native").name == "agent_3c_scifi_native"
    assert get_solver_backend("scifi_native_v2").name == "agent_3c_scifi_native"
    assert get_solver_backend("native_scifi_v2").name == "agent_3c_scifi_native"


def test_scifi_native_worker_has_no_task_specific_fast_path():
    assert not (SRC_ROOT / "agent_03a_scifi_native" / "hyy_l1_baseline.py").exists()
    assert not (SRC_ROOT / "agent_03b_scifi_native" / "hyy_l1_baseline.py").exists()
    assert not (SRC_ROOT / "agent_03c_scifi_native" / "hyy_l1_baseline.py").exists()
    for worker_class in (NativeSciFiWorker03A, NativeSciFiWorker03B, NativeSciFiWorker03C):
        assert not hasattr(worker_class, "_is_l1_hyy_task")
        assert not hasattr(worker_class, "_try_hyy_l1_baseline_skill")


def test_scifi_native_backends_use_independent_runtime_modules():
    assert NativeSciFiLoop03A.__module__ == "agent_03a_scifi_native.loop"
    assert NativeSciFiWorker03A.__module__ == "agent_03a_scifi_native.native_worker"
    assert NativeSciFiLoop03B.__module__ == "agent_03b_scifi_native.loop"
    assert NativeSciFiWorker03B.__module__ == "agent_03b_scifi_native.native_worker"
    assert NativeSciFiLoop03C.__module__ == "agent_03c_scifi_native.loop"
    assert NativeSciFiWorker03C.__module__ == "agent_03c_scifi_native.native_worker"

    assert get_solver_backend("agent_3a_scifi_native").worker_class is NativeSciFiWorker03A
    assert get_solver_backend("agent_3b_scifi_native").worker_class is NativeSciFiWorker03B
    assert get_solver_backend("agent_3c_scifi_native").worker_class is NativeSciFiWorker03C


@pytest.mark.asyncio
async def test_scifi_native_loop_uses_custom_prompt_builder(tmp_path):
    prompts: list[str] = []

    def prompt_builder(base_prompt, req_json, input_manifest, *, attempt, max_attempts, review_feedback=None):
        del req_json, input_manifest, max_attempts, review_feedback
        return f"custom attempt {attempt}: {base_prompt}"

    async def status(_: str) -> None:
        return None

    async def worker(prompt: str, attempt: int, max_attempts: int) -> str:
        del attempt, max_attempts
        prompts.append(prompt)
        return _bundle(_valid_l1_artifacts())

    loop = NativeSciFiLoop03A(
        worker=worker,
        status=status,
        max_attempts=1,
        prompt_builder=prompt_builder,
        label="test-native-loop",
    )
    result = await loop.run(
        base_prompt="base",
        req_json=_l1_request(tmp_path),
        input_manifest=_manifest(tmp_path),
        work_dir=tmp_path / "solver_work",
    )

    assert result.review.passed
    assert prompts == ["custom attempt 1: base"]


def test_scifi_native_general_prompt_is_contract_driven(tmp_path):
    req = {
        "role": "task_request",
        "task_id": "t999_table_v1",
        "task_type": "table_summary",
        "prompt": "Analyze the provided table and return the contracted artifacts.",
        "submission_contract": {
            "required_outputs": [
                {"canonical_filename": "summary.json", "type": "json"},
                {"canonical_filename": "interpretation.md", "type": "markdown"},
            ]
        },
        "data": {"work_dir": str(tmp_path / "solver_work")},
        "constraints": {"response_format": "submission_bundle_v1"},
    }
    prompt = build_general_sam_prompt(
        req["prompt"],
        req,
        {"files": [{"path": str(tmp_path / "table.csv")}], "read_only_for_solver": True},
        attempt=1,
        max_attempts=2,
    )

    assert "summary.json" in prompt
    assert "submission_bundle_v1" in prompt
    assert "scientific_analysis" in prompt
    assert "Hyy" not in prompt


def test_scifi_native_v2_prompt_uses_dev_branch_sam_style(tmp_path):
    req = {
        "role": "task_request",
        "task_id": "t999_table_v2",
        "task_type": "table_summary",
        "prompt": "Analyze the provided table and return the contracted artifacts.",
        "submission_contract": {
            "required_outputs": [
                {"canonical_filename": "summary.json", "type": "json"},
                {"canonical_filename": "interpretation.md", "type": "markdown"},
            ]
        },
        "data": {"work_dir": str(tmp_path / "solver_work")},
        "constraints": {"response_format": "submission_bundle_v1"},
    }
    prompt = build_v2_sam_prompt(
        req["prompt"],
        req,
        {"files": [{"path": str(tmp_path / "table.csv")}], "read_only_for_solver": True},
        attempt=1,
        max_attempts=2,
    )

    assert "SourceBranch: scifi/dev_max_bench_v2" in prompt
    assert "## Context" in prompt
    assert "## Todo" in prompt
    assert "## Expect" in prompt
    assert "list_shared_envs" in prompt
    assert "summary.json" in prompt
    assert "Hyy" not in prompt


@pytest.mark.asyncio
async def test_scifi_native_backend_retries_without_openharness(tmp_path, monkeypatch):
    req = _l1_request(tmp_path)
    req["constraints"]["solver_backend"] = "agent_3a_scifi_native"
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("scifi_native")
    calls = {"count": 0}
    statuses: list[str] = []

    async def status(text: str) -> None:
        statuses.append(text)

    async def forbidden_subprocess(*args, **kwargs):
        raise AssertionError("native SciFi backend must not call OpenHarness subprocesses")

    class FakeCompletions:
        def create(self, **kwargs):
            del kwargs
            calls["count"] += 1
            artifacts = _valid_l1_artifacts()
            if calls["count"] == 1:
                artifacts["submission_trace.json"].pop("input_files_used")
            return _FakeResponse(
                _FakeToolCall(
                    "done",
                    {"final_json": _bundle(artifacts)},
                    call_id=f"done-{calls['count']}",
                )
            )

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            del kwargs
            self.chat = FakeChat()

    monkeypatch.setattr("solver_backends.asyncio.create_subprocess_exec", forbidden_subprocess)
    monkeypatch.setattr("agent_03a_scifi_native.native_worker.OpenAI", FakeOpenAI)
    monkeypatch.setenv("SCIFI_NATIVE_MAX_RETRIES", "2")

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
    assert "native SciFi worker attempt 1/2" in status_text
    assert "Independent review FAIL" in status_text
    assert "retrying worker with independent review feedback" in status_text
    assert "Independent review PASS" in status_text
    debug_text = (work_dir / "debug_scifi_native_output.log").read_text(encoding="utf-8")
    assert "--- Worker Executor ---" in debug_text
    assert "native_scifi" in debug_text
    assert not (work_dir / "debug_scifi_oh_output.log").exists()


@pytest.mark.asyncio
async def test_scifi_native_general_backend_uses_model_loop(tmp_path, monkeypatch):
    req = _l1_request(tmp_path)
    req["constraints"]["solver_backend"] = "agent_3b_scifi_native"
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("agent_03b_scifi_native")
    calls = {"count": 0}
    statuses: list[str] = []

    async def status(text: str) -> None:
        statuses.append(text)

    class FakeCompletions:
        def create(self, **kwargs):
            del kwargs
            calls["count"] += 1
            return _FakeResponse(_FakeToolCall("done", {"final_json": _bundle(_valid_l1_artifacts())}))

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            del kwargs
            self.chat = FakeChat()

    monkeypatch.setattr("agent_03b_scifi_native.native_worker.OpenAI", FakeOpenAI)
    monkeypatch.setenv("SCIFI_NATIVE_MAX_RETRIES", "1")

    final_text = await backend.run(
        "Base benchmark prompt",
        req,
        system_prompt="ignored",
        status=status,
        input_manifest=manifest,
        work_dir=work_dir,
    )

    assert calls["count"] == 1
    assert json.loads(final_text)["status"] == "ok"
    assert "SciFi-native general loop" in "\n".join(statuses)
    debug_text = (work_dir / "debug_scifi_native_output.log").read_text(encoding="utf-8")
    assert "--- Native Tool Call ---" in debug_text


@pytest.mark.asyncio
async def test_scifi_native_v2_env_tools_without_shell(tmp_path):
    shared_root = tmp_path / "shared_envs"
    env_path = shared_root / "root" / "envs" / "analysis"
    (env_path / "bin").mkdir(parents=True)
    (env_path / ".manifest.json").write_text(
        json.dumps(
            {
                "purpose": "test analysis env",
                "binaries": {"python": "bin/python"},
                "aliases": {"TEST_TOOL": "bin/test-tool"},
            }
        ),
        encoding="utf-8",
    )
    worker = NativeSciFiWorker03C(
        system_prompt="system",
        req_json={},
        input_manifest={},
        work_dir=tmp_path / "work",
        status=lambda _: None,
        enable_scifi_v2_tools=True,
        shared_env_root=shared_root,
    )

    tool_names = {tool["function"]["name"] for tool in worker._tools()}
    assert {"list_shared_envs", "read_env_manifest", "activate_env", "compact"} <= tool_names

    listed = await worker._execute_tool("list_shared_envs", {})
    assert listed["envs"][0]["path"] == str(env_path)

    manifest = await worker._execute_tool("read_env_manifest", {"env_path": str(env_path)})
    assert manifest["manifest"]["aliases"]["TEST_TOOL"] == "bin/test-tool"

    activated = await worker._execute_tool("activate_env", {"env_path": str(env_path)})
    assert activated["active_env"] == str(env_path)
    assert activated["aliases"]["TEST_TOOL"] == "bin/test-tool"

    compacted = await worker._execute_tool("compact", {"text": "x" * 500, "max_chars": 400})
    assert compacted["original_chars"] == 500
    assert "[compact omitted" in compacted["content"]


@pytest.mark.asyncio
async def test_scifi_native_v2_backend_uses_model_loop_and_v2_tools(tmp_path, monkeypatch):
    req = _l1_request(tmp_path)
    req["constraints"]["solver_backend"] = "agent_3c_scifi_native"
    manifest = _manifest(tmp_path)
    work_dir = tmp_path / "solver_work"
    work_dir.mkdir()
    backend = get_solver_backend("agent_03c_scifi_native")
    calls = {"count": 0}
    statuses: list[str] = []

    async def status(text: str) -> None:
        statuses.append(text)

    class FakeCompletions:
        def create(self, **kwargs):
            calls["count"] += 1
            tool_names = {tool["function"]["name"] for tool in kwargs["tools"]}
            assert "list_shared_envs" in tool_names
            if calls["count"] == 1:
                return _FakeResponse(
                    _FakeToolCall("compact", {"text": "x" * 500, "max_chars": 400})
                )
            return _FakeResponse(
                _FakeToolCall("done", {"final_json": _bundle(_valid_l1_artifacts())})
            )

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            del kwargs
            self.chat = FakeChat()

    monkeypatch.setattr("agent_03c_scifi_native.native_worker.OpenAI", FakeOpenAI)
    monkeypatch.setenv("SCIFI_NATIVE_MAX_RETRIES", "1")

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
    assert "SciFi-native v2 loop" in "\n".join(statuses)
    debug_text = (work_dir / "debug_scifi_native_output.log").read_text(encoding="utf-8")
    assert "compact" in debug_text
