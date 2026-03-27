"""Tests for the CLI reset-terminal-sandbox command."""

from unittest.mock import MagicMock, patch

from tests.test_cli_new_session import _prepare_cli_with_active_session


def test_reset_terminal_sandbox_command_targets_current_session(tmp_path):
    cli = _prepare_cli_with_active_session(tmp_path)
    cli.console = MagicMock()
    reset_sandbox = MagicMock(return_value=True)

    with patch.dict(
        cli._handle_reset_terminal_sandbox_command.__func__.__globals__,
        {"_reset_terminal_sandbox": reset_sandbox},
    ):
        cli.process_command("/reset-terminal-sandbox")

    reset_sandbox.assert_called_once_with(cli.session_id)
    cli.console.print.assert_called_once_with("  Reset terminal sandbox for this session.")


def test_reset_terminal_sandbox_command_reports_missing_session_sandbox(tmp_path):
    cli = _prepare_cli_with_active_session(tmp_path)
    cli.console = MagicMock()
    reset_sandbox = MagicMock(return_value=False)

    with patch.dict(
        cli._handle_reset_terminal_sandbox_command.__func__.__globals__,
        {"_reset_terminal_sandbox": reset_sandbox},
    ):
        cli.process_command("/reset-terminal-sandbox")

    reset_sandbox.assert_called_once_with(cli.session_id)
    cli.console.print.assert_called_once_with("  No active terminal sandbox for this session.")
