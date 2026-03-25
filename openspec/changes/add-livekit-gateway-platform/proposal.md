## Why

Hermes already treats messaging transports as gateway platforms that normalize
inbound events into a shared session and agent pipeline. LiveKit fits that
architecture more cleanly as a first-class platform than as a skill or as a
Discord-specific audio bridge, because the repo already routes session
identity, toolset selection, cached agents, and mirror delivery off
`SessionSource.platform`.

## What Changes

- Add LiveKit as a first-class gateway platform with config, adapter factory,
  toolset, prompt hint, setup, status, and delivery integration.
- Introduce a LiveKit adapter that joins rooms as the Hermes agent, normalizes
  text and voice activity into `MessageEvent`, and publishes Hermes responses
  back into the room.
- Preserve session continuity by keying LiveKit room and participant activity
  through the existing `SessionSource` and `SessionStore` flow.
- Add a Discord control surface that can create or link a LiveKit room and
  post room status, join links, and mirrored transcripts back into Discord.
- Reuse mirror/session plumbing for continuity between LiveKit and Discord
  rather than implementing a bidirectional Discord audio bridge in phase one.

## Capabilities

### New Capabilities

- `livekit-platform-configuration`: Load, validate, expose, and operate LiveKit
  as a first-class Hermes gateway platform.
- `livekit-room-conversations`: Normalize LiveKit room activity into Hermes
  sessions and preserve room-scoped conversational continuity.
- `livekit-voice-agent-runtime`: Run Hermes as a LiveKit-native voice agent
  participant with STT/TTS round-tripping inside the room.
- `discord-livekit-control`: Use Discord as a thin control surface for LiveKit
  room creation, linking, and status reflection.
- `livekit-mirroring-observability`: Mirror linked room status/transcripts into
  Hermes session history and expose operational/test coverage for the new
  platform.

### Modified Capabilities

- None.

## Impact

- Affected code spans `gateway/config.py`, `gateway/run.py`,
  `gateway/platforms/`, `gateway/session.py`, `gateway/mirror.py`,
  `toolsets.py`, `tools/send_message_tool.py`, `cron/scheduler.py`,
  `agent/prompt_builder.py`, `hermes_cli/`, and `tests/gateway/`.
- Adds a new runtime dependency surface for LiveKit connectivity and room
  control, plus new configuration and setup paths in the gateway.
- Explicitly defers a Discord↔LiveKit bidirectional media bridge; phase one is
  LiveKit-native media with Discord only handling control, status, and text
  continuity.
