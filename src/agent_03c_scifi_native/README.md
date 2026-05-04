# agent_03c_scifi_native

`agent_03c_scifi_native` is the native SciFi backend aligned with the reference
SciFi branch `dev_max_bench_v2`.

It keeps the AgentBeats transport and submission contract intact, but adopts the
branch-v2 runtime ideas that are useful inside the Purple Agent:

- SAM framing with Context, Todo, and Expect.
- General contract-driven prompt construction.
- Native tool loop without OpenHarness.
- Shared environment discovery and activation tools.
- Deterministic compacting for long tool outputs.
- Independent review and retry through its package-local SciFi loop.

It intentionally does not vendor the full SciFi Apptainer/Pam/Cam scheduler.
Those are outside the Purple Agent runtime boundary.

Registered backend names:

- `agent_3c_scifi_native`
- `agent_03c_scifi_native`
- `scifi_native_v2`
- `native_scifi_v2`

Useful environment variables:

- `SCIFI_NATIVE_MODEL`
- `SCIFI_NATIVE_BASE_URL`
- `SCIFI_NATIVE_API_KEY`
- `SCIFI_NATIVE_SHARED_ENV_ROOT`, default `/mnt/sci_envs`
- `SCIFI_NATIVE_MAX_ITERATIONS`
- `SCIFI_NATIVE_MAX_BASH_SECONDS`
- `SCIFI_NATIVE_MAX_TOOL_CHARS`
- `SCIFI_NATIVE_MAX_RETRIES`

Debug log:

```text
<solver_work>/debug_scifi_native_output.log
```
