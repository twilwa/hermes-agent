# ABOUTME: Tests for the gateway room-link registry.
# ABOUTME: Covers durable saves and lookups by room and control context.

import json
from unittest.mock import patch

import gateway.room_links as room_links_mod
from gateway.room_links import (
    find_room_link,
    get_room_link,
    list_room_links,
    save_room_link,
)


class TestRoomLinkRegistry:
    def test_save_and_get_room_link(self, tmp_path):
        registry_path = tmp_path / "room_links.json"

        with patch.object(room_links_mod, "ROOM_LINKS_PATH", registry_path):
            saved = save_room_link(
                "livekit",
                "room-sid-1",
                "Town Hall",
                "discord",
                "guild-123",
            )
            loaded = get_room_link("livekit", "room-sid-1")

        assert registry_path.exists()
        on_disk = json.loads(registry_path.read_text())
        assert len(on_disk["room_links"]) == 1
        assert loaded == saved
        assert loaded["room_id"] == "room-sid-1"
        assert loaded["room_name"] == "Town Hall"
        assert loaded["control_platform"] == "discord"
        assert loaded["control_chat_id"] == "guild-123"
        assert loaded["control_thread_id"] is None

    def test_find_room_link_distinguishes_channel_and_thread_contexts(self, tmp_path):
        registry_path = tmp_path / "room_links.json"

        with patch.object(room_links_mod, "ROOM_LINKS_PATH", registry_path):
            save_room_link(
                "livekit",
                "room-sid-1",
                "Town Hall",
                "discord",
                "guild-123",
            )
            save_room_link(
                "livekit",
                "room-sid-2",
                "Town Hall Thread",
                "discord",
                "guild-123",
                control_thread_id="thread-9",
            )

            parent_link = find_room_link("discord", "guild-123")
            thread_link = find_room_link("discord", "guild-123", "thread-9")

        assert parent_link["room_id"] == "room-sid-1"
        assert thread_link["room_id"] == "room-sid-2"
        assert parent_link["control_thread_id"] is None
        assert thread_link["control_thread_id"] == "thread-9"

    def test_save_room_link_replaces_conflicting_entries(self, tmp_path):
        registry_path = tmp_path / "room_links.json"

        with patch.object(room_links_mod, "ROOM_LINKS_PATH", registry_path):
            save_room_link(
                "livekit",
                "room-sid-1",
                "Town Hall",
                "discord",
                "guild-123",
            )
            save_room_link(
                "livekit",
                "room-sid-1",
                "Town Hall v2",
                "discord",
                "guild-456",
            )

            loaded = get_room_link("livekit", "room-sid-1")
            old_control = find_room_link("discord", "guild-123")
            links = list_room_links()

        assert loaded["room_name"] == "Town Hall v2"
        assert loaded["control_chat_id"] == "guild-456"
        assert old_control is None
        assert len(links) == 1

    def test_list_room_links_filters_by_platform(self, tmp_path):
        registry_path = tmp_path / "room_links.json"

        with patch.object(room_links_mod, "ROOM_LINKS_PATH", registry_path):
            save_room_link(
                "livekit",
                "room-sid-1",
                "Town Hall",
                "discord",
                "guild-123",
            )
            save_room_link(
                "matrix",
                "room-sid-2",
                "Side Room",
                "discord",
                "guild-456",
            )

            livekit_links = list_room_links(platform="livekit")
            all_links = list_room_links()

        assert len(all_links) == 2
        assert [link["room_id"] for link in livekit_links] == ["room-sid-1"]
