## Summary

This change adds LiveKit as a gateway platform, not as a skill and not as a
Discord media bridge. The media plane stays LiveKit-native; Discord only
launches, links, and reflects room state.

## Verified Architectural Fit

- New transports are normalized by platform adapters via `MessageEvent` in
  `gateway/platforms/base.py`.
- Runner-side adapter creation is centralized in `_create_adapter()` in
  `gateway/run.py`.
- Session context and routing are keyed by `SessionSource.platform`,
  `chat_id`, `thread_id`, and participant identity in `gateway/session.py`.
- Platform toolset selection and cached `AIAgent` reuse are already keyed off
  platform and session in `gateway/run.py`.
- Discord voice input is already implemented as a transport-specific ingest
  path that re-enters the normal Hermes pipeline as a synthetic message event.
- Cross-platform continuity already exists through `gateway/mirror.py` and
  `tools/send_message_tool.py`.

This means LiveKit can follow the repo's existing extension seams without
adding a second parallel conversation runtime.

## Non-Goals

- No phase-one Discord↔LiveKit bidirectional audio bridge.
- No new skill-based LiveKit entrypoint that bypasses gateway/session logic.
- No requirement that Discord be present for Hermes to operate in LiveKit.

## Proposed Shape

### 1. Platform Foundation

Add `Platform.LIVEKIT` and wire it through the same integration points used by
existing gateway platforms:

- `gateway/config.py`
- `gateway/run.py`
- `toolsets.py`
- `agent/prompt_builder.py`
- `cron/scheduler.py`
- `tools/send_message_tool.py`
- `gateway/channel_directory.py`
- `hermes_cli/status.py`
- `hermes_cli/gateway.py`

### 2. LiveKit Adapter

Create `gateway/platforms/livekit.py` as a `BasePlatformAdapter` subclass.
Its responsibilities are:

- Connect to LiveKit with Hermes agent credentials.
- Join configured or linked rooms as the Hermes participant.
- Convert inbound room text and/or transcribed voice turns into `MessageEvent`.
- Publish agent responses back into the room as text and voice.
- Track participant lifecycle and clean room state on disconnect/reconnect.

### 3. Session Model

The initial design should reuse existing `SessionSource` fields:

- `platform=Platform.LIVEKIT`
- `chat_id=<room identifier>`
- `chat_name=<room name>`
- `chat_type="group"` or `"channel"` depending on the room semantics
- `user_id=<participant identity>`
- `user_name=<participant display name>`

Only extend `SessionSource` if a missing LiveKit identity concept proves
necessary for stable routing or mirroring.

### 4. Discord Control Surface

Discord should remain a thin control surface:

- create a room
- link an existing room to a Discord channel/thread
- post join/status information
- reflect mirrored transcripts or summaries

This can piggyback on the existing Discord slash-command pattern, where slash
commands are converted into `MessageEvent` via `_build_slash_event()`.

### 5. Mirroring and Link State

Linked LiveKit↔Discord relationships should live in a small gateway-owned data
store or config-backed registry, not in Discord-only state. That linkage layer
is responsible for:

- mapping a LiveKit room to a Discord control channel/thread
- deciding which events should be mirrored
- appending mirrored status/transcript records to the target session

## Parallel Workstreams

### Workstream A: Platform/config foundation

Ownership:
- `gateway/config.py`
- `toolsets.py`
- `agent/prompt_builder.py`

Goal:
- establish `Platform.LIVEKIT`, config/env loading, toolset naming, and prompt
  hints without touching Discord or the media runtime.

### Workstream B: Runner/delivery plumbing

Ownership:
- `gateway/run.py`
- `cron/scheduler.py`
- `tools/send_message_tool.py`
- `gateway/channel_directory.py`

Goal:
- make the runner, authorization maps, delivery helpers, and discovery surfaces
  aware of LiveKit.

### Workstream C: LiveKit adapter/media runtime

Ownership:
- `gateway/platforms/livekit.py`

Goal:
- implement room connectivity, ingress normalization, and agent response
  publication with LiveKit-native media handling.

### Workstream D: Linkage and mirroring

Ownership:
- `gateway/mirror.py`
- new gateway linkage state module if needed
- targeted session tests

Goal:
- persist LiveKit↔Discord linkage and mirror status/transcript events into the
  correct Hermes sessions.

### Workstream E: Discord control surface

Ownership:
- `gateway/platforms/discord.py`

Goal:
- add slash-command control for room creation/linking/status without taking on
  audio bridging.

### Workstream F: Docs, setup, and verification

Ownership:
- `hermes_cli/status.py`
- `hermes_cli/gateway.py`
- `website/docs/...`
- `tests/gateway/...`

Goal:
- expose the new platform to operators and cover the new behavior with focused
  tests.

## Validation Strategy

- Config/env loading tests for `Platform.LIVEKIT`.
- Adapter init/connect/disconnect tests with mocked LiveKit edges.
- Runner/session tests proving LiveKit messages reuse the standard Hermes
  session and agent cache behavior.
- Discord slash command tests for room creation/linking/status.
- Mirroring tests for linked LiveKit↔Discord transcript continuity.
- Targeted gateway regression suite before merge.
