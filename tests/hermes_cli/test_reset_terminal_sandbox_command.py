"""Tests for the reset-terminal-sandbox command registry entries."""

from hermes_cli.commands import GATEWAY_KNOWN_COMMANDS, resolve_command


def test_reset_terminal_sandbox_command_resolves():
    assert resolve_command("reset-terminal-sandbox").name == "reset-terminal-sandbox"


def test_reset_terminal_sandbox_command_is_available_in_gateway_dispatch():
    assert "reset-terminal-sandbox" in GATEWAY_KNOWN_COMMANDS
