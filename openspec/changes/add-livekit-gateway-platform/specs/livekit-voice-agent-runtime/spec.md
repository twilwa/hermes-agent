## ADDED Requirements

### Requirement: Hermes joins LiveKit rooms as the agent participant
The system SHALL connect Hermes to LiveKit rooms as a first-class participant
so the agent can receive room activity and publish responses inside the LiveKit
media plane.

#### Scenario: Hermes joins a configured room
- **WHEN** the LiveKit adapter connects for a configured or linked room
- **THEN** Hermes joins the LiveKit room as the agent participant
- **AND** tracks the room lifecycle until disconnect or shutdown

#### Scenario: Hermes survives reconnects
- **WHEN** the LiveKit connection drops or the room transport restarts
- **THEN** the adapter retries connection with bounded reconnect behavior
- **AND** cleans up stale room state before rejoining

### Requirement: Hermes responds inside LiveKit without Discord RTP dependencies
The system SHALL produce LiveKit-native responses so voice operation in
LiveKit does not depend on Discord voice transport, Discord decryption, or a
Discord audio bridge.

#### Scenario: A spoken room turn yields a LiveKit response
- **WHEN** a LiveKit participant speaks and Hermes completes the agent turn
- **THEN** Hermes publishes the response back into the LiveKit room
- **AND** any synthesized voice playback uses LiveKit-native publication

#### Scenario: LiveKit voice mode works without Discord configured
- **WHEN** Discord is disabled or unavailable
- **THEN** Hermes can still operate as a LiveKit voice agent
- **AND** no Discord voice runtime dependency blocks the LiveKit room flow
