# agent_03b_scifi_native

`agent_03b_scifi_native` is the general native SciFi-style backend. It keeps the
same Green/Purple wire format, SAM loop, independent review, retry feedback,
and native Python tool execution pattern as `03a`, but owns its package-local
`loop.py`, `native_worker.py`, and prompt builder.

The difference is that `03b` uses a task-agnostic SAM prompt. It relies on the
task prompt, submission contract, runtime manifest, generic tool loop, and
review feedback. This makes it the smallest native starting point for later
SciFi-reference migration work.

Registered backend names:

- `agent_3b_scifi_native`
- `agent_03b_scifi_native`
- `scifi_native_general`
- `native_scifi_general`

Useful environment variables are the same as `03a`:

- `SCIFI_NATIVE_MODEL`
- `SCIFI_NATIVE_BASE_URL`
- `SCIFI_NATIVE_API_KEY`
- `SCIFI_NATIVE_MAX_ITERATIONS`
- `SCIFI_NATIVE_MAX_BASH_SECONDS`
- `SCIFI_NATIVE_MAX_TOOL_CHARS`
- `SCIFI_NATIVE_MAX_RETRIES`

Debug log:

```text
<solver_work>/debug_scifi_native_output.log
```
