from gateway.modal_runtime import (
    render_dashboard_html,
    sanitize_config_for_modal,
    sanitize_env_text_for_modal,
)


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
