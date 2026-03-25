## 1. Platform Foundation

- [ ] 1.1 Add `Platform.LIVEKIT` and LiveKit config/env loading in `gateway/config.py`.
- [ ] 1.2 Add `hermes-livekit` toolset mapping and platform prompt hints.
- [ ] 1.3 Expose LiveKit in operator-facing status/setup surfaces.

## 2. Runner And Delivery Plumbing

- [ ] 2.1 Add LiveKit adapter creation, authorization env mappings, and default platform toolset selection in `gateway/run.py`.
- [ ] 2.2 Add LiveKit routing to `tools/send_message_tool.py` and `cron/scheduler.py`.
- [ ] 2.3 Add LiveKit to channel/session discovery surfaces where session-backed lookup is required.

## 3. LiveKit Adapter Runtime

- [ ] 3.1 Create `gateway/platforms/livekit.py` with requirements checks, connect/disconnect, send, typing, and chat-info behavior.
- [ ] 3.2 Normalize inbound LiveKit room text and voice turns into `MessageEvent` values with stable `SessionSource` identity.
- [ ] 3.3 Publish Hermes responses back into the LiveKit room and clean up room state on disconnect/reconnect.

## 4. Linkage And Mirroring

- [ ] 4.1 Add a gateway-owned linkage model for LiveKit room ↔ Discord control-channel associations.
- [ ] 4.2 Mirror linked LiveKit status/transcript events into Hermes session history.
- [ ] 4.3 Verify linked sessions preserve room continuity without introducing a Discord audio bridge.

## 5. Discord Control Surface

- [ ] 5.1 Add Discord slash command support for creating or linking a LiveKit room.
- [ ] 5.2 Post join links, room status, and linkage feedback back into the invoking Discord context.
- [ ] 5.3 Reuse the existing slash-command event flow so Discord control commands enter Hermes through normal gateway handling.

## 6. Verification And Documentation

- [ ] 6.1 Add focused gateway tests for config loading, adapter lifecycle, session routing, mirroring, and Discord control flows.
- [ ] 6.2 Document LiveKit setup and environment variables in the website docs and operator references.
- [ ] 6.3 Validate the OpenSpec change and run targeted gateway regression tests for the new platform.
