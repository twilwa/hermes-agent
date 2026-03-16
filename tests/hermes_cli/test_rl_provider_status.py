"""Tests for RL provider helpers in CLI surfaces."""

from types import SimpleNamespace


def test_configured_rl_backend_label_prefers_explicit_prime(monkeypatch):
    from hermes_cli import status as status_mod

    monkeypatch.setattr(
        status_mod,
        "get_env_value",
        lambda name: "present" if name == "PRIME_API_KEY" else "",
        raising=False,
    )

    assert status_mod._configured_rl_backend_label({"rl": {"provider": "prime"}}) == "Prime"


def test_rl_provider_status_reports_prime_key_requirement(monkeypatch):
    from hermes_cli import setup as setup_mod

    monkeypatch.setattr(
        setup_mod,
        "get_env_value",
        lambda name: "",
        raising=False,
    )

    assert setup_mod._rl_provider_status({"rl": {"provider": "prime"}}) == (
        "RL Training (Prime)",
        False,
        "PRIME_API_KEY",
    )


def test_configured_rl_backend_prefers_explicit_prime(monkeypatch):
    from hermes_cli import doctor as doctor_mod

    monkeypatch.setattr(doctor_mod, "load_config", lambda: {"rl": {"provider": "prime"}}, raising=False)
    monkeypatch.setattr(
        doctor_mod,
        "get_env_value",
        lambda name: "present" if name == "PRIME_API_KEY" else "",
        raising=False,
    )

    assert doctor_mod._configured_rl_backend() == "prime"
