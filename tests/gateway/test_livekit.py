# ABOUTME: Focused tests for the LiveKit gateway adapter's room wiring and event normalization.
# ABOUTME: Covers connection hooks, outbound publishing, typing packets, chat info, and MessageEvent creation.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from gateway.platforms.livekit import LiveKitAdapter, check_livekit_requirements


class FakeParticipant:
    def __init__(self, identity: str, name: str | None = None, sid: str | None = None):
        self.identity = identity
        self.name = name or identity
        self.sid = sid or f"PA_{identity}"
        self.metadata = None
        self.attributes = {}


class FakeRoom:
    def __init__(self):
        self.name = "team-room"
        self.sid = "RM_123"
        self.local_participant = FakeParticipant("hermes", name="Hermes", sid="PA_local")
        self.local_participant.send_text = AsyncMock(return_value=SimpleNamespace(stream_id="stream-1"))
        self.local_participant.publish_data = AsyncMock()
        self.remote_participants = {
            "user-1": FakeParticipant("user-1", name="Ada", sid="PA_user1"),
        }
        self.handlers = {}
        self.text_handlers = {}
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()

    def on(self, event_name, callback):
        self.handlers[event_name] = callback

    def register_text_stream_handler(self, topic, callback):
        self.text_handlers[topic] = callback


def make_adapter(**extra) -> LiveKitAdapter:
    config = PlatformConfig(enabled=True, token="lk-token")
    config.extra = {
        "url": "wss://livekit.example.test",
        "room_name": "team-room",
        **extra,
    }
    return LiveKitAdapter(config)


def test_check_livekit_requirements_reflects_sdk_availability(monkeypatch):
    monkeypatch.setattr("gateway.platforms.livekit.LIVEKIT_AVAILABLE", True)
    assert check_livekit_requirements() is True

    monkeypatch.setattr("gateway.platforms.livekit.LIVEKIT_AVAILABLE", False)
    assert check_livekit_requirements() is False


@pytest.mark.asyncio
async def test_connect_registers_room_handlers(monkeypatch):
    room = FakeRoom()
    adapter = make_adapter(text_topics=("lk.chat", "hermes.chat"))

    monkeypatch.setattr("gateway.platforms.livekit.LIVEKIT_AVAILABLE", True)
    monkeypatch.setattr(
        "gateway.platforms.livekit.rtc",
        SimpleNamespace(Room=lambda: room),
    )

    connected = await adapter.connect()

    assert connected is True
    room.connect.assert_awaited_once_with("wss://livekit.example.test", "lk-token")
    assert adapter.is_connected is True
    assert sorted(room.text_handlers) == ["hermes.chat", "lk.chat"]
    assert "data_received" in room.handlers
    assert "transcription_received" in room.handlers
    assert "participant_connected" in room.handlers

    await adapter.disconnect()
    room.disconnect.assert_awaited_once()
    assert adapter.is_connected is False


@pytest.mark.asyncio
async def test_send_prefers_livekit_text_streams():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room

    result = await adapter.send(
        "team-room",
        "hello from hermes",
        reply_to="stream-0",
        metadata={
            "destination_identities": ["user-1"],
            "attributes": {"kind": "chat"},
            "topic": "lk.chat",
        },
    )

    assert result.success is True
    assert result.message_id == "stream-1"
    room.local_participant.send_text.assert_awaited_once()
    args = room.local_participant.send_text.await_args
    assert args.args == ("hello from hermes",)
    assert args.kwargs["destination_identities"] == ["user-1"]
    assert args.kwargs["topic"] == "lk.chat"
    assert args.kwargs["attributes"]["kind"] == "chat"
    assert args.kwargs["attributes"]["reply_to"] == "stream-0"


@pytest.mark.asyncio
async def test_send_falls_back_to_data_packets_when_text_streams_are_unavailable():
    room = FakeRoom()
    room.local_participant = SimpleNamespace(publish_data=AsyncMock())
    adapter = make_adapter()
    adapter._room = room

    result = await adapter.send("user-1", "fallback message", reply_to="stream-9")

    assert result.success is True
    room.local_participant.publish_data.assert_awaited_once()
    args = room.local_participant.publish_data.await_args
    payload = args.args[0].decode("utf-8")
    assert '"type": "chat"' in payload
    assert '"reply_to": "stream-9"' in payload
    assert args.kwargs["reliable"] is True
    assert args.kwargs["topic"] == "lk.chat"
    assert args.kwargs["destination_identities"] == ["user-1"]


@pytest.mark.asyncio
async def test_send_typing_uses_lossy_livekit_data_packets():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room

    await adapter.send_typing("team-room", metadata={"destination_identities": ["user-1"]})

    room.local_participant.publish_data.assert_awaited_once()
    args = room.local_participant.publish_data.await_args
    payload = args.args[0].decode("utf-8")
    assert '"type": "typing"' in payload
    assert args.kwargs["reliable"] is False
    assert args.kwargs["topic"] == "hermes.typing"
    assert args.kwargs["destination_identities"] == ["user-1"]


@pytest.mark.asyncio
async def test_get_chat_info_reflects_room_state():
    room = FakeRoom()
    room.remote_participants["user-2"] = FakeParticipant("user-2", name="Grace", sid="PA_user2")
    adapter = make_adapter()
    adapter._room = room

    info = await adapter.get_chat_info("team-room")

    assert info == {
        "name": "team-room",
        "type": "group",
        "participant_count": 3,
        "room_sid": "RM_123",
    }


@pytest.mark.asyncio
async def test_text_streams_are_normalized_into_message_events():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()

    reader = SimpleNamespace(
        info=SimpleNamespace(id="stream-22", topic="lk.chat", attributes={"reply_to": "stream-20"}),
        read_all=AsyncMock(return_value="/status"),
    )

    await adapter._consume_text_stream(reader, "user-1")

    adapter.handle_message.assert_awaited_once()
    event = adapter.handle_message.await_args.args[0]
    assert event.text == "/status"
    assert event.message_type == MessageType.COMMAND
    assert event.message_id == "stream-22"
    assert event.reply_to_message_id == "stream-20"
    assert event.source.chat_id == "team-room"
    assert event.source.chat_type == "dm"
    assert event.source.user_id == "user-1"
    assert event.source.user_name == "Ada"
    assert event.source.chat_topic == "lk.chat"


@pytest.mark.asyncio
async def test_data_packets_are_normalized_into_voice_events_when_marked():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()

    packet = SimpleNamespace(
        data=b'{"type":"chat","text":"transcribed speech","message_type":"voice","reply_to":"stream-10"}',
        topic="lk.chat",
        participant=room.remote_participants["user-1"],
    )

    await adapter._consume_data_packet(packet)

    adapter.handle_message.assert_awaited_once()
    event = adapter.handle_message.await_args.args[0]
    assert event.text == "transcribed speech"
    assert event.message_type == MessageType.VOICE
    assert event.reply_to_message_id == "stream-10"
    assert event.source.user_id == "user-1"
