# agent_02_scifi_oh

`agent_02_scifi_oh` is a lightweight SciFi-style solver backend for the HEPEx
AnalysisOps Purple Agent.

This backend is best read as a **SciFi-OH controller** around an
**OpenHarness executor**:

```text
Green Agent task
  -> agent_2_scifi_oh backend
  -> SAM prompt builder
  -> OpenHarness worker executor (`oh`)
  -> independent SciFi-style review
  -> retry with review feedback, or final submission_bundle_v1
```

It is inspired by the SciFi autonomous scientific workflow by Qibin Liu and
Julia Gonski and is included with author permission. This directory intentionally
absorbs only the small workflow pattern needed for AgentBeats:

- SAM-shaped task prompts: Context, Todo, Expect
- a work loop with bounded retries
- an independent deterministic review before returning a bundle
- review feedback injected into the next worker attempt

It does not vendor or run the full SciFi runtime. In particular it does not
include SciFi's Apptainer container launcher, Pam/LiteLLM gateway, SciF/SciFi
CLI, Cam audit system, global memory, or model-ranking runtime. The Purple
Agent is already launched by AgentBeats/Green Agent infrastructure, so this
backend keeps the public wire format unchanged and returns only
`submission_bundle_v1`.

The worker execution layer is still OpenHarness. That is intentional: SciFi
contributes the control pattern here, while OpenHarness remains the local
executor that actually runs the model/tooling command. In implementation terms,
`agent_2_scifi_oh` calls `oh --print ...` for each work attempt, then reviews the
returned bundle before deciding whether to retry.

Because this backend owns the SciFi-OH controller, its debug log is named after
that combined role:

```text
<solver_work>/debug_scifi_oh_output.log
```

Inside that log the executor is explicitly recorded as `openharness`, so local
runs show both facts: SciFi-OH backend/controller, OpenHarness worker
executor.

For CI debugging, the backend also prints this file to the Purple container log
near the end of each SciFi-OH task. Search the GitHub Actions log for
`BEGIN debug_scifi_oh_output.log`.

Registered backend names:

- `agent_2_scifi_oh`
- `scifi_oh`

The default backend remains `agent_1_oh`; use this backend explicitly from the
leaderboard/local runner with `--solver-backend agent_2_scifi_oh`.

The unsuffixed names `agent_2_scifi` and `scifi` are intentionally left free for
a future backend that vendors or drives a closer-to-upstream SciFi runtime.
