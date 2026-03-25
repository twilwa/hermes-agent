## ADDED Requirements

### Requirement: LiveKit room activity enters Hermes through normalized gateway events
The system SHALL transform LiveKit room activity into `MessageEvent` values so
LiveKit conversations use the same gateway, session, and agent pipeline as the
existing messaging platforms.

#### Scenario: LiveKit room text becomes a MessageEvent
- **WHEN** a user sends a supported text event in a LiveKit room
- **THEN** Hermes creates a `MessageEvent` with `platform=livekit`
- **AND** dispatches it through the standard gateway message handler

#### Scenario: LiveKit voice turns become synthetic message events
- **WHEN** a user speaks in a LiveKit room and speech-to-text completes
- **THEN** Hermes creates a synthetic text `MessageEvent` from the transcript
- **AND** processes it through the same conversation path used for typed input

### Requirement: LiveKit conversations preserve room-scoped Hermes sessions
The system SHALL map LiveKit room and participant identity into `SessionSource`
in a way that preserves Hermes session continuity and cached agent reuse.

#### Scenario: Follow-up turns reuse the same session
- **WHEN** the same participant continues in the same linked LiveKit room
- **THEN** Hermes resolves the same session key for follow-up turns
- **AND** reuses the room's existing session history and cached agent when the
  runtime signature has not changed

#### Scenario: LiveKit does not require Discord for session routing
- **WHEN** Hermes is operating in LiveKit without any Discord linkage
- **THEN** the LiveKit room still resolves to a valid Hermes session
- **AND** replies route back into the LiveKit room without Discord-specific state
