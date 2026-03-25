# ABOUTME: Durable gateway registry for LiveKit room to Discord link records.
# ABOUTME: Stores the smallest JSON-backed map needed for room and control lookups.

import json
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from hermes_cli.config import get_hermes_home

ROOM_LINKS_PATH = get_hermes_home() / "room_links.json"


def _normalize_platform(value: Any) -> str:
    platform = getattr(value, "value", value)
    if platform is None:
        raise ValueError("platform must be provided")
    text = str(platform).strip()
    if not text:
        raise ValueError("platform must be provided")
    return text.lower()


def _required_text(value: Any, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} must be provided")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be provided")
    return text


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _default_state() -> Dict[str, Any]:
    return {"updated_at": None, "room_links": []}


def _normalize_state(data: Any) -> Dict[str, Any]:
    if isinstance(data, list):
        links = data
        updated_at = None
    elif isinstance(data, dict):
        links = data.get("room_links")
        if links is None and isinstance(data.get("links"), list):
            links = data.get("links")
        updated_at = data.get("updated_at")
    else:
        return _default_state()

    if not isinstance(links, list):
        links = []

    normalized_links = [link for link in links if isinstance(link, dict)]
    return {"updated_at": updated_at, "room_links": normalized_links}


def _load_state() -> Dict[str, Any]:
    if not ROOM_LINKS_PATH.exists():
        return _default_state()

    try:
        with open(ROOM_LINKS_PATH, encoding="utf-8") as f:
            return _normalize_state(json.load(f))
    except Exception:
        return _default_state()


def _save_state(state: Dict[str, Any]) -> None:
    ROOM_LINKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(ROOM_LINKS_PATH.parent),
        suffix=".tmp",
        prefix=".room_links_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ROOM_LINKS_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _matches_room(link: Dict[str, Any], platform: str, room_id: str) -> bool:
    return (
        _normalize_platform(link.get("platform")) == platform
        and str(link.get("room_id")) == room_id
    )


def _matches_control(
    link: Dict[str, Any],
    control_platform: str,
    control_chat_id: str,
    control_thread_id: Optional[str],
) -> bool:
    return (
        _normalize_platform(link.get("control_platform")) == control_platform
        and str(link.get("control_chat_id")) == control_chat_id
        and _optional_text(link.get("control_thread_id")) == control_thread_id
    )


def _pick_latest(matches: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not matches:
        return None

    best = None
    best_updated = ""
    for link in matches:
        updated = str(link.get("updated_at") or "")
        if updated >= best_updated:
            best_updated = updated
            best = link
    return dict(best) if best is not None else None


def save_room_link(
    platform: str,
    room_id: str,
    room_name: str,
    control_platform: str,
    control_chat_id: str,
    control_thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save a durable LiveKit-to-control-channel association.

    The registry is one-to-one:
    - a room_id maps to one control context
    - a control context maps to one room_id
    """
    room_platform = _normalize_platform(platform)
    room_id_text = _required_text(room_id, "room_id")
    room_name_text = _required_text(room_name, "room_name")
    control_platform_text = _normalize_platform(control_platform)
    control_chat_id_text = _required_text(control_chat_id, "control_chat_id")
    control_thread_id_text = _optional_text(control_thread_id)

    state = _load_state()
    now = datetime.now().isoformat()
    kept_links: List[Dict[str, Any]] = []
    created_at = None

    for link in state["room_links"]:
        same_room = _matches_room(link, room_platform, room_id_text)
        same_control = _matches_control(
            link,
            control_platform_text,
            control_chat_id_text,
            control_thread_id_text,
        )
        if same_room or same_control:
            if created_at is None:
                created_at = link.get("created_at")
            continue
        kept_links.append(link)

    record = {
        "platform": room_platform,
        "room_id": room_id_text,
        "room_name": room_name_text,
        "control_platform": control_platform_text,
        "control_chat_id": control_chat_id_text,
        "control_thread_id": control_thread_id_text,
        "created_at": created_at or now,
        "updated_at": now,
    }
    kept_links.append(record)

    state["room_links"] = kept_links
    state["updated_at"] = now
    _save_state(state)
    return dict(record)


def get_room_link(platform: str, room_id: str) -> Optional[Dict[str, Any]]:
    """Look up a link by room identity."""
    room_platform = _normalize_platform(platform)
    room_id_text = _required_text(room_id, "room_id")
    state = _load_state()
    matches = [
        link
        for link in state["room_links"]
        if _matches_room(link, room_platform, room_id_text)
    ]
    return _pick_latest(matches)


def find_room_link(
    control_platform: str,
    control_chat_id: str,
    control_thread_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up a link by Discord control channel or thread identity."""
    control_platform_text = _normalize_platform(control_platform)
    control_chat_id_text = _required_text(control_chat_id, "control_chat_id")
    control_thread_id_text = _optional_text(control_thread_id)
    state = _load_state()
    matches = [
        link
        for link in state["room_links"]
        if _matches_control(
            link,
            control_platform_text,
            control_chat_id_text,
            control_thread_id_text,
        )
    ]
    return _pick_latest(matches)


def list_room_links(platform: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all saved room links, optionally filtered by room platform."""
    state = _load_state()
    if platform is None:
        return [dict(link) for link in state["room_links"]]

    room_platform = _normalize_platform(platform)
    return [
        dict(link)
        for link in state["room_links"]
        if _normalize_platform(link.get("platform")) == room_platform
    ]
