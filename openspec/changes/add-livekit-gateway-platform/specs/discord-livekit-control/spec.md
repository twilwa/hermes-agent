## ADDED Requirements

### Requirement: Discord acts as a thin control surface for LiveKit rooms
The system SHALL allow Discord users to create, link, and inspect LiveKit rooms
through Discord control commands without making Discord the owner of the media
plane.

#### Scenario: Discord creates a LiveKit room
- **WHEN** an authorized Discord user invokes the LiveKit room creation command
- **THEN** Hermes creates a LiveKit room or linkage record
- **AND** returns the room join information to the invoking Discord context

#### Scenario: Discord links an existing LiveKit room
- **WHEN** an authorized Discord user links a Discord channel or thread to an
  existing LiveKit room
- **THEN** Hermes persists the linkage
- **AND** subsequent control and mirror operations target that linked room

### Requirement: Discord control flow reuses Hermes gateway command handling
The system SHALL route Discord LiveKit control actions through the existing
slash-command event flow so authorization, session context, and agent behavior
remain consistent with other Discord commands.

#### Scenario: Slash command becomes a Hermes event
- **WHEN** a Discord user invokes a LiveKit control slash command
- **THEN** the adapter converts it into a `MessageEvent`
- **AND** Hermes handles it through the normal Discord gateway pipeline

#### Scenario: Phase one does not bridge Discord audio
- **WHEN** a Discord user links or creates a LiveKit room
- **THEN** Hermes exposes control and text continuity only
- **AND** does not start a bidirectional Discord↔LiveKit audio bridge
