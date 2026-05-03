# agent_01_oh

This directory owns the OpenHarness-backed reference solver backend assets.

Runtime backend id:

```text
agent_1_oh
```

The zero-padded directory name keeps backend assets sortable as additional
backends are added.

Contents:

- `AGENTS.md`: OpenHarness system prompt copied into the container as
  `/home/agent/AGENTS.md`.
- `skills/sm-ana-aod`: OpenHarness skills copied into
  `/home/agent/.openharness/skills`.

The A2A transport remains in `src/agent.py`; backend selection and execution
remain in `src/solver_backends.py`. This directory is intentionally limited to
backend-owned prompt and skill assets.
