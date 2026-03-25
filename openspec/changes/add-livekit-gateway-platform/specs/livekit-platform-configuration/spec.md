## ADDED Requirements

### Requirement: Hermes exposes LiveKit as a first-class gateway platform
The system SHALL expose LiveKit anywhere Hermes enumerates supported gateway
platforms so operators can configure, enable, and route Hermes through LiveKit
without treating it as a skill-only integration.

#### Scenario: LiveKit configuration enables the platform
- **WHEN** LiveKit credentials and platform configuration are present
- **THEN** `GatewayConfig` includes `Platform.LIVEKIT` in connected platforms
- **AND** the gateway can create a LiveKit adapter for that platform

#### Scenario: LiveKit receives a platform-specific toolset
- **WHEN** the runner resolves toolsets for a LiveKit session
- **THEN** it selects a LiveKit-specific Hermes gateway toolset
- **AND** that toolset participates in the `hermes-gateway` composite

### Requirement: Hermes surfaces LiveKit in operator workflows
The system SHALL expose LiveKit in operator-facing setup, status, and delivery
surfaces so enabling the platform does not require hidden repo knowledge.

#### Scenario: Setup and status surfaces list LiveKit
- **WHEN** an operator opens Hermes setup or status output
- **THEN** LiveKit appears alongside the other supported gateway platforms
- **AND** the operator can discover the required LiveKit environment variables

#### Scenario: Delivery helpers recognize LiveKit
- **WHEN** a cron job or send-message helper targets LiveKit
- **THEN** Hermes resolves the LiveKit platform name into the platform enum
- **AND** attempts delivery through the LiveKit platform path
