# ABOUTME: Focused tests for the LiveKit gateway adapter's room wiring and event normalization.
# ABOUTME: Covers connection hooks, outbound publishing, typing packets, chat info, and MessageEvent creation.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from gateway.platforms.livekit import LiveKitAdapter, check_livekit_requirements
from gateway.session import build_session_key


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
async def test_connect_mirrors_linked_room_status_into_control_session(monkeypatch):
    room = FakeRoom()
    adapter = make_adapter()
    mirror = MagicMock(return_value=True)

    monkeypatch.setattr("gateway.platforms.livekit.LIVEKIT_AVAILABLE", True)
    monkeypatch.setattr(
        "gateway.platforms.livekit.rtc",
        SimpleNamespace(Room=lambda: room),
    )
    monkeypatch.setattr(
        "gateway.platforms.livekit.get_room_link",
        lambda platform, room_id: {
            "room_id": "team-room",
            "room_name": "Team Room",
            "control_platform": "discord",
            "control_chat_id": "discord-control",
            "control_thread_id": "thread-7",
        } if room_id == "team-room" else None,
    )
    monkeypatch.setattr("gateway.platforms.livekit.mirror_to_session", mirror)

    connected = await adapter.connect()

    assert connected is True
    mirror.assert_called_once_with(
        "discord",
        "discord-control",
        "[LiveKit status] Room connected: team-room",
        source_label="livekit",
        thread_id="thread-7",
        linked_chat_id="team-room",
    )


def test_room_disconnect_mirrors_linked_status_into_control_session(monkeypatch):
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter._manual_disconnect = True
    mirror = MagicMock(return_value=True)

    monkeypatch.setattr(
        "gateway.platforms.livekit.get_room_link",
        lambda platform, room_id: {
            "room_id": "team-room",
            "control_platform": "discord",
            "control_chat_id": "discord-control",
            "control_thread_id": "thread-7",
        } if room_id == "team-room" else None,
    )
    monkeypatch.setattr("gateway.platforms.livekit.mirror_to_session", mirror)

    adapter._on_room_disconnected("transport_restart")

    mirror.assert_called_once_with(
        "discord",
        "discord-control",
        "[LiveKit status] Room disconnected: team-room (transport_restart)",
        source_label="livekit",
        thread_id="thread-7",
        linked_chat_id="team-room",
    )


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
    assert event.source.user_id_alt == "user-1"
    assert event.source.chat_id_alt == "RM_123"
    assert event.source.chat_topic == "lk.chat"


@pytest.mark.asyncio
async def test_data_packets_are_normalized_into_synthetic_text_events_when_marked_as_voice():
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
    assert event.message_type == MessageType.TEXT
    assert event.reply_to_message_id == "stream-10"
    assert event.source.user_id == "user-1"
    assert event.source.user_id_alt == "user-1"


@pytest.mark.asyncio
async def test_transcriptions_become_synthetic_text_message_events():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()

    segments = [
        SimpleNamespace(text="first"),
        SimpleNamespace(text="second"),
    ]

    await adapter._consume_transcription(segments, room.remote_participants["user-1"])

    adapter.handle_message.assert_awaited_once()
    event = adapter.handle_message.await_args.args[0]
    assert event.text == "first second"
    assert event.message_type == MessageType.TEXT
    assert event.source.chat_id == "team-room"
    assert event.source.user_id == "user-1"
    assert event.source.user_id_alt == "user-1"
    assert event.source.chat_topic == "transcription"


@pytest.mark.asyncio
async def test_transcriptions_mirror_into_linked_control_session(monkeypatch):
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()
    mirror = MagicMock(return_value=True)

    monkeypatch.setattr(
        "gateway.platforms.livekit.get_room_link",
        lambda platform, room_id: {
            "room_id": "team-room",
            "control_platform": "discord",
            "control_chat_id": "discord-control",
            "control_thread_id": "thread-9",
        } if room_id == "team-room" else None,
    )
    monkeypatch.setattr("gateway.platforms.livekit.mirror_to_session", mirror)

    await adapter._consume_transcription(
        [SimpleNamespace(text="linked"), SimpleNamespace(text="transcript")],
        room.remote_participants["user-1"],
    )

    mirror.assert_called_once_with(
        "discord",
        "discord-control",
        "[LiveKit transcript] Ada: linked transcript",
        source_label="livekit",
        thread_id="thread-9",
        linked_chat_id="team-room",
    )


@pytest.mark.asyncio
async def test_unlinked_transcriptions_do_not_mirror(monkeypatch):
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()
    mirror = MagicMock(return_value=True)

    monkeypatch.setattr("gateway.platforms.livekit.get_room_link", lambda platform, room_id: None)
    monkeypatch.setattr("gateway.platforms.livekit.mirror_to_session", mirror)

    await adapter._consume_transcription(
        [SimpleNamespace(text="room-local-only")],
        room.remote_participants["user-1"],
    )

    mirror.assert_not_called()


@pytest.mark.asyncio
async def test_same_participant_in_same_room_reuses_session_key():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()

    reader = SimpleNamespace(
        info=SimpleNamespace(id="stream-1", topic="lk.chat", attributes={}),
        read_all=AsyncMock(return_value="hello"),
    )
    packet = SimpleNamespace(
        data=b'{"type":"chat","text":"follow up"}',
        topic="lk.chat",
        participant=room.remote_participants["user-1"],
    )

    await adapter._consume_text_stream(reader, "user-1")
    await adapter._consume_data_packet(packet)

    first_event, second_event = [call.args[0] for call in adapter.handle_message.await_args_list]
    assert build_session_key(first_event.source) == build_session_key(second_event.source)
    assert first_event.source.chat_id == second_event.source.chat_id == "team-room"
    assert first_event.source.user_id_alt == second_event.source.user_id_alt == "user-1"
    assert first_event.source.chat_id_alt == second_event.source.chat_id_alt == "RM_123"


@pytest.mark.asyncio
async def test_local_publications_are_ignored_on_ingress():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter.handle_message = AsyncMock()

    local_reader = SimpleNamespace(
        info=SimpleNamespace(id="stream-local", topic="lk.chat", attributes={}),
        read_all=AsyncMock(return_value="self echo"),
    )
    local_packet = SimpleNamespace(
        data=b'{"type":"chat","text":"self echo"}',
        topic="lk.chat",
        participant=room.local_participant,
    )

    await adapter._consume_text_stream(local_reader, "hermes")
    await adapter._consume_data_packet(local_packet)
    await adapter._consume_transcription([SimpleNamespace(text="self echo")], room.local_participant)

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_room_disconnect_retries_after_clearing_stale_state():
    room = FakeRoom()
    adapter = make_adapter(
        max_reconnect_attempts=2,
        reconnect_initial_delay_seconds=0,
        reconnect_max_delay_seconds=0,
    )
    adapter._room = room
    adapter._participants["user-1"] = {
        "identity": "user-1",
        "sid": "PA_user1",
        "name": "Ada",
        "metadata": None,
        "attributes": {},
        "participant": room.remote_participants["user-1"],
    }
    stale_task = asyncio.create_task(asyncio.sleep(60))
    adapter._room_tasks.add(stale_task)
    adapter._mark_connected()

    observed_states = []

    async def fake_connect():
        observed_states.append(
            {
                "room": adapter._room,
                "participants": dict(adapter._participants),
                "stale_task_done": stale_task.done(),
            }
        )
        if len(observed_states) == 1:
            return False
        adapter._mark_connected()
        return True

    adapter.connect = AsyncMock(side_effect=fake_connect)

    adapter._on_room_disconnected("transport_restart")

    await asyncio.wait_for(adapter._reconnect_task, 1)

    assert adapter.connect.await_count == 2
    assert observed_states[0] == {
        "room": None,
        "participants": {},
        "stale_task_done": True,
    }
    assert adapter.is_connected is True
    assert adapter._reconnect_task is None


@pytest.mark.asyncio
async def test_disconnect_cancels_reconnect_and_clears_room_state():
    room = FakeRoom()
    adapter = make_adapter()
    adapter._room = room
    adapter._participants["user-1"] = {
        "identity": "user-1",
        "sid": "PA_user1",
        "name": "Ada",
        "metadata": None,
        "attributes": {},
        "participant": room.remote_participants["user-1"],
    }
    adapter._reconnect_task = asyncio.create_task(asyncio.sleep(60))

    await adapter.disconnect()

    room.disconnect.assert_awaited_once()
    assert adapter._room is None
    assert adapter._participants == {}
    assert adapter._reconnect_task is None
    assert adapter.is_connected is False
