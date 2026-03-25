"""
Channel directory -- cached map of reachable channels/contacts per platform.

Built on gateway startup, refreshed periodically (every 5 min), and saved to
~/.hermes/channel_directory.json.  The send_message tool reads this file for
action="list" and for resolving human-friendly channel names to numeric IDs.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from hermes_cli.config import get_hermes_home

logger = logging.getLogger(__name__)

DIRECTORY_PATH = get_hermes_home() / "channel_directory.json"


def _session_entry_id(origin: Dict[str, Any]) -> Optional[str]:
    chat_id = origin.get("chat_id")
    if not chat_id:
        return None
    thread_id = origin.get("thread_id")
    if thread_id:
        return f"{chat_id}:{thread_id}"
    return str(chat_id)


def _session_entry_name(origin: Dict[str, Any]) -> str:
    base_name = origin.get("chat_name") or origin.get("user_name") or str(origin.get("chat_id"))
    thread_id = origin.get("thread_id")
    if not thread_id:
        return base_name

    topic_label = origin.get("chat_topic") or f"topic {thread_id}"
    return f"{base_name} / {topic_label}"


def _entry_value(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _stringify_value(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    return str(value)


def _control_context_label(entry: Dict[str, Any]) -> Optional[str]:
    control_platform = entry.get("control_platform")
    control_chat_id = entry.get("control_chat_id")
    if not control_platform or not control_chat_id:
        return None

    control_target = _stringify_value(control_chat_id)
    control_thread_id = entry.get("control_thread_id")
    if control_thread_id:
        control_target = f"{control_target}:{_stringify_value(control_thread_id)}"

    return f"{_stringify_value(control_platform)}:{control_target}"


def _merge_entries_by_id(base_entries: List[Dict[str, Any]], extra_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}

    for entry in base_entries:
        entry_id = entry.get("id")
        if not entry_id:
            continue
        merged.append(entry)
        by_id[entry_id] = entry

    for entry in extra_entries:
        entry_id = entry.get("id")
        if not entry_id:
            continue

        existing = by_id.get(entry_id)
        if existing is None:
            merged.append(entry)
            by_id[entry_id] = entry
            continue

        for key in ("name", "type", "control_platform", "control_chat_id", "control_thread_id"):
            value = entry.get(key)
            if value is None:
                continue
            if key == "name" and existing.get("name") not in (None, "", existing.get("id")):
                continue
            if key == "type" and value != "room" and existing.get("type") not in (None, "", "dm"):
                continue
            existing[key] = value

    return merged


def _build_linked_livekit_rooms() -> List[Dict[str, Any]]:
    try:
        from gateway.room_links import list_room_links
    except ImportError:
        return []

    try:
        records = list_room_links(platform="livekit") or []
    except Exception as e:
        logger.debug("Channel directory: failed to read linked LiveKit rooms: %s", e)
        return []

    entries: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for record in records:
        room_id = _entry_value(record, "room_id")
        room_name = _entry_value(record, "room_name") or room_id
        if not room_id or not room_name:
            continue

        room_id = str(room_id)
        if room_id in seen_ids:
            continue
        seen_ids.add(room_id)

        control_platform = _entry_value(record, "control_platform")
        control_chat_id = _entry_value(record, "control_chat_id")
        control_thread_id = _entry_value(record, "control_thread_id")
        entries.append({
            "id": room_id,
            "name": str(room_name),
            "type": "room",
            "control_platform": _stringify_value(control_platform) if control_platform is not None else None,
            "control_chat_id": _stringify_value(control_chat_id) if control_chat_id is not None else None,
            "control_thread_id": _stringify_value(control_thread_id) if control_thread_id is not None else None,
        })

    return entries


# ---------------------------------------------------------------------------
# Build / refresh
# ---------------------------------------------------------------------------

def build_channel_directory(adapters: Dict[Any, Any]) -> Dict[str, Any]:
    """
    Build a channel directory from connected platform adapters and session data.

    Returns the directory dict and writes it to DIRECTORY_PATH.
    """
    from gateway.config import Platform

    platforms: Dict[str, List[Dict[str, str]]] = {}

    for platform, adapter in adapters.items():
        try:
            if platform == Platform.DISCORD:
                platforms["discord"] = _build_discord(adapter)
            elif platform == Platform.SLACK:
                platforms["slack"] = _build_slack(adapter)
        except Exception as e:
            logger.warning("Channel directory: failed to build %s: %s", platform.value, e)

    # Telegram, WhatsApp, Signal, and LiveKit can't enumerate chats directly -- pull from session history
    for plat_name in ("telegram", "whatsapp", "signal", "email", "sms", "livekit"):
        if plat_name not in platforms:
            platforms[plat_name] = _build_from_sessions(plat_name)

    livekit_rooms = _build_linked_livekit_rooms()
    if livekit_rooms:
        platforms["livekit"] = _merge_entries_by_id(platforms.get("livekit", []), livekit_rooms)

    directory = {
        "updated_at": datetime.now().isoformat(),
        "platforms": platforms,
    }

    try:
        DIRECTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DIRECTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(directory, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("Channel directory: failed to write: %s", e)

    return directory


def _build_discord(adapter) -> List[Dict[str, str]]:
    """Enumerate all text channels the Discord bot can see."""
    channels = []
    client = getattr(adapter, "_client", None)
    if not client:
        return channels

    try:
        import discord as _discord  # noqa: F401 — SDK presence check
    except ImportError:
        return channels

    for guild in client.guilds:
        for ch in guild.text_channels:
            channels.append({
                "id": str(ch.id),
                "name": ch.name,
                "guild": guild.name,
                "type": "channel",
            })
        # Also include DM-capable users we've interacted with is not
        # feasible via guild enumeration; those come from sessions.

    # Merge any DMs from session history
    channels.extend(_build_from_sessions("discord"))
    return channels


def _build_slack(adapter) -> List[Dict[str, str]]:
    """List Slack channels the bot has joined."""
    channels = []
    # Slack adapter may expose a web client
    client = getattr(adapter, "_app", None) or getattr(adapter, "_client", None)
    if not client:
        return _build_from_sessions("slack")

    try:
        from tools.send_message_tool import _send_slack  # noqa: F401
        # Use the Slack Web API directly if available
    except Exception:
        pass

    # Fallback to session data
    return _build_from_sessions("slack")


def _build_from_sessions(platform_name: str) -> List[Dict[str, str]]:
    """Pull known channels/contacts from sessions.json origin data."""
    sessions_path = get_hermes_home() / "sessions" / "sessions.json"
    if not sessions_path.exists():
        return []

    entries = []
    try:
        with open(sessions_path, encoding="utf-8") as f:
            data = json.load(f)

        seen_ids = set()
        for _key, session in data.items():
            origin = session.get("origin") or {}
            if origin.get("platform") != platform_name:
                continue
            entry_id = _session_entry_id(origin)
            if not entry_id or entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            entries.append({
                "id": entry_id,
                "name": _session_entry_name(origin),
                "type": session.get("chat_type", "dm"),
                "thread_id": origin.get("thread_id"),
            })
    except Exception as e:
        logger.debug("Channel directory: failed to read sessions for %s: %s", platform_name, e)

    return entries


# ---------------------------------------------------------------------------
# Read / resolve
# ---------------------------------------------------------------------------

def load_directory() -> Dict[str, Any]:
    """Load the cached channel directory from disk."""
    if not DIRECTORY_PATH.exists():
        return {"updated_at": None, "platforms": {}}
    try:
        with open(DIRECTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": None, "platforms": {}}


def resolve_channel_name(platform_name: str, name: str) -> Optional[str]:
    """
    Resolve a human-friendly channel name to a numeric ID.

    Matching strategy (case-insensitive, first match wins):
    - Discord: "bot-home", "#bot-home", "GuildName/bot-home"
    - Telegram: display name or group name
    - Slack: "engineering", "#engineering"
    """
    directory = load_directory()
    channels = directory.get("platforms", {}).get(platform_name, [])
    if not channels:
        return None

    query = name.lstrip("#").lower()

    # 0. Exact ID match
    for ch in channels:
        if str(ch.get("id", "")).lower() == query:
            return ch["id"]

    # 1. Exact name match
    for ch in channels:
        if ch["name"].lower() == query:
            return ch["id"]

    # 2. Guild-qualified match for Discord ("GuildName/channel")
    if "/" in query:
        guild_part, ch_part = query.rsplit("/", 1)
        for ch in channels:
            guild = ch.get("guild", "").lower()
            if guild == guild_part and ch["name"].lower() == ch_part:
                return ch["id"]

    # 3. Partial prefix match (only if unambiguous)
    matches = [ch for ch in channels if ch["name"].lower().startswith(query)]
    if len(matches) == 1:
        return matches[0]["id"]

    return None


def format_directory_for_display() -> str:
    """Format the channel directory as a human-readable list for the model."""
    directory = load_directory()
    platforms = directory.get("platforms", {})

    if not any(platforms.values()):
        return "No messaging platforms connected or no channels discovered yet."

    lines = ["Available messaging targets:\n"]

    for plat_name, channels in sorted(platforms.items()):
        if not channels:
            continue

        # Group Discord channels by guild
        if plat_name == "discord":
            guilds: Dict[str, List] = {}
            dms: List = []
            for ch in channels:
                guild = ch.get("guild")
                if guild:
                    guilds.setdefault(guild, []).append(ch)
                else:
                    dms.append(ch)

            for guild_name, guild_channels in sorted(guilds.items()):
                lines.append(f"Discord ({guild_name}):")
                for ch in sorted(guild_channels, key=lambda c: c["name"]):
                    lines.append(f"  discord:#{ch['name']}")
            if dms:
                lines.append("Discord (DMs):")
                for ch in dms:
                    lines.append(f"  discord:{ch['name']}")
            lines.append("")
        else:
            label = "LiveKit" if plat_name == "livekit" else plat_name.title()
            lines.append(f"{label}:")
            for ch in channels:
                type_label = f" ({ch['type']})" if ch.get("type") else ""
                control_label = _control_context_label(ch)
                linked_label = f" [linked to {control_label}]" if control_label else ""
                lines.append(f"  {plat_name}:{ch['name']}{type_label}{linked_label}")
            lines.append("")

    lines.append('Use these as the "target" parameter when sending.')
    lines.append('Bare platform name (e.g. "telegram") sends to home channel.')

    return "\n".join(lines)
