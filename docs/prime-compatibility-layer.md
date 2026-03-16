# Prime compatibility layer

Hermes can support Prime without rewriting the Atropos environment layer, but
it is not a one-line provider swap. The current RL path assumes a
Tinker-specific control plane, local process topology, and Tinker-specific
credentials. The smallest sane change is to add a backend seam, keep the
Hermes environment and reward stack, and implement Prime as a parallel backend
first.

## Summary

The current codebase mixes three different concerns inside the same RL surface:
environment definition, local trainer orchestration, and user-facing setup and
status UX. Prime compatibility is mostly blocked by the second and third
concerns, not by the environment logic itself.

- Keep the Hermes environment layer in `environments/`.
- Keep reward verification through `ToolContext`.
- Keep evaluation and trajectory-generation patterns where they already work.
- Replace the hard-coded Tinker launcher with a backend interface.
- Add Prime support as a second backend before changing the existing
  `rl_*` tools in place.

## What is reusable today

The reusable part of the stack is the Hermes-specific environment contract. It
already wraps the agent loop, tool execution, and reward verification in a way
that is mostly backend-agnostic.

- `environments/hermes_base_env.py` provides the shared BaseEnv integration.
- `environments/agent_loop.py` drives the multi-turn tool-calling rollout.
- `environments/tool_context.py` lets verifiers inspect the same sandbox state
  the model used during rollout.
- `environments/README.md` documents the `serve`, `process`, and `evaluate`
  modes that can remain valid under a Prime-oriented flow.
- `skills/mlops/training/hermes-atropos-environments/SKILL.md` is already
  centered on environment authoring, reward functions, and evaluation, which
  should stay stable.

In practice, this means Hermes does not need a new environment model for
Prime. It needs a new training and execution backend around the existing
environment model.

## What is hard-coupled to Tinker today

The current RL toolchain hard-codes Tinker at every operational boundary.
Those assumptions are why Prime is not a config toggle.

- `tools/rl_training_tool.py` scans environments from the
  `tinker-atropos` submodule path.
- `tools/rl_training_tool.py` bakes in local URLs for rollout and inference:
  `http://localhost:8000` and `http://localhost:8001/v1`.
- `tools/rl_training_tool.py` hard-codes the launch sequence as
  `run-api`, `launch_training.py`, then `environment.py serve`.
- `tools/rl_training_tool.py` requires `TINKER_API_KEY` to start training and
  assumes `WANDB_API_KEY` for metrics and results.
- `hermes_cli/tools_config.py` exposes RL setup only as
  "Tinker / Atropos" and its post-setup logic installs the
  `tinker-atropos` submodule.
- `hermes_cli/setup.py`, `hermes_cli/status.py`, `hermes_cli/config.py`, and
  `hermes_cli/doctor.py` all treat RL as a Tinker-specific feature.
- `rl_cli.py` sets `TERMINAL_CWD` to the `tinker-atropos` checkout and frames
  the workflow entirely around Tinker.
- `website/docs/user-guide/features/rl-training.md` and related docs describe
  RL as a Tinker-plus-Atropos stack.

There is also a concrete repo issue: the `tinker-atropos` submodule exists in
Git metadata, but it is not initialized in this checkout. That means the
current RL path is not only Tinker-specific, it is also not fully installed by
default.

## Recommended architecture split

The compatibility layer should separate environment logic from training
orchestration. A small backend interface is enough.

```python
class TrainingBackend(Protocol):
    name: str

    def validate_install(self) -> list[str]: ...
    def required_env_vars(self) -> list[str]: ...
    def discover_environments(self) -> list[EnvironmentInfo]: ...
    def default_config(self, environment: EnvironmentInfo) -> dict[str, Any]: ...
    async def start_run(self, environment: EnvironmentInfo,
                        config: dict[str, Any]) -> RunHandle: ...
    async def stop_run(self, run_id: str) -> dict[str, Any]: ...
    async def get_status(self, run_id: str) -> dict[str, Any]: ...
    async def get_results(self, run_id: str) -> dict[str, Any]: ...
    async def test_inference(self, environment: EnvironmentInfo,
                             config: dict[str, Any]) -> dict[str, Any]: ...
```

The existing `rl_training_tool.py` should become the orchestration layer that
delegates to a backend instead of owning the Tinker process model directly.

### Layer 1: environment catalog

This layer answers, "What environments exist, and how do I load their editable
config?" Hermes already does this work, but it should stop assuming the
environments live under the `tinker-atropos` submodule.

Recommended changes:

- Move the environment root behind configuration.
- Support at least two environment sources:
  `repo_environments` and `tinker_submodule`.
- Keep the AST scanning and config extraction logic.

### Layer 2: backend adapter

This layer answers, "How does a run actually start, stop, and report status?"
This is where Tinker and Prime differ.

Recommended initial backends:

- `TinkerBackend`
  - Keeps the current `run-api` plus `launch_training.py` flow.
  - Owns local process handles and log files.
- `PrimeBackend`
  - Owns `PRIME_API_KEY` validation.
  - Owns Prime CLI or SDK invocation.
  - Treats Prime-hosted training as the default execution mode.
  - Returns normalized status and results back to Hermes.

### Layer 3: UX and config surface

This layer answers, "How does the user enable RL, configure providers, and see
status?" It should stop assuming there is only one RL provider.

Recommended changes:

- Replace the single RL provider entry in `hermes_cli/tools_config.py` with a
  provider list that includes at least `Tinker / Atropos` and `Prime`.
- Add `PRIME_API_KEY` to `hermes_cli/config.py` and `hermes_cli/status.py`.
- Update `hermes_cli/setup.py` and `hermes_cli/doctor.py` to report the active
  RL backend rather than only Tinker installation state.
- Keep the `rl` toolset name. Add a backend selector instead of creating a new
  top-level toolset.

## Prime backend behavior

The first Prime backend should optimize for hosted execution, not local GPU
training inside Hermes.

### Start run

The backend should:

1. Validate `PRIME_API_KEY`.
2. Resolve a Prime workspace or lab configuration.
3. Materialize a run config from the selected Hermes environment.
4. Start the Prime-hosted training or evaluation job.
5. Return a normalized `run_id`, provider metadata, and dashboard links.

### Status and results

The backend should normalize Prime state into Hermes' existing run model.

Recommended normalized fields:

- `run_id`
- `backend`
- `status`
- `started_at`
- `updated_at`
- `environment`
- `metrics`
- `artifacts`
- `provider_url`
- `error`

This keeps Hermes' status UI stable even if the upstream provider differs.

### Inference testing

`rl_test_inference` is a good candidate for early Prime support because it is
already less coupled than full training. The first Prime path can support
evaluation and dry-run validation before full training parity lands.

## Migration plan

The smallest low-risk sequence is a four-step migration.

### Phase 1: provider plumbing

Add `PRIME_API_KEY`, backend selection, and Prime-aware status/setup without
changing the existing Tinker execution path.

Expected files:

- `hermes_cli/config.py`
- `hermes_cli/status.py`
- `hermes_cli/setup.py`
- `hermes_cli/tools_config.py`

### Phase 2: backend seam

Refactor `tools/rl_training_tool.py` so the current implementation becomes a
`TinkerBackend` instead of the only implementation.

Expected files:

- `tools/rl_training_tool.py`
- a new backend module such as `tools/rl_backends.py`

### Phase 3: Prime MVP

Implement Prime start, status, results, and inference-test support as a
parallel backend. Do not delete the Tinker backend yet.

Expected files:

- `tools/rl_training_tool.py`
- `tools/rl_backends.py`
- Prime-specific tests

### Phase 4: environment source cleanup

Stop treating the `tinker-atropos` submodule as the default source of
environments. Make environment discovery explicit and configurable.

Expected files:

- `tools/rl_training_tool.py`
- `rl_cli.py`
- docs

## Estimated lift

This is a medium lift, not a full rewrite.

- Small change: secret wiring, config keys, status output, docs.
- Medium change: backend seam in `rl_training_tool.py`.
- Large change: full one-for-one parity with every Tinker-specific training
  feature and metric.

The right read is: Prime compatibility is bigger than a config flip, but it is
smaller than rebuilding Hermes RL from scratch.

## Recommendation

The recommended path is to ship Prime as a parallel backend first.

That gives you:

- a working Prime path for hosted runs,
- minimal disruption to existing Tinker users,
- a cleaner architecture for later backend additions, and
- a way to decide with real usage data whether the legacy Tinker path is still
  worth keeping.

Do not start by rewriting the current `rl_*` tools around Prime semantics
directly. Start by making the current Tinker implementation one backend among
several.
