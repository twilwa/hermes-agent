## ADDED Requirements

### Requirement: Linked LiveKit rooms can mirror status and transcript events
The system SHALL mirror linked LiveKit room status or transcript events into the
appropriate Hermes session so Discord and other linked control surfaces retain
continuity without taking ownership of the room media plane.

#### Scenario: Linked transcript is mirrored into the target session
- **WHEN** a linked LiveKit room emits a transcript or status event marked for
  mirroring
- **THEN** Hermes appends a mirror record to the target session history
- **AND** the receiving-side agent can see that mirrored context on later turns

#### Scenario: Unlinked rooms do not mirror arbitrarily
- **WHEN** a LiveKit room has no linked control surface
- **THEN** Hermes does not append cross-platform mirror records for that room
- **AND** room context stays local to the LiveKit session

### Requirement: Hermes exposes operational visibility for the LiveKit platform
The system SHALL provide tests and operator-visible status for LiveKit so the
new platform can be configured and diagnosed like the existing gateway adapters.

#### Scenario: Operator surfaces show LiveKit state
- **WHEN** the gateway reports platform status
- **THEN** LiveKit appears in the platform status output with its configured or
  runtime state

#### Scenario: Regression coverage protects the integration
- **WHEN** Hermes test suites run for the LiveKit change
- **THEN** they cover config loading, adapter lifecycle, session routing,
  mirroring, and Discord control integration for LiveKit
