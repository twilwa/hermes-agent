import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.modal_runtime import (
    normalize_github_token_env,
    render_dashboard_html,
    sanitize_config_for_modal,
    sanitize_env_text_for_modal,
)
import gateway.run as run_module
from scripts.modal_gateway import _named_secret_names


def test_sanitize_config_for_modal_forces_local_terminal_and_drops_local_urls():
    original = {
        "model": {
            "provider": "openai-codex",
            "default": "gpt-5.4",
            "base_url": "http://localhost:20128/v1",
        },
        "auxiliary": {
            "vision": {"base_url": "http://127.0.0.1:4000/v1"},
            "web_extract": {"base_url": "https://api.example.com/v1"},
        },
        "terminal": {
            "backend": "modal",
            "cwd": ".",
        },
    }

    sanitized = sanitize_config_for_modal(original, project_root="/opt/hermes/hermes-agent")

    assert original["terminal"]["backend"] == "modal"
    assert sanitized["terminal"]["backend"] == "local"
    assert sanitized["terminal"]["cwd"] == "/opt/hermes/hermes-agent"
    assert "base_url" not in sanitized["model"]
    assert "base_url" not in sanitized["auxiliary"]["vision"]
    assert sanitized["auxiliary"]["web_extract"]["base_url"] == "https://api.example.com/v1"


def test_sanitize_env_text_for_modal_drops_localhost_and_modal_credentials():
    raw = """# gateway config
OPENAI_BASE_URL=http://localhost:1234/v1
MODAL_TOKEN_ID=abc
MODAL_TOKEN_SECRET=def
DISCORD_BOT_TOKEN=xyz
OPENAI_API_KEY=sk-live
REMOTE_BASE_URL=https://api.example.com/v1
"""

    sanitized = sanitize_env_text_for_modal(raw)

    assert "# gateway config" in sanitized
    assert "OPENAI_BASE_URL" not in sanitized
    assert "MODAL_TOKEN_ID" not in sanitized
    assert "MODAL_TOKEN_SECRET" not in sanitized
    assert "DISCORD_BOT_TOKEN=xyz" in sanitized
    assert "OPENAI_API_KEY=sk-live" in sanitized
    assert "REMOTE_BASE_URL=https://api.example.com/v1" in sanitized


def test_render_dashboard_html_includes_runtime_state_and_logs():
    html = render_dashboard_html({
        "runtime_status": {
            "gateway_state": "running",
            "platforms": {"discord": {"state": "running"}},
        },
        "thread_alive": True,
        "gateway_log_tail": "discord connected",
        "error_log_tail": "",
        "last_error": None,
        "hermes_home": "/hermes-state/home",
        "project_root": "/opt/hermes/hermes-agent",
    })

    assert "Hermes Gateway Dashboard" in html
    assert "running" in html
    assert "discord connected" in html


def test_normalize_github_token_env_aliases_nonstandard_secret_keys(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("github-token", "secret-value")

    normalize_github_token_env()

    assert os.environ["GITHUB_TOKEN"] == "secret-value"
    assert os.environ["GH_TOKEN"] == "secret-value"


def test_named_secret_names_include_github_and_prime_by_default(monkeypatch):
    monkeypatch.delenv("HERMES_MODAL_GITHUB_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("HERMES_MODAL_PRIME_API_KEY_SECRET", raising=False)
    monkeypatch.delenv("HERMES_MODAL_FIRECRAWL_API_KEY_SECRET", raising=False)

    assert _named_secret_names() == ["github-token", "PRIME_API_KEY", "FIRECRAWL_API_KEY"]


def test_named_secret_names_dedupe_and_skip_empty_values(monkeypatch):
    monkeypatch.setenv("HERMES_MODAL_GITHUB_TOKEN_SECRET", "shared-secret")
    monkeypatch.setenv("HERMES_MODAL_PRIME_API_KEY_SECRET", "shared-secret")
    monkeypatch.setenv("HERMES_MODAL_FIRECRAWL_API_KEY_SECRET", "shared-secret")

    assert _named_secret_names() == ["shared-secret"]


@pytest.mark.asyncio
async def test_start_gateway_skips_signal_handlers_outside_main_thread(monkeypatch, tmp_path):
    class _FakeRunner:
        def __init__(self, config):
            self.config = config
            self.adapters = {}
            self.should_exit_cleanly = False
            self.should_exit_with_failure = False
            self.exit_reason = None

        async def start(self):
            return True

        async def wait_for_shutdown(self):
            return None

        async def stop(self):
            return None

    loop = MagicMock()

    monkeypatch.setattr(run_module, "_hermes_home", tmp_path)
    monkeypatch.setattr(run_module, "GatewayRunner", _FakeRunner)
    monkeypatch.setattr(run_module.asyncio, "get_event_loop", lambda: loop)
    monkeypatch.setattr(
        run_module.threading,
        "current_thread",
        lambda: SimpleNamespace(name="worker-thread"),
    )
    monkeypatch.setattr(
        run_module.threading,
        "main_thread",
        lambda: SimpleNamespace(name="main-thread"),
    )
    monkeypatch.setattr(run_module, "_start_cron_ticker", lambda *args, **kwargs: None)
    monkeypatch.setattr("gateway.status.get_running_pid", lambda: None)
    monkeypatch.setattr("gateway.status.write_pid_file", lambda: None)
    monkeypatch.setattr("gateway.status.remove_pid_file", lambda: None)
    monkeypatch.setattr("tools.skills_sync.sync_skills", lambda quiet=True: None)

    ok = await run_module.start_gateway(replace=True)

    assert ok is True
    loop.add_signal_handler.assert_not_called()
