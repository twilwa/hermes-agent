import json
from model_tools import get_tool_definitions
from tools.hyperspace_sidecar_tool import (
    APP_NAME,
    COMMAND_FUNCTION_NAME,
    HYPERSPACE_SIDECAR_SCRIPT,
    _get_sidecar_command_function,
    check_hyperspace_sidecar_requirements,
    hyperspace_sidecar,
)


def test_terminal_toolset_exposes_hyperspace_sidecar():
    tools = get_tool_definitions(enabled_toolsets=["terminal"], quiet_mode=True)
    names = {tool["function"]["name"] for tool in tools}

    assert "hyperspace_sidecar" in names


def test_rl_toolset_also_exposes_hyperspace_sidecar():
    tools = get_tool_definitions(enabled_toolsets=["rl"], quiet_mode=True)
    names = {tool["function"]["name"] for tool in tools}

    assert "hyperspace_sidecar" in names


def test_hyperspace_sidecar_requirements_pass_with_repo_script():
    assert HYPERSPACE_SIDECAR_SCRIPT.exists()
    assert check_hyperspace_sidecar_requirements() is True


def test_hyperspace_sidecar_without_command_returns_metadata():
    result = json.loads(hyperspace_sidecar())

    assert result["success"] is True
    assert result["metadata"]["app"] == "hermes-hyperspace-sidecar"
    assert result["metadata"]["gpu"] == "L4"
    assert "modal shell" in result["metadata"]["shell"]
    assert result["metadata"]["script"] == str(HYPERSPACE_SIDECAR_SCRIPT)


def test_hyperspace_sidecar_runs_command_in_remote_sidecar(monkeypatch):
    captured = {}

    class _FakeFunction:
        def remote(self, **kwargs):
            captured["kwargs"] = kwargs
            return {
                "success": True,
                "returncode": 0,
                "stdout": "gpu ready\n",
                "stderr": "",
                "metadata": {"gpu": "L4"},
            }

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_sidecar_command_function",
        lambda: _FakeFunction(),
    )

    result = json.loads(hyperspace_sidecar(command="nvidia-smi", timeout_seconds=42))

    assert result["success"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "gpu ready\n"
    assert captured["kwargs"] == {
        "command": "nvidia-smi",
        "timeout_seconds": 42,
        "bootstrap": True,
    }


def test_get_sidecar_command_function_uses_named_modal_function(monkeypatch):
    captured = {}

    class _FakeModalFunction:
        @staticmethod
        def from_name(app_name, function_name):
            captured["app_name"] = app_name
            captured["function_name"] = function_name
            return "fake-function"

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._ensure_modal_sdk",
        lambda: type("_FakeModal", (), {"Function": _FakeModalFunction}),
    )

    result = _get_sidecar_command_function()

    assert result == "fake-function"
    assert captured["app_name"] == APP_NAME
    assert captured["function_name"] == COMMAND_FUNCTION_NAME


def test_hyperspace_sidecar_surfaces_remote_failures(monkeypatch):
    def fake_get_sidecar_command_function():
        raise RuntimeError("modal auth broke")

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_sidecar_command_function",
        fake_get_sidecar_command_function,
    )

    result = json.loads(hyperspace_sidecar(command="whoami"))

    assert result["success"] is False
    assert result["stage"] == "remote"
    assert "RuntimeError: modal auth broke" in result["error"]
