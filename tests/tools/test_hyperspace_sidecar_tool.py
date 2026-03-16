import json

from model_tools import get_tool_definitions
from tools.hyperspace_sidecar_tool import (
    HYPERSPACE_SIDECAR_SCRIPT,
    KEEPALIVE_COMMAND,
    SYNC_VOLUME_COMMAND,
    check_hyperspace_sidecar_requirements,
    hyperspace_sidecar,
    _run_sidecar_command_in_sandbox,
    _wrap_sidecar_command,
)


class _FakeSandbox:
    def __init__(self, object_id="sb-123", poll_result=None):
        self.object_id = object_id
        self._poll_result = poll_result
        self.terminate_calls = []

    def poll(self):
        return self._poll_result

    def terminate(self, wait=False):
        self.terminate_calls.append(wait)


class _FakeStream:
    def __init__(self, value):
        self._value = value

    def read(self):
        return self._value


class _FakeProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = _FakeStream(stdout)
        self.stderr = _FakeStream(stderr)
        self._returncode = returncode

    def wait(self):
        return self._returncode


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


def test_wrap_sidecar_command_bootstraps_directories():
    command = _wrap_sidecar_command("nvidia-smi", bootstrap=True)

    assert "mkdir -p" in command
    assert command.endswith(" && nvidia-smi")


def test_hyperspace_sidecar_metadata_reports_no_running_sandbox(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: None,
    )

    result = json.loads(hyperspace_sidecar())

    assert result["success"] is True
    assert result["action"] == "metadata"
    assert result["running"] is False
    assert result["metadata"]["mode"] == "named_sandbox"
    assert result["metadata"]["script"] == str(HYPERSPACE_SIDECAR_SCRIPT)


def test_hyperspace_sidecar_start_creates_keepalive_sandbox(monkeypatch):
    captured = {}
    sandbox = _FakeSandbox()

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: None,
    )

    def fake_create_sidecar_sandbox(startup_command="", sandbox_timeout_seconds=0, bootstrap=True):
        captured["startup_command"] = startup_command
        captured["sandbox_timeout_seconds"] = sandbox_timeout_seconds
        captured["bootstrap"] = bootstrap
        return sandbox

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._create_sidecar_sandbox",
        fake_create_sidecar_sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(
        hyperspace_sidecar(action="start", sandbox_timeout_seconds=600, bootstrap=False)
    )

    assert result["success"] is True
    assert result["action"] == "start"
    assert result["created"] is True
    assert result["startup_command"] == KEEPALIVE_COMMAND
    assert result["sandbox_id"] == "sb-123"
    assert captured == {
        "startup_command": "",
        "sandbox_timeout_seconds": 600,
        "bootstrap": False,
        "detached": True,
    }


def test_hyperspace_sidecar_start_reuses_existing_sandbox(monkeypatch):
    sandbox = _FakeSandbox(object_id="sb-existing")
    captured = {}

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(
        hyperspace_sidecar(action="start", command="hyperspace start --daemon")
    )

    assert result["success"] is True
    assert result["created"] is False
    assert result["running"] is True
    assert result["warning"].startswith("Sidecar is already running")
    assert captured["detached"] is True


def test_hyperspace_sidecar_exec_auto_starts_and_reuses_named_sandbox(monkeypatch):
    captured = {}
    sandbox = _FakeSandbox()

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: None,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._create_sidecar_sandbox",
        lambda startup_command="", sandbox_timeout_seconds=0, bootstrap=True: sandbox,
    )

    def fake_run_sidecar_command_in_sandbox(sandbox, command, timeout_seconds, bootstrap):
        captured["command"] = command
        captured["timeout_seconds"] = timeout_seconds
        captured["bootstrap"] = bootstrap
        return {
            "success": True,
            "command": command,
            "returncode": 0,
            "stdout": "gpu ready\n",
            "stderr": "",
        }

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._run_sidecar_command_in_sandbox",
        fake_run_sidecar_command_in_sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(hyperspace_sidecar(command="nvidia-smi", timeout_seconds=42))

    assert result["success"] is True
    assert result["action"] == "exec"
    assert result["auto_started"] is True
    assert result["stdout"] == "gpu ready\n"
    assert result["sandbox_id"] == "sb-123"
    assert captured == {
        "command": "nvidia-smi",
        "timeout_seconds": 42,
        "bootstrap": True,
        "detached": True,
    }


def test_run_sidecar_command_in_sandbox_syncs_volume_after_exec():
    captured = {"calls": []}

    class _SyncingSandbox:
        def exec(self, *args, **kwargs):
            captured["calls"].append((args, kwargs))
            if len(captured["calls"]) == 1:
                return _FakeProcess(stdout="ready\n")
            return _FakeProcess(stdout="")

    payload = _run_sidecar_command_in_sandbox(
        sandbox=_SyncingSandbox(),
        command="nvidia-smi",
        timeout_seconds=42,
        bootstrap=True,
    )

    assert payload["success"] is True
    assert payload["stdout"] == "ready\n"
    assert len(captured["calls"]) == 2
    assert captured["calls"][1][0] == ("bash", "-lc", SYNC_VOLUME_COMMAND)


def test_hyperspace_sidecar_status_reports_running_sandbox(monkeypatch):
    sandbox = _FakeSandbox(object_id="sb-running")
    captured = {}

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(hyperspace_sidecar(action="status"))

    assert result["success"] is True
    assert result["action"] == "status"
    assert result["running"] is True
    assert result["sandbox_id"] == "sb-running"
    assert captured["detached"] is True


def test_hyperspace_sidecar_stop_terminates_running_sandbox(monkeypatch):
    sandbox = _FakeSandbox(object_id="sb-stop")
    captured = {}

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(hyperspace_sidecar(action="stop"))

    assert result["success"] is True
    assert result["action"] == "stop"
    assert result["stopped"] is True
    assert result["running"] is False
    assert sandbox.terminate_calls == [True]
    assert captured["detached"] is True


def test_hyperspace_sidecar_rejects_exec_without_command():
    result = json.loads(hyperspace_sidecar(action="exec"))

    assert result["success"] is False
    assert result["stage"] == "exec"
    assert "command is required" in result["error"].lower()


def test_hyperspace_sidecar_surfaces_invalid_actions():
    result = json.loads(hyperspace_sidecar(action="dance"))

    assert result["success"] is False
    assert "Unknown action 'dance'" in result["error"]
