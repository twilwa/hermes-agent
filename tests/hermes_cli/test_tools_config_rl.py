"""Tests for RL provider selection in hermes_cli.tools_config."""

from hermes_cli.tools_config import _toolset_has_keys


def test_toolset_has_keys_accepts_prime_when_selected(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.tools_config.load_config",
        lambda: {"rl": {"provider": "prime"}},
    )
    monkeypatch.setattr(
        "hermes_cli.tools_config.get_env_value",
        lambda name: "prime-key" if name == "PRIME_API_KEY" else "",
    )

    assert _toolset_has_keys("rl") is True


def test_toolset_has_keys_requires_wandb_for_tinker(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.tools_config.load_config",
        lambda: {"rl": {"provider": "tinker"}},
    )
    monkeypatch.setattr(
        "hermes_cli.tools_config.get_env_value",
        lambda name: "tinker-key" if name == "TINKER_API_KEY" else "",
    )

    assert _toolset_has_keys("rl") is False
