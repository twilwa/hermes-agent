## Overview

Hermes Agent is a multi-platform conversational agent runtime. It combines a
shared `AIAgent` core, tool orchestration, session persistence, and a gateway
layer that adapts multiple transport surfaces into one normalized message
pipeline.

## Architectural Patterns

- New user-facing transports belong in `gateway/platforms/` as first-class
  adapters that emit normalized `MessageEvent` values.
- Session continuity is keyed by `SessionSource` and `build_session_key()` in
  `gateway/session.py`, not by platform-specific ad hoc state.
- Gateway runners choose platform-specific toolsets and reuse cached
  `AIAgent` instances so prompt construction and tool schemas stay stable
  within a session.
- Cross-platform continuity is handled with mirroring and delivery hooks,
  rather than transport-specific bridges.

## Major Implementation Areas

- `gateway/`: platform adapters, session storage, runner orchestration,
  mirroring, channel discovery, and delivery routing.
- `agent/` and `run_agent.py`: prompt building, tool execution, context
  handling, and model/runtime selection.
- `tools/` and `toolsets.py`: tool registration, platform toolset mapping,
  direct-send helpers, and background capabilities.
- `hermes_cli/`: config loading, status/setup flows, and CLI-facing gateway
  controls.
- `tests/gateway/`: transport and runner verification for platform behavior,
  session routing, delivery, and mirroring.
