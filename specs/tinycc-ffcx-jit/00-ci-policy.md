# TinyCC CI policy

This policy supersedes the earlier `EPIC.md` / Phase-1 wording that required TinyCC qualification to be manual-only and `stack.yml` to be the sole automatic pull-request workflow.

TinyCC remains experimental, but its dedicated qualification workflow may run automatically on pull requests when TinyCC-specific implementation, workflow, recipe, or specification paths change. The workflow must remain narrowly path-scoped so unrelated repository changes do not incur the experimental matrix cost.

`workflow_dispatch` remains supported for explicit requalification runs.

`stack.yml` remains the general automatic PR/main workflow. `tinycc-jit.yml` is an additional automatic PR qualification gate only for TinyCC-relevant changes; it is not a general automatic main-branch workflow.

The automatic TinyCC trigger must include at least:

- `.github/workflows/tinycc-jit.yml`;
- `scripts/tinycc-jit/**`;
- `specs/tinycc-ffcx-jit/**`;
- TinyCC-specific recipes/runtime packaging paths once those are introduced.

This policy applies to all phases of the TinyCC FFCx JIT epic unless a later spec explicitly replaces it.
