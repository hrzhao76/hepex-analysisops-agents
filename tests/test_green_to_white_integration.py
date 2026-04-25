"""
Integration test: Green Agent (Judge) -> White Agent (Solver)

This test script simulates the full benchmark flow:
1. Green agent receives an EvalRequest
2. Green agent prepares data and sends task to white agent
3. White agent processes the task using tools
4. Green agent receives response and grades it

Prerequisites:
- White agent server running on port 9009 (src/server.py in hepex-analysisops-agents)
- Green agent server running on port 9010 (src/server.py in hepex-analysisops-benchmark)
  OR use the test fixtures to auto-start

Usage:
    # Start white agent first:
    cd /home/ranriver/Projects/hepex-analysisops-agents/src && python server.py --port 9009
    
    # Then run this test:
    pytest tests/test_green_to_white_integration.py -v --white-agent-url=http://localhost:9009
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart, Task


# --------------------------------------------------------------------------
# Pytest fixtures and options
# --------------------------------------------------------------------------

# Note: Uses 'agent' fixture from conftest.py (--agent-url option)
# The 'agent' fixture is already defined in conftest.py

@pytest.fixture(scope="session")
def white_agent(agent):
    """Alias for the agent fixture - white agent URL."""
    return agent


@pytest.fixture(scope="session")
def benchmark_dir() -> Path:
    """Locate the benchmark directory."""
    # Auto-detect: look for sibling directory or submodule
    candidates = [
        Path(__file__).parent.parent / "hepex-analysisops-benchmark",
        Path(__file__).parent.parent.parent / "hepex-analysisops-benchmark",
    ]
    for c in candidates:
        if (c / "src" / "agent.py").exists():
            return c
    
    pytest.skip("Could not find hepex-analysisops-benchmark directory")


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    """Temporary data directory for tests."""
    return tmp_path_factory.mktemp("integration_test_data")


# --------------------------------------------------------------------------
# A2A messaging helpers
# --------------------------------------------------------------------------

async def send_eval_request(
    eval_request: dict,
    green_agent_url: str,
    timeout: int = 300,
) -> tuple[str, str, list]:
    """
    Send an EvalRequest to the green agent.
    Returns: (response_text, status, events)
    """
    message_str = json.dumps(eval_request)
    
    async with httpx.AsyncClient(timeout=timeout) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=green_agent_url)
        agent_card = await resolver.get_agent_card()
        config = ClientConfig(httpx_client=httpx_client, streaming=False)
        factory = ClientFactory(config)
        client = factory.create(agent_card)
        
        msg = Message(
            kind="message",
            role=Role.user,
            parts=[Part(TextPart(text=message_str))],
            message_id=uuid4().hex,
            context_id=None,
        )
        
        events = [event async for event in client.send_message(msg)]
    
    # Extract response
    response_text = ""
    status = "unknown"
    
    for event in events:
        if isinstance(event, tuple) and len(event) == 2:
            task, update = event
            if isinstance(task, Task):
                try:
                    status = task.status.state.value
                except Exception:
                    pass
                
                # Extract from artifacts
                if task.artifacts:
                    for artifact in task.artifacts:
                        for p in artifact.parts:
                            root = getattr(p, "root", None)
                            if root and hasattr(root, "text"):
                                response_text += root.text + "\n"
                            if root and hasattr(root, "data"):
                                response_text += json.dumps(root.data, indent=2) + "\n"
    
    return response_text, status, events


async def send_task_to_white_agent(
    payload: dict,
    white_agent_url: str,
    timeout: int = 300,
) -> tuple[str, str]:
    """
    Send a task payload directly to the white agent.
    Returns: (response_text, status)
    """
    message_str = json.dumps(payload, indent=2)
    
    async with httpx.AsyncClient(timeout=timeout) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=white_agent_url)
        agent_card = await resolver.get_agent_card()
        config = ClientConfig(httpx_client=httpx_client, streaming=False)
        factory = ClientFactory(config)
        client = factory.create(agent_card)
        
        msg = Message(
            kind="message",
            role=Role.user,
            parts=[Part(TextPart(text=message_str))],
            message_id=uuid4().hex,
            context_id=None,
        )
        
        events = [event async for event in client.send_message(msg)]
    
    # Extract response
    response_chunks = []
    status = "unknown"
    
    for event in events:
        if isinstance(event, tuple) and len(event) == 2:
            task, update = event
            if isinstance(task, Task):
                try:
                    status = task.status.state.value
                except Exception:
                    pass
                
                if task.artifacts:
                    for artifact in task.artifacts:
                        for p in artifact.parts:
                            root = getattr(p, "root", None)
                            if root and hasattr(root, "text"):
                                text = root.text
                                if text not in ["Running analysis agent...", "Done."]:
                                    response_chunks.append(text)
    
    return "\n".join(response_chunks), status


def extract_json_from_response(response_text: str) -> dict | None:
    """Extract JSON from response text, handling markdown code blocks."""
    text = response_text.strip()
    
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try extracting from markdown code block (```json ... ```)
    if "```json" in text:
        start = text.find("```json") + 7
        # Skip any whitespace/newline after ```json
        while start < len(text) and text[start] in " \t\n\r":
            start += 1
        # Find the closing ``` - need to handle nested content
        end = text.find("\n```", start)
        if end == -1:
            end = text.find("```", start)
        if end > start:
            json_str = text[start:end].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
    
    # Try generic code block (``` ... ```)
    if "```" in text:
        first_fence = text.find("```")
        # Skip to end of first line (language identifier)
        newline_after = text.find("\n", first_fence + 3)
        if newline_after > first_fence:
            start = newline_after + 1
            # Find closing fence
            end = text.find("\n```", start)
            if end == -1:
                end = text.find("```", start)
            if end > start:
                json_str = text[start:end].strip()
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
    
    # Try finding JSON object in text by matching braces
    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i, char in enumerate(text[brace_start:], brace_start):
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
    
    return None


# --------------------------------------------------------------------------
# Build payloads mimicking green agent behavior
# --------------------------------------------------------------------------

def build_zpeak_task_payload(
    task_id: str = "t001_zpeak_fit",
    files: list[str] | None = None,
    release: str = "2025e-13tev-beta",
    dataset: str = "data",
    skim: str = "2muons",
    max_files: int = 1,
) -> dict:
    """Build a Z-peak fit task payload as the green agent would."""
    
    prompt = """You are a physics analysis agent. Solve the task: **Z→μμ mass-peak fit**.
If you need, you may inspect the file schema (trees/branches). Record chosen tree and branches in comments.

Goal
- Build the di-muon invariant mass spectrum (m_mumu) from the provided ROOT file.
- Fit around the Z resonance and report the fitted peak position (mu) and width (sigma).

Data & environment
- You will receive a list of local ROOT file paths.
- Use at most 1 file.
- You may inspect the ROOT schema (trees/branches) if needed.

Analysis requirements
- Define how you select the muon pair (e.g., exactly 2 muons, or take two leading-pt muons). State your choice.
- Sanity check units: the Z peak should be around 91 GeV. If values look like ~91000, treat as MeV and convert to GeV.
- Fit in a reasonable window around the Z peak (e.g., 70–110 GeV) with a simple model (e.g., Gaussian with/without a smooth background). State your model and why.

Output format (SUBMISSION_TRACE JSON)
Return a JSON object with:

{
  "task_id": "{{TASK_ID}}",
  "status": "ok" | "error",
  "fit_result": {
    "mu": number,
    "sigma": number,
    "gof": {
      "p_value": number,
      "chi2_ndof": number
    }
  },
  "fit_method": {
    "model": string,
    "fit_range": [number, number],
    "binned_or_unbinned": "binned" | "unbinned",
    "optimizer": string,
    "initial_params": object,
    "uncertainties_method": string
  },
  "comments": string
}

Guidance
- Briefly justify the fit model and fit range.
- If you cannot complete, set status="error" and explain in "comments".
- Output JSON only.
"""

    if files is None:
        files = [
            "/home/ranriver/Projects/hepex-analysisops-agents/data/2025e-13tev-beta/data/2muons/ODEO_FEB2025_v0_2muons_data15_periodD.2muons.root"
        ]

    payload = {
        "role": "task_request",
        "task_id": task_id,
        "task_type": "zpeak_fit",
        "prompt": prompt.replace("{{TASK_ID}}", task_id),
        "data": {
            "files": files[:max_files],
            "release": release,
            "dataset": dataset,
            "skim": skim,
        },
        "constraints": {
            "time_limit_sec": 600,
            "memory_gb": 8,
            "allow_network": False,
        },
    }

    return payload


# --------------------------------------------------------------------------
# Evaluation helpers (mimicking green agent's rubric evaluation)
# --------------------------------------------------------------------------

def evaluate_zpeak_response(submission: dict, eval_ref: dict | None = None) -> dict:
    """
    Simple evaluation of Z-peak fit response.
    Mimics the green agent's evaluation but simplified for testing.
    """
    result = {
        "status": "ok",
        "score": 0.0,
        "max_score": 100.0,
        "checks": [],
    }
    
    if eval_ref is None:
        eval_ref = {
            "fit_expectations": {
                "mu_target": 91.2,
                "mu_tolerance": 0.5,
                "sigma_range": [1.5, 4.0],
                "min_p_value": 0.01,
            }
        }
    
    # Gate check: required fields
    required = ["status", "fit_result", "fit_method"]
    missing = [f for f in required if f not in submission]
    if missing:
        result["status"] = "fail"
        result["checks"].append({
            "id": "required_fields",
            "passed": False,
            "message": f"Missing required fields: {missing}",
        })
        return result
    
    result["checks"].append({
        "id": "required_fields",
        "passed": True,
        "message": "All required fields present",
    })
    
    if submission.get("status") != "ok":
        result["status"] = "fail"
        result["checks"].append({
            "id": "status_ok",
            "passed": False,
            "message": f"Submission status is '{submission.get('status')}', not 'ok'",
        })
        return result
    
    fit = submission.get("fit_result", {})
    expectations = eval_ref.get("fit_expectations", {})
    
    # Check mu value
    mu = fit.get("mu")
    if mu is not None:
        mu_target = expectations.get("mu_target", 91.2)
        mu_tolerance = expectations.get("mu_tolerance", 0.5)
        
        if abs(mu - mu_target) <= mu_tolerance:
            result["score"] += 40
            result["checks"].append({
                "id": "mu_closeness",
                "passed": True,
                "score": 40,
                "message": f"mu={mu:.3f} within {mu_tolerance} of target {mu_target}",
            })
        else:
            # Partial credit based on distance
            distance = abs(mu - mu_target)
            partial = max(0, 40 * (1 - distance / (3 * mu_tolerance)))
            result["score"] += partial
            result["checks"].append({
                "id": "mu_closeness",
                "passed": False,
                "score": partial,
                "message": f"mu={mu:.3f} is {distance:.3f} from target {mu_target}",
            })
    
    # Check sigma value
    sigma = fit.get("sigma")
    if sigma is not None:
        sigma_range = expectations.get("sigma_range", [1.5, 4.0])
        if sigma_range[0] <= sigma <= sigma_range[1]:
            result["score"] += 20
            result["checks"].append({
                "id": "sigma_range",
                "passed": True,
                "score": 20,
                "message": f"sigma={sigma:.3f} within range {sigma_range}",
            })
        else:
            result["score"] += 5  # partial credit
            result["checks"].append({
                "id": "sigma_range",
                "passed": False,
                "score": 5,
                "message": f"sigma={sigma:.3f} outside range {sigma_range}",
            })
    
    # Check p-value
    gof = fit.get("gof", {})
    p_value = gof.get("p_value")
    if p_value is not None:
        min_p = expectations.get("min_p_value", 0.01)
        if p_value >= min_p:
            result["score"] += 20
            result["checks"].append({
                "id": "pvalue",
                "passed": True,
                "score": 20,
                "message": f"p_value={p_value:.4f} >= {min_p}",
            })
        else:
            result["score"] += 10
            result["checks"].append({
                "id": "pvalue",
                "passed": False,
                "score": 10,
                "message": f"p_value={p_value:.4f} < {min_p}",
            })
    else:
        result["score"] += 10  # partial for missing
        result["checks"].append({
            "id": "pvalue",
            "passed": False,
            "score": 10,
            "message": "p_value not provided",
        })
    
    # Check fit_method metadata
    method = submission.get("fit_method", {})
    required_method_keys = ["model", "fit_range"]
    present = [k for k in required_method_keys if k in method]
    if len(present) == len(required_method_keys):
        result["score"] += 20
        result["checks"].append({
            "id": "method_metadata",
            "passed": True,
            "score": 20,
            "message": "fit_method contains required keys",
        })
    else:
        missing = [k for k in required_method_keys if k not in method]
        partial = 20 - 5 * len(missing)
        result["score"] += max(0, partial)
        result["checks"].append({
            "id": "method_metadata",
            "passed": False,
            "score": max(0, partial),
            "message": f"fit_method missing keys: {missing}",
        })
    
    result["normalized_score"] = result["score"] / result["max_score"]
    return result


# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_white_agent_zpeak_direct(white_agent):
    """
    Test direct communication with white agent for Z-peak fitting.
    This mimics what the green agent does when calling the white agent.
    """
    payload = build_zpeak_task_payload()
    
    response_text, status = await send_task_to_white_agent(payload, white_agent)
    
    assert status in ("completed", "ok"), f"Task failed with status: {status}"
    assert response_text.strip(), "Empty response from white agent"
    
    # Parse the response
    submission = extract_json_from_response(response_text)
    assert submission is not None, f"Could not parse JSON from response:\n{response_text[:500]}"
    
    # Basic validation
    assert "status" in submission, f"Missing 'status' in submission: {submission}"
    assert "task_id" in submission or submission.get("status") == "error", \
        f"Missing 'task_id' in successful submission: {submission}"


@pytest.mark.asyncio
async def test_white_agent_zpeak_with_evaluation(white_agent):
    """
    Test white agent response and evaluate it using rubric-like checks.
    """
    payload = build_zpeak_task_payload(task_id="eval_test_001")
    
    response_text, status = await send_task_to_white_agent(payload, white_agent)
    
    assert status in ("completed", "ok"), f"Task failed with status: {status}"
    
    submission = extract_json_from_response(response_text)
    assert submission is not None, f"Could not parse JSON:\n{response_text[:500]}"
    
    # Evaluate the submission
    eval_result = evaluate_zpeak_response(submission)
    
    print(f"\n=== Evaluation Result ===")
    print(f"Status: {eval_result['status']}")
    print(f"Score: {eval_result['score']}/{eval_result['max_score']}")
    print(f"Normalized: {eval_result.get('normalized_score', 0):.3f}")
    for check in eval_result["checks"]:
        status_str = "✓" if check["passed"] else "✗"
        print(f"  {status_str} {check['id']}: {check['message']}")
    
    # Basic assertions
    assert eval_result["status"] in ("ok", "fail"), f"Unexpected eval status: {eval_result['status']}"
    assert eval_result["score"] >= 0, "Score should be non-negative"


@pytest.mark.asyncio
async def test_white_agent_fit_quality(white_agent):
    """
    Test that white agent produces reasonable fit results.
    """
    payload = build_zpeak_task_payload(task_id="fit_quality_test")
    
    response_text, status = await send_task_to_white_agent(payload, white_agent)
    submission = extract_json_from_response(response_text)
    
    assert submission is not None, "Could not parse response"
    
    if submission.get("status") == "ok":
        fit = submission.get("fit_result", {})
        
        # Check mu is near Z mass
        mu = fit.get("mu")
        assert mu is not None, "fit_result should contain 'mu'"
        assert 85 < mu < 97, f"mu={mu} is far from Z mass (~91 GeV)"
        
        # Check sigma is reasonable
        sigma = fit.get("sigma")
        assert sigma is not None, "fit_result should contain 'sigma'"
        assert 1 < sigma < 8, f"sigma={sigma} seems unreasonable"
        
        # Check fit_method
        method = submission.get("fit_method", {})
        assert "model" in method, "fit_method should describe the model"
        assert "fit_range" in method, "fit_method should describe fit_range"


@pytest.mark.asyncio
async def test_full_green_to_white_flow_simulation(white_agent, data_dir):
    """
    Simulate the full flow: prepare task -> send to white -> evaluate.
    This is what happens inside the green agent's run() method.
    """
    # Step 1: Prepare task (as green agent would)
    task_id = "flow_sim_001"
    
    # Check if data file exists
    data_file = Path("/home/ranriver/Projects/hepex-analysisops-agents/data/2025e-13tev-beta/data/2muons/ODEO_FEB2025_v0_2muons_data15_periodD.2muons.root")
    
    if not data_file.exists():
        pytest.skip(f"Data file not found: {data_file}")
    
    # Step 2: Build payload (as green agent would)
    payload = build_zpeak_task_payload(
        task_id=task_id,
        files=[str(data_file)],
    )
    
    # Step 3: Send to white agent
    print(f"\n[Flow] Sending task {task_id} to white agent...")
    response_text, status = await send_task_to_white_agent(payload, white_agent)
    
    assert status in ("completed", "ok"), f"White agent failed: {status}"
    
    # Step 4: Parse response (as green agent would)
    submission = extract_json_from_response(response_text)
    assert submission is not None, "Failed to parse white agent response"
    
    print(f"[Flow] Received submission with status: {submission.get('status')}")
    
    # Step 5: Evaluate (as green agent would)
    eval_result = evaluate_zpeak_response(submission)
    
    print(f"[Flow] Evaluation complete: {eval_result['score']}/{eval_result['max_score']}")
    
    # Step 6: Save artifacts (as green agent would)
    run_dir = data_dir / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    (run_dir / "submission_trace.json").write_text(
        json.dumps(submission, indent=2)
    )
    (run_dir / "judge_output.json").write_text(
        json.dumps(eval_result, indent=2)
    )
    
    print(f"[Flow] Artifacts saved to: {run_dir}")
    
    # Verify artifacts exist
    assert (run_dir / "submission_trace.json").exists()
    assert (run_dir / "judge_output.json").exists()


# @pytest.mark.asyncio
# async def test_multiple_tasks_sequential(white_agent):
#     """
#     Test running multiple tasks sequentially (as green agent batch would).
#     """
#     tasks = [
#         ("batch_task_001", "zpeak_fit"),
#         ("batch_task_002", "zpeak_fit"),
#     ]
    
#     results = []
    
#     for task_id, task_type in tasks:
#         payload = build_zpeak_task_payload(task_id=task_id)
        
#         response_text, status = await send_task_to_white_agent(payload, white_agent)
#         submission = extract_json_from_response(response_text)
        
#         if submission:
#             eval_result = evaluate_zpeak_response(submission)
#             results.append({
#                 "task_id": task_id,
#                 "submission_status": submission.get("status"),
#                 "eval_score": eval_result["score"],
#                 "eval_status": eval_result["status"],
#             })
#         else:
#             results.append({
#                 "task_id": task_id,
#                 "submission_status": "parse_error",
#                 "eval_score": 0,
#                 "eval_status": "error",
#             })
    
#     print("\n=== Batch Results ===")
#     total_score = 0
#     for r in results:
#         print(f"  {r['task_id']}: {r['eval_score']:.1f} ({r['eval_status']})")
#         total_score += r["eval_score"]
#     print(f"  Total: {total_score:.1f}")
    
#     # At least some tasks should complete
#     completed = [r for r in results if r["submission_status"] == "ok"]
#     assert len(completed) > 0, "No tasks completed successfully"


@pytest.mark.asyncio
async def test_error_handling_missing_file(white_agent):
    """
    Test how white agent handles missing data files.
    """
    payload = build_zpeak_task_payload(
        task_id="error_test_001",
        files=["/nonexistent/path/to/missing.root"],
    )
    
    response_text, status = await send_task_to_white_agent(payload, white_agent)
    submission = extract_json_from_response(response_text)
    
    # Agent should either return error status or handle gracefully
    if submission:
        if submission.get("status") == "error":
            assert "comments" in submission or "error" in submission, \
                "Error response should explain the issue"
            print(f"[Expected] Agent returned error: {submission.get('comments', submission.get('error'))}")
        # If ok, the agent somehow worked around missing file (unexpected but possible)


# --------------------------------------------------------------------------
# Entry point for manual testing
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("Running integration tests manually...")
        white_url = "http://localhost:9009"
        
        # Check white agent is up
        try:
            resp = httpx.get(f"{white_url}/.well-known/agent-card.json", timeout=5)
            print(f"White agent is running at {white_url}")
        except Exception as e:
            print(f"ERROR: White agent not reachable at {white_url}: {e}")
            return
        
        # Run a simple test
        print("\n--- Test: Direct Z-peak fit ---")
        payload = build_zpeak_task_payload(task_id="manual_test_001")
        response_text, status = await send_task_to_white_agent(payload, white_url)
        
        print(f"Status: {status}")
        submission = extract_json_from_response(response_text)
        
        if submission:
            print(f"Submission status: {submission.get('status')}")
            if submission.get("fit_result"):
                fit = submission["fit_result"]
                print(f"  mu = {fit.get('mu')}")
                print(f"  sigma = {fit.get('sigma')}")
            
            eval_result = evaluate_zpeak_response(submission)
            print(f"\nEvaluation: {eval_result['score']}/{eval_result['max_score']}")
        else:
            print("Failed to parse response")
            print(f"Raw response:\n{response_text[:500]}")
    
    asyncio.run(main())
