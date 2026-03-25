---
sidebar_position: 4
title: "LiveKit"
description: "Set up Hermes Agent as a LiveKit-native media participant with Discord as a control surface"
---

# LiveKit Setup

Hermes joins LiveKit rooms as a native media participant. In phase one, LiveKit owns the media plane. Discord is only used as a control surface for room management and status.

:::warning Phase-one scope
This page covers the operator lane only.

The exact Discord control commands, room-link storage, and mirroring runtime are owned by the gateway workstreams and are not documented here yet.
:::

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `LIVEKIT_URL` | LiveKit server URL or LiveKit Cloud project URL |
| `LIVEKIT_API_KEY` | LiveKit API key used by the Hermes agent |
| `LIVEKIT_API_SECRET` | LiveKit API secret used by the Hermes agent |

## Optional Environment Variables

These variables are useful when you want to pin a room name or control which
users can reach the LiveKit gateway.

| Variable | Description |
|----------|-------------|
| `LIVEKIT_TOKEN` | Optional LiveKit session token override for advanced deployments |
| `LIVEKIT_ROOM` / `LIVEKIT_HOME_ROOM` | Default LiveKit room used for home delivery |
| `LIVEKIT_ROOM_NAME` / `LIVEKIT_HOME_ROOM_NAME` | Display name for the default LiveKit room |
| `LIVEKIT_ALLOWED_USERS` | Comma-separated user IDs allowed to use the LiveKit gateway |
| `LIVEKIT_ALLOW_ALL_USERS` | Allow all users without an allowlist (`true`/`false`, default: `false`) |

## Configure LiveKit

1. Add the LiveKit variables above to `~/.hermes/.env`.
2. Run `hermes gateway setup` and select `LiveKit`.
3. If you want Discord to control LiveKit rooms, configure Discord separately with [Discord Setup](discord.md).

## Linking and Mirroring

When a LiveKit room is linked to a Hermes session, mirrored status or
transcript events are appended to the target session history. When a room is
not linked, Hermes keeps the room context local to LiveKit and does not create
cross-platform mirror records.

If mirrored context is missing, verify the room link and target session before
checking agent behavior.

## What Phase One Does Not Include

- It does not add a Discord audio bridge.
- It does not require Discord to be present for LiveKit room operation.
- It does not document the control command names or linkage storage owned by the runtime workstreams.

## Troubleshooting

- If `hermes status` shows LiveKit as partially configured, one or more of the three LiveKit variables is missing.
- If you only want LiveKit media and do not want Discord control, you can leave Discord unconfigured for now.
