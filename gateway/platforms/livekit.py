# ABOUTME: LiveKit gateway adapter for Hermes room-based text, data, and transcription events.
# ABOUTME: Normalizes LiveKit room activity into MessageEvent objects and publishes Hermes replies back into the room.

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger(__name__)

try:
    from livekit import rtc

    LIVEKIT_AVAILABLE = True
except ImportError:
    rtc = None
    LIVEKIT_AVAILABLE = False


class _LiveKitPlatformFallback(Enum):
    LIVEKIT = "livekit"


LIVEKIT_PLATFORM = getattr(Platform, "LIVEKIT", _LiveKitPlatformFallback.LIVEKIT)

LIVEKIT_CHAT_TOPIC = "lk.chat"
LIVEKIT_TYPING_TOPIC = "hermes.typing"


def check_livekit_requirements() -> bool:
    """Return True when the LiveKit realtime SDK is importable."""
    return LIVEKIT_AVAILABLE


class LiveKitAdapter(BasePlatformAdapter):
    """Gateway adapter for Hermes sessions carried over a LiveKit room."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config, LIVEKIT_PLATFORM)
        self._url: str = (
            config.extra.get("url", "")
            or os.getenv("LIVEKIT_URL", "")
        ).rstrip("/")
        self._token: str = config.token or config.extra.get("token", "") or os.getenv("LIVEKIT_TOKEN", "")
        self._configured_room_name: str = (
            config.extra.get("room_name", "")
            or os.getenv("LIVEKIT_ROOM_NAME", "")
        )
        self._chat_topic: str = config.extra.get("chat_topic", LIVEKIT_CHAT_TOPIC)
        self._typing_topic: str = config.extra.get("typing_topic", LIVEKIT_TYPING_TOPIC)
        self._text_topics: tuple[str, ...] = tuple(
            config.extra.get("text_topics", (self._chat_topic,))
        ) or (self._chat_topic,)
        self._room: Any = None
        self._room_tasks: set[asyncio.Task] = set()
        self._participants: Dict[str, Dict[str, Any]] = {}
        self._manual_disconnect = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._max_reconnect_attempts = max(
            1,
            int(config.extra.get("max_reconnect_attempts", 3) or 3),
        )
        self._reconnect_initial_delay_seconds = max(
            0.0,
            float(config.extra.get("reconnect_initial_delay_seconds", 1.0) or 0.0),
        )
        self._reconnect_max_delay_seconds = max(
            self._reconnect_initial_delay_seconds,
            float(config.extra.get("reconnect_max_delay_seconds", 8.0) or 0.0),
        )

    @property
    def name(self) -> str:
        return "LiveKit"

    async def connect(self) -> bool:
        """Connect to the configured LiveKit room and register room callbacks."""
        self._manual_disconnect = False
        if not LIVEKIT_AVAILABLE:
            logger.error("[LiveKit] livekit package not installed")
            return False
        if not self._url:
            logger.error("[LiveKit] LIVEKIT_URL not configured")
            return False
        if not self._token:
            logger.error("[LiveKit] LiveKit access token not configured")
            return False

        current_task = asyncio.current_task()
        if self._reconnect_task is not None and self._reconnect_task is not current_task:
            await self._cancel_reconnect_task()
        if self._room is not None or self._room_tasks:
            await self._reset_room_state(disconnect_room=False)

        try:
            self._room = rtc.Room()
            self._register_room_handlers(self._room)
            await self._room.connect(self._url, self._token)
            self._snapshot_room_participants()
            self._mark_connected()
            logger.info(
                "[LiveKit] Connected to room=%s url=%s",
                self._resolved_room_name(),
                self._url,
            )
            return True
        except Exception as exc:
            self._room = None
            message = f"LiveKit connect failed: {exc}"
            self._set_fatal_error("livekit_connect_error", message, retryable=True)
            logger.error("[LiveKit] %s", message, exc_info=True)
            return False

    async def disconnect(self) -> None:
        """Leave the room and stop background event tasks."""
        self._manual_disconnect = True
        await self._cancel_reconnect_task()
        await self._reset_room_state(disconnect_room=True)

        self._mark_disconnected()
        logger.info("[LiveKit] Disconnected")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send Hermes text back through LiveKit text streams or data packets."""
        local_participant = self._local_participant()
        if local_participant is None:
            return SendResult(success=False, error="Not connected")

        metadata = metadata or {}
        destination_identities = self._resolve_destination_identities(chat_id, metadata)
        attributes = dict(metadata.get("attributes", {}) or {})
        if reply_to:
            attributes.setdefault("reply_to", str(reply_to))

        try:
            if hasattr(local_participant, "send_text"):
                send_kwargs: Dict[str, Any] = {"topic": metadata.get("topic", self._chat_topic)}
                if destination_identities:
                    send_kwargs["destination_identities"] = destination_identities
                if attributes:
                    send_kwargs["attributes"] = attributes
                sender_identity = metadata.get("sender_identity")
                if sender_identity:
                    send_kwargs["sender_identity"] = sender_identity
                info = await local_participant.send_text(content, **send_kwargs)
                return SendResult(
                    success=True,
                    message_id=str(
                        getattr(info, "stream_id", None)
                        or getattr(info, "id", None)
                        or ""
                    )
                    or None,
                    raw_response=info,
                )

            payload = {
                "type": "chat",
                "text": content,
                "attributes": attributes,
            }
            if reply_to:
                payload["reply_to"] = str(reply_to)

            publish_kwargs: Dict[str, Any] = {
                "reliable": True,
                "topic": metadata.get("topic", self._chat_topic),
            }
            if destination_identities:
                publish_kwargs["destination_identities"] = destination_identities
            await local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                **publish_kwargs,
            )
            return SendResult(success=True)
        except Exception as exc:
            logger.error("[LiveKit] send failed: %s", exc, exc_info=True)
            return SendResult(success=False, error=str(exc))

    async def send_typing(
        self,
        chat_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publish a lossy typing packet to the same room destination set."""
        local_participant = self._local_participant()
        if local_participant is None or not hasattr(local_participant, "publish_data"):
            return

        metadata = metadata or {}
        payload = {
            "type": "typing",
            "active": True,
            "chat_id": chat_id,
        }
        destination_identities = self._resolve_destination_identities(chat_id, metadata)
        publish_kwargs: Dict[str, Any] = {
            "reliable": False,
            "topic": metadata.get("topic", self._typing_topic),
        }
        if destination_identities:
            publish_kwargs["destination_identities"] = destination_identities
        try:
            await local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                **publish_kwargs,
            )
        except Exception as exc:
            logger.debug("[LiveKit] typing publish failed: %s", exc, exc_info=True)

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Return room-level chat metadata used by Hermes session routing."""
        room = self._room
        room_name = self._resolved_room_name() or chat_id
        participant_count = self._participant_count()
        room_sid = getattr(room, "sid", None) if room is not None else None
        return {
            "name": room_name,
            "type": "dm" if participant_count <= 2 else "group",
            "participant_count": participant_count,
            "room_sid": room_sid,
        }

    def _register_room_handlers(self, room: Any) -> None:
        """Bind LiveKit callbacks for text, data, and transcription events."""
        if hasattr(room, "on"):
            room.on("participant_connected", self._on_participant_connected)
            room.on("participant_disconnected", self._on_participant_disconnected)
            room.on("participant_attributes_changed", self._on_participant_attributes_changed)
            room.on("participant_metadata_changed", self._on_participant_metadata_changed)
            room.on("data_received", self._on_data_received)
            room.on("transcription_received", self._on_transcription_received)
            room.on("disconnected", self._on_room_disconnected)

        if hasattr(room, "register_text_stream_handler"):
            for topic in self._text_topics:
                room.register_text_stream_handler(topic, self._on_text_stream)

    def _on_participant_connected(self, participant: Any) -> None:
        self._remember_participant(participant)

    def _on_participant_disconnected(self, participant: Any) -> None:
        identity = self._participant_identity(participant)
        if identity:
            self._participants.pop(identity, None)

    def _on_participant_attributes_changed(self, changed_attributes: Dict[str, str], participant: Any) -> None:
        del changed_attributes
        self._remember_participant(participant)

    def _on_participant_metadata_changed(self, participant: Any, old_metadata: str, new_metadata: str) -> None:
        del old_metadata, new_metadata
        self._remember_participant(participant)

    def _on_room_disconnected(self, reason: Any) -> None:
        logger.info("[LiveKit] room disconnected reason=%s", reason)
        self._mark_disconnected()
        if self._manual_disconnect:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._run_reconnect_loop(reason))

    def _on_text_stream(self, reader: Any, participant_identity: str) -> None:
        self._track_task(
            self._consume_text_stream(reader, participant_identity),
        )

    def _on_data_received(self, data_packet: Any) -> None:
        self._track_task(
            self._consume_data_packet(data_packet),
        )

    def _on_transcription_received(self, segments: Iterable[Any], participant: Any, publication: Any) -> None:
        del publication
        self._track_task(
            self._consume_transcription(segments, participant),
        )

    async def _consume_text_stream(self, reader: Any, participant_identity: str) -> None:
        if self._is_local_identity(participant_identity):
            return
        text = (await reader.read_all()).strip()
        if not text:
            return

        info = getattr(reader, "info", None)
        participant = self._participant_by_identity(participant_identity)
        event = self._build_message_event(
            text=text,
            participant=participant,
            raw_message=reader,
            message_type=MessageType.COMMAND if text.startswith("/") else MessageType.TEXT,
            message_id=self._stream_info_id(info),
            chat_topic=self._stream_info_topic(info),
            reply_to_message_id=self._stream_info_reply_to(info),
        )
        await self.handle_message(event)

    async def _consume_data_packet(self, data_packet: Any) -> None:
        payload = self._parse_data_payload(getattr(data_packet, "data", b""))
        if payload is None:
            return

        topic = getattr(data_packet, "topic", None)
        if isinstance(payload, dict) and payload.get("type") == "typing":
            return

        if isinstance(payload, dict):
            text = str(payload.get("text", "") or "").strip()
            reply_to = payload.get("reply_to")
        else:
            text = payload.strip()
            reply_to = None

        if not text:
            return

        participant = getattr(data_packet, "participant", None)
        if self._is_local_participant(participant):
            return
        event = self._build_message_event(
            text=text,
            participant=participant,
            raw_message=data_packet,
            message_type=MessageType.COMMAND if text.startswith("/") else MessageType.TEXT,
            message_id=self._message_id_from_packet(data_packet),
            chat_topic=topic,
            reply_to_message_id=str(reply_to) if reply_to else None,
        )
        await self.handle_message(event)

    async def _consume_transcription(self, segments: Iterable[Any], participant: Any) -> None:
        if self._is_local_participant(participant):
            return
        text = " ".join(
            self._strip_segment_text(getattr(segment, "text", ""))
            for segment in segments
        ).strip()
        if not text:
            return

        event = self._build_message_event(
            text=text,
            participant=participant,
            raw_message=list(segments),
            message_type=MessageType.COMMAND if text.startswith("/") else MessageType.TEXT,
            message_id=None,
            chat_topic="transcription",
        )
        await self.handle_message(event)

    def _build_message_event(
        self,
        *,
        text: str,
        participant: Any,
        raw_message: Any,
        message_type: MessageType,
        message_id: Optional[str],
        chat_topic: Optional[str],
        reply_to_message_id: Optional[str] = None,
    ) -> MessageEvent:
        source = self.build_source(
            chat_id=self._resolved_room_name(),
            chat_name=self._resolved_room_name(),
            chat_type="dm" if self._participant_count() <= 2 else "group",
            user_id=self._participant_identity(participant),
            user_name=self._participant_name(participant),
            chat_topic=chat_topic,
            user_id_alt=self._participant_session_identity(participant),
            chat_id_alt=self._resolved_room_sid(),
        )
        return MessageEvent(
            text=text,
            message_type=message_type,
            source=source,
            raw_message=raw_message,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
            timestamp=datetime.now(timezone.utc),
        )

    def _track_task(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._room_tasks.add(task)
        task.add_done_callback(self._room_tasks.discard)

    async def _cancel_reconnect_task(self) -> None:
        reconnect_task = self._reconnect_task
        if reconnect_task is None:
            return
        self._reconnect_task = None
        if reconnect_task.done() or reconnect_task is asyncio.current_task():
            return
        reconnect_task.cancel()
        await asyncio.gather(reconnect_task, return_exceptions=True)

    async def _reset_room_state(self, *, disconnect_room: bool) -> None:
        room = self._room
        room_tasks = [task for task in self._room_tasks if task is not asyncio.current_task()]
        for task in room_tasks:
            task.cancel()
        if room_tasks:
            await asyncio.gather(*room_tasks, return_exceptions=True)
        self._room_tasks.clear()
        self._participants.clear()
        self._room = None
        if disconnect_room and room is not None:
            try:
                await room.disconnect()
            except Exception as exc:
                logger.warning("[LiveKit] disconnect failed: %s", exc, exc_info=True)

    async def _run_reconnect_loop(self, reason: Any) -> None:
        try:
            await self._reset_room_state(disconnect_room=False)
            delay = self._reconnect_initial_delay_seconds
            for attempt in range(1, self._max_reconnect_attempts + 1):
                if self._manual_disconnect:
                    return
                if delay > 0:
                    await asyncio.sleep(delay)
                logger.info(
                    "[LiveKit] reconnect attempt %s/%s after reason=%s",
                    attempt,
                    self._max_reconnect_attempts,
                    reason,
                )
                if await self.connect():
                    return
                delay = min(
                    max(delay * 2, self._reconnect_initial_delay_seconds or 0.0),
                    self._reconnect_max_delay_seconds,
                )
            logger.warning(
                "[LiveKit] reconnect exhausted after %s attempts",
                self._max_reconnect_attempts,
            )
        finally:
            if self._reconnect_task is asyncio.current_task():
                self._reconnect_task = None

    def _snapshot_room_participants(self) -> None:
        room = self._room
        if room is None:
            return

        local_participant = getattr(room, "local_participant", None)
        if local_participant is not None:
            self._remember_participant(local_participant)

        for participant in getattr(room, "remote_participants", {}).values():
            self._remember_participant(participant)

    def _remember_participant(self, participant: Any) -> None:
        identity = self._participant_identity(participant)
        if not identity:
            return
        self._participants[identity] = {
            "identity": identity,
            "sid": self._participant_sid(participant),
            "name": self._participant_name(participant),
            "metadata": getattr(participant, "metadata", None),
            "attributes": dict(getattr(participant, "attributes", {}) or {}),
            "participant": participant,
        }

    def _participant_by_identity(self, identity: Optional[str]) -> Any:
        if not identity:
            return None
        cached = self._participants.get(identity)
        if cached:
            return cached["participant"]

        room = self._room
        if room is None:
            return None

        remote = getattr(room, "remote_participants", {}).get(identity)
        if remote is not None:
            self._remember_participant(remote)
            return remote

        local = getattr(room, "local_participant", None)
        if self._participant_identity(local) == identity:
            self._remember_participant(local)
            return local
        return None

    def _is_local_identity(self, participant_identity: Optional[str]) -> bool:
        return bool(
            participant_identity
            and participant_identity == self._participant_identity(self._local_participant())
        )

    def _is_local_participant(self, participant: Any) -> bool:
        return self._is_local_identity(self._participant_identity(participant))

    def _resolve_destination_identities(
        self,
        chat_id: str,
        metadata: Dict[str, Any],
    ) -> list[str]:
        raw = metadata.get("destination_identities") or metadata.get("destination_identity")
        if raw:
            if isinstance(raw, str):
                return [raw]
            return [str(item) for item in raw if item]

        if chat_id and chat_id not in {self._resolved_room_name(), self._resolved_room_sid()}:
            return [chat_id]
        return []

    def _resolved_room_name(self) -> str:
        room = self._room
        return getattr(room, "name", None) or self._configured_room_name or "livekit-room"

    def _resolved_room_sid(self) -> Optional[str]:
        room = self._room
        return getattr(room, "sid", None) if room is not None else None

    def _participant_count(self) -> int:
        room = self._room
        if room is None:
            return 1
        remote_participants = getattr(room, "remote_participants", {}) or {}
        local_participant = getattr(room, "local_participant", None)
        return len(remote_participants) + (1 if local_participant is not None else 0)

    def _local_participant(self) -> Any:
        room = self._room
        if room is None:
            return None
        return getattr(room, "local_participant", None)

    @staticmethod
    def _participant_identity(participant: Any) -> Optional[str]:
        if participant is None:
            return None
        identity = getattr(participant, "identity", None)
        return str(identity) if identity else None

    @staticmethod
    def _participant_sid(participant: Any) -> Optional[str]:
        if participant is None:
            return None
        sid = getattr(participant, "sid", None)
        return str(sid) if sid else None

    def _participant_session_identity(self, participant: Any) -> Optional[str]:
        cached = self._participants.get(self._participant_identity(participant) or "")
        attributes = cached["attributes"] if cached else dict(getattr(participant, "attributes", {}) or {})
        for key in ("hermes_session_identity", "session_identity", "identity"):
            value = attributes.get(key)
            if value:
                return str(value)
        return self._participant_identity(participant)

    @staticmethod
    def _participant_name(participant: Any) -> Optional[str]:
        if participant is None:
            return None
        name = getattr(participant, "name", None) or getattr(participant, "identity", None)
        return str(name) if name else None

    @staticmethod
    def _stream_info_id(info: Any) -> Optional[str]:
        if info is None:
            return None
        value = getattr(info, "id", None) or getattr(info, "stream_id", None)
        return str(value) if value else None

    @staticmethod
    def _stream_info_topic(info: Any) -> Optional[str]:
        if info is None:
            return None
        topic = getattr(info, "topic", None)
        return str(topic) if topic else None

    @staticmethod
    def _stream_info_reply_to(info: Any) -> Optional[str]:
        if info is None:
            return None
        attributes = dict(getattr(info, "attributes", {}) or {})
        reply_to = attributes.get("reply_to")
        return str(reply_to) if reply_to else None

    @staticmethod
    def _parse_data_payload(raw_data: bytes) -> Optional[str | Dict[str, Any]]:
        if not raw_data:
            return None
        try:
            decoded = raw_data.decode("utf-8")
        except Exception:
            return None
        decoded = decoded.strip()
        if not decoded:
            return None
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError:
            return decoded
        return parsed if isinstance(parsed, dict) else decoded

    @staticmethod
    def _message_id_from_packet(data_packet: Any) -> Optional[str]:
        for attr in ("id", "packet_id", "stream_id"):
            value = getattr(data_packet, attr, None)
            if value:
                return str(value)
        return None

    @staticmethod
    def _strip_segment_text(text: str) -> str:
        return str(text or "").strip()
