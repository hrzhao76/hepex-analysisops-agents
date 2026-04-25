"""
Test suite for WhiteAgent tool calling behavior.
Mimics the behavior of a green agent passing a payload to the white agent.
"""

import json
import pytest
import httpx
from uuid import uuid4

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart, Task


# --------------------------------------------------------------------------
# Payload construction helpers (mimicking green agent behavior)
# --------------------------------------------------------------------------

def build_zpeak_task_payload(
    task_id: str = "z_peak_fit_001",
    task_type: str = "z_peak_fit",
    files: list[str] | None = None,
    release: str = "2025e-13tev-beta",
    dataset: str = "data15_periodD",
    skim: str = "2muons",
    max_files: int = 1,
) -> dict:
    """
    Build a task payload mimicking green agent behavior.
    """
    if files is None:
        files = [
            "/home/ranriver/Projects/hepex-analysisops-agents/data/2025e-13tev-beta/data/2muons/ODEO_FEB2025_v0_2muons_data15_periodD.2muons.root"
        ]

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

    payload = {
        "role": "task_request",
        "task_id": task_id,
        "task_type": task_type,
        "prompt": prompt.replace("{{TASK_ID}}", task_id),
        "data": {
            "files": files[:max_files],
            "release": release,
            "dataset": dataset,
            "skim": skim,
        },
        "constraints": {},
    }

    return payload


# --------------------------------------------------------------------------
# A2A messaging helpers
# --------------------------------------------------------------------------

async def send_task_payload(payload: dict, url: str, streaming: bool = False):
    """
    Send a task payload to the agent and return all events.
    """
    message_str = json.dumps(payload, indent=2)

    async with httpx.AsyncClient(timeout=300) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=url)
        agent_card = await resolver.get_agent_card()
        config = ClientConfig(httpx_client=httpx_client, streaming=streaming)
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

    return events


def _extract_text_from_parts(parts):
    """Helper to extract text from a list of Part objects."""
    texts = []
    for p in parts:
        root = getattr(p, "root", None)
        if root:
            if getattr(root, "kind", None) == "text":
                texts.append(root.text)
            elif hasattr(root, "text"):
                texts.append(root.text)
    return texts


def extract_response_and_status(outputs):
    """
    Extract response text and status from A2A outputs.
    Returns: (response_text, status, debug_str)
    """
    response_chunks = []
    status = None
    debug_str = repr(outputs)

    def process_task(task):
        nonlocal status
        try:
            status = task.status.state.value
        except Exception:
            pass

        # Extract from artifacts
        try:
            if task.artifacts:
                for artifact in task.artifacts:
                    response_chunks.extend(_extract_text_from_parts(artifact.parts))
        except Exception:
            pass

        # Check history for agent messages
        try:
            if task.history:
                for msg in task.history:
                    if msg.role.value == "agent" and msg.parts:
                        for p in msg.parts:
                            root = getattr(p, "root", None)
                            if root and hasattr(root, "text"):
                                text = root.text
                                if text not in ["Running analysis agent...", "Done."]:
                                    response_chunks.append(text)
        except Exception:
            pass

    if isinstance(outputs, (list, tuple)):
        for item in outputs:
            if item is None:
                continue
            if isinstance(item, Task):
                process_task(item)
            elif isinstance(item, tuple) and len(item) == 2:
                task, update = item
                if isinstance(task, Task):
                    process_task(task)
                if update is not None:
                    try:
                        if hasattr(update, "artifact") and update.artifact:
                            response_chunks.extend(_extract_text_from_parts(update.artifact.parts))
                    except Exception:
                        pass
            elif isinstance(item, Message):
                if item.role.value == "agent" and item.parts:
                    texts = _extract_text_from_parts(item.parts)
                    for t in texts:
                        if t not in ["Running analysis agent...", "Done."]:
                            response_chunks.append(t)

    return "\n".join([c for c in response_chunks if c]), status or "unknown", debug_str


def extract_json_from_response(response_text: str) -> dict | None:
    """
    Try to extract JSON from response text.
    Handles cases where JSON might be wrapped in markdown code blocks.
    """
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

    # Try extracting from generic code block
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

    # Try finding JSON object in text by matching braces (handling strings properly)
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
                        return json.loads(text[brace_start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break

    return None


# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zpeak_tool_calling_basic(agent):
    """
    Test that the agent can process a Z-peak fit task and call the appropriate tools.
    This mimics the green agent's task_request payload format.
    """
    payload = build_zpeak_task_payload(task_id="test_zpeak_001")

    outputs = await send_task_payload(payload, agent, streaming=False)

    resp, status, debug = extract_response_and_status(outputs)

    # Basic assertions
    assert outputs, "Agent should respond with at least one event"
    assert status in ("completed", "ok"), f"Task not completed. status={status}\noutputs={debug}"
    assert resp.strip(), f"Empty response. outputs={debug}"

    # Try to parse JSON response
    parsed = extract_json_from_response(resp)
    assert parsed is not None, f"Could not parse JSON from response:\n{resp[:500]}"

    # Validate expected fields
    assert "status" in parsed, f"Missing 'status' field in response: {parsed}"
    assert "task_id" in parsed or parsed.get("status") == "error", f"Missing 'task_id' in successful response: {parsed}"


@pytest.mark.asyncio
async def test_zpeak_fit_result_structure(agent):
    """
    Test that the agent returns a properly structured fit result for Z-peak fitting.
    """
    payload = build_zpeak_task_payload(task_id="test_zpeak_fit_structure")

    outputs = await send_task_payload(payload, agent, streaming=False)
    resp, status, debug = extract_response_and_status(outputs)

    parsed = extract_json_from_response(resp)
    assert parsed is not None, f"Could not parse JSON from response:\n{resp[:500]}"

    if parsed.get("status") == "ok":
        # If successful, validate fit_result structure
        assert "fit_result" in parsed, f"Missing 'fit_result' for successful fit: {parsed}"
        fit_result = parsed["fit_result"]

        # Check for mu and sigma
        assert "mu" in fit_result, f"fit_result missing 'mu': {fit_result}"
        assert "sigma" in fit_result, f"fit_result missing 'sigma': {fit_result}"

        # Validate mu is near Z mass (around 91 GeV)
        mu = fit_result["mu"]
        assert 80 < mu < 100, f"fitted mu={mu} is far from expected Z mass (~91 GeV)"

        # Validate sigma is reasonable (typically 2-4 GeV for Z boson)
        sigma = fit_result["sigma"]
        assert 1 < sigma < 10, f"fitted sigma={sigma} seems unreasonable"

    elif parsed.get("status") == "error":
        # If error, should have explanation in comments
        assert "comments" in parsed or "error" in parsed, f"Error status but no explanation: {parsed}"


@pytest.mark.asyncio
async def test_zpeak_fit_method_documentation(agent):
    """
    Test that the agent documents its fit method choices.
    """
    payload = build_zpeak_task_payload(task_id="test_zpeak_method_doc")

    outputs = await send_task_payload(payload, agent, streaming=False)
    resp, status, debug = extract_response_and_status(outputs)

    parsed = extract_json_from_response(resp)
    assert parsed is not None, f"Could not parse JSON from response:\n{resp[:500]}"

    if parsed.get("status") == "ok":
        # Check for fit_method documentation
        assert "fit_method" in parsed, f"Missing 'fit_method' documentation: {parsed}"
        fit_method = parsed["fit_method"]

        # Validate fit_method fields
        assert "model" in fit_method, f"fit_method missing 'model': {fit_method}"
        assert "fit_range" in fit_method, f"fit_method missing 'fit_range': {fit_method}"

        # fit_range should be a 2-element list
        fit_range = fit_method["fit_range"]
        assert isinstance(fit_range, list) and len(fit_range) == 2, f"Invalid fit_range format: {fit_range}"
        assert fit_range[0] < fit_range[1], f"fit_range should be [low, high]: {fit_range}"


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_zpeak_streaming_modes(agent, streaming):
    """
    Test that the agent works correctly in both streaming and non-streaming modes.
    """
    payload = build_zpeak_task_payload(task_id=f"test_zpeak_streaming_{streaming}")

    outputs = await send_task_payload(payload, agent, streaming=streaming)
    resp, status, debug = extract_response_and_status(outputs)

    assert outputs, f"No output in streaming={streaming} mode"
    assert status in ("completed", "ok"), f"Task not completed in streaming={streaming} mode. status={status}"

    parsed = extract_json_from_response(resp)
    assert parsed is not None, f"Could not parse JSON in streaming={streaming} mode:\n{resp[:500]}"
    assert "status" in parsed, f"Missing status in streaming={streaming} mode"


@pytest.mark.asyncio
async def test_tool_inspect_schema_called(agent):
    """
    Test that the agent inspects the ROOT schema before loading data.
    We can infer this from the comments or structure of the response.
    """
    payload = build_zpeak_task_payload(task_id="test_schema_inspection")

    outputs = await send_task_payload(payload, agent, streaming=False)
    resp, status, debug = extract_response_and_status(outputs)

    parsed = extract_json_from_response(resp)
    assert parsed is not None, f"Could not parse JSON:\n{resp[:500]}"

    # Check if response indicates schema inspection
    # The agent should mention tree/branch names in comments or response
    resp_lower = resp.lower()
    schema_keywords = ["tree", "branch", "muons_", "pt", "eta", "phi"]
    found_schema_hint = any(kw in resp_lower for kw in schema_keywords)

    # Soft assertion - just log if not found
    if not found_schema_hint:
        print("Warning: Response doesn't mention typical schema keywords. Agent may not have inspected schema.")


@pytest.mark.asyncio
async def test_payload_format_matches_spec(agent):
    """
    Verify the payload format sent matches the green agent's expected format.
    """
    payload = build_zpeak_task_payload(
        task_id="format_test_001",
        task_type="z_peak_fit",
        release="2025e-13tev-beta",
        dataset="data15_periodD",
    )

    # Validate payload structure
    assert "role" in payload and payload["role"] == "task_request"
    assert "task_id" in payload
    assert "task_type" in payload
    assert "prompt" in payload
    assert "data" in payload
    assert "constraints" in payload

    # Validate data sub-structure
    data = payload["data"]
    assert "files" in data
    assert "release" in data
    assert "dataset" in data
    assert "skim" in data

    # Now send and verify agent processes it
    outputs = await send_task_payload(payload, agent, streaming=False)
    resp, status, debug = extract_response_and_status(outputs)

    assert status in ("completed", "ok"), f"Agent couldn't process valid payload. status={status}"


@pytest.mark.asyncio
async def test_error_handling_no_file(agent):
    """
    Test agent behavior when given a non-existent file path.
    """
    payload = build_zpeak_task_payload(
        task_id="test_error_no_file",
        files=["/nonexistent/path/to/file.root"],
    )

    outputs = await send_task_payload(payload, agent, streaming=False)
    resp, status, debug = extract_response_and_status(outputs)

    parsed = extract_json_from_response(resp)

    # Agent should either return error status or the task should fail gracefully
    if parsed:
        if parsed.get("status") == "error":
            assert "comments" in parsed or "error" in parsed, "Error response should explain the issue"
        # If status is ok, the agent handled it somehow (unexpected but possible)


@pytest.mark.asyncio
async def test_gof_metrics_present(agent):
    """
    Test that goodness-of-fit metrics are included in successful fits.
    """
    payload = build_zpeak_task_payload(task_id="test_gof_metrics")

    outputs = await send_task_payload(payload, agent, streaming=False)
    resp, status, debug = extract_response_and_status(outputs)

    parsed = extract_json_from_response(resp)
    assert parsed is not None, f"Could not parse JSON:\n{resp[:500]}"

    if parsed.get("status") == "ok":
        fit_result = parsed.get("fit_result", {})

        # GOF metrics are nice to have but not strictly required
        # Just check structure if present
        if "gof" in fit_result:
            gof = fit_result["gof"]
            # At least one metric should be present
            assert any(k in gof for k in ["p_value", "chi2_ndof", "chi2", "ndf"]), \
                f"gof present but missing expected metrics: {gof}"
