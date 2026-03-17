import json

from model_tools import get_tool_definitions
from tools.hyperspace_sidecar_tool import (
    BASE_IMAGE_TAG,
    HYPERSPACE_SIDECAR_SCRIPT,
    HYPERSPACE_RUNTIME_BINARY_PATCHES,
    HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_NEW,
    HYPERSPACE_SQLITE_LOADER_PATCH_NEW,
    KEEPALIVE_COMMAND,
    SIDECAR_APT_PACKAGES,
    SYNC_VOLUME_COMMAND,
    _apply_hyperspace_runtime_binary_patches,
    _build_hyperspace_service_command,
    _build_hyperspace_service_status_command,
    _summarize_hyperspace_connection,
    check_hyperspace_sidecar_requirements,
    hyperspace,
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


def _extract_python_heredoc(command: str) -> str:
    prefix = "python - <<'PY'\n"
    suffix = "\nPY"
    assert command.startswith(prefix)
    assert command.endswith(suffix)
    return command[len(prefix) : -len(suffix)]


def test_terminal_toolset_exposes_hyperspace_sidecar():
    tools = get_tool_definitions(enabled_toolsets=["terminal"], quiet_mode=True)
    names = {tool["function"]["name"] for tool in tools}

    assert "hyperspace_sidecar" in names
    assert "hyperspace" in names


def test_legacy_terminal_toolset_exposes_hyperspace_wrapper():
    tools = get_tool_definitions(enabled_toolsets=["terminal_tools"], quiet_mode=True)
    names = {tool["function"]["name"] for tool in tools}

    assert "hyperspace_sidecar" in names
    assert "hyperspace" in names


def test_rl_toolset_also_exposes_hyperspace_sidecar():
    tools = get_tool_definitions(enabled_toolsets=["rl"], quiet_mode=True)
    names = {tool["function"]["name"] for tool in tools}

    assert "hyperspace_sidecar" in names
    assert "hyperspace" in names


def test_legacy_rl_toolset_also_exposes_hyperspace_wrapper():
    tools = get_tool_definitions(enabled_toolsets=["rl_tools"], quiet_mode=True)
    names = {tool["function"]["name"] for tool in tools}

    assert "hyperspace_sidecar" in names
    assert "hyperspace" in names


def test_hyperspace_sidecar_requirements_pass_with_repo_script():
    assert HYPERSPACE_SIDECAR_SCRIPT.exists()
    assert check_hyperspace_sidecar_requirements() is True


def test_hyperspace_sidecar_runtime_image_matches_hyperspace_binary_requirements():
    assert BASE_IMAGE_TAG == "python:3.11-slim-bookworm"
    assert {"libgomp1", "libssl3", "libstdc++6", "lsof"}.issubset(
        set(SIDECAR_APT_PACKAGES)
    )


def test_hyperspace_runtime_binary_patches_preserve_bundle_size():
    for _, old_variants, new in HYPERSPACE_RUNTIME_BINARY_PATCHES:
        for old in old_variants:
            assert len(old) == len(new)


def test_hyperspace_sqlite_loader_patch_uses_create_require():
    assert b'createRequire(process.execPath)' in HYPERSPACE_SQLITE_LOADER_PATCH_NEW
    assert (
        b'createRequire(process.execPath)'
        in HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_NEW
    )


def test_apply_hyperspace_runtime_binary_patches_updates_upstream_bundle_bytes():
    upstream_bundle = b"\n".join(
        old_variants[0] for _, old_variants, _ in HYPERSPACE_RUNTIME_BINARY_PATCHES
    )

    patched_bundle, applied, already_patched, missing = (
        _apply_hyperspace_runtime_binary_patches(upstream_bundle)
    )

    assert applied == [name for name, _, _ in HYPERSPACE_RUNTIME_BINARY_PATCHES]
    assert already_patched == []
    assert missing == []
    for _, old_variants, new in HYPERSPACE_RUNTIME_BINARY_PATCHES:
        for old in old_variants:
            assert old not in patched_bundle
        assert new in patched_bundle


def test_apply_hyperspace_runtime_binary_patches_is_idempotent():
    upstream_bundle = b"\n".join(
        old_variants[0] for _, old_variants, _ in HYPERSPACE_RUNTIME_BINARY_PATCHES
    )
    patched_bundle, _, _, _ = _apply_hyperspace_runtime_binary_patches(upstream_bundle)

    repatched_bundle, applied, already_patched, missing = (
        _apply_hyperspace_runtime_binary_patches(patched_bundle)
    )

    assert repatched_bundle == patched_bundle
    assert applied == []
    assert already_patched == [name for name, _, _ in HYPERSPACE_RUNTIME_BINARY_PATCHES]
    assert missing == []


def test_wrap_sidecar_command_bootstraps_directories():
    command = _wrap_sidecar_command("nvidia-smi", bootstrap=True)

    assert "mkdir -p" in command
    assert command.endswith(" && nvidia-smi")


def test_hyperspace_service_status_command_checks_hyperspace_pid_fallback():
    command = _build_hyperspace_service_status_command()

    assert "service.pid" in command
    assert "hyperspace.pid" in command
    assert "supervisor.pid" in command
    assert "api_listening" in command
    assert "api_healthy" in command


def test_hyperspace_service_command_disables_startup_auto_update():
    command = _build_hyperspace_service_command("--alpha")
    enabled = _build_hyperspace_service_command(
        "--alpha",
        disable_startup_update=False,
    )

    assert 'child_env.setdefault("HYPERSPACE_SKIP_STARTUP_UPDATE", "1")' in command
    assert 'child_env.pop("HYPERSPACE_SKIP_STARTUP_UPDATE", None)' in command
    assert '"disable_startup_update": json.loads(\'true\')' in command
    assert '"disable_startup_update": json.loads(\'false\')' in enabled
    compile(_extract_python_heredoc(command), "<hyperspace-service>", "exec")
    compile(_extract_python_heredoc(enabled), "<hyperspace-service>", "exec")


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


def test_hyperspace_sidecar_start_service_launches_inside_keepalive_sandbox(monkeypatch):
    captured = {}
    sandbox = _FakeSandbox(object_id="sb-service")
    state = {"sandbox": None}
    status_calls = {"count": 0}

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: state["sandbox"],
    )

    def fake_create_sidecar_sandbox(startup_command="", sandbox_timeout_seconds=0, bootstrap=True):
        captured["startup_command"] = startup_command
        captured["sandbox_timeout_seconds"] = sandbox_timeout_seconds
        captured["bootstrap"] = bootstrap
        state["sandbox"] = sandbox
        return sandbox

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._create_sidecar_sandbox",
        fake_create_sidecar_sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._run_sidecar_command_in_sandbox",
        lambda sandbox, command, timeout_seconds, bootstrap: captured.update(
            {
                "launch_command": command,
                "launch_timeout_seconds": timeout_seconds,
                "launch_bootstrap": bootstrap,
            }
        )
        or {
            "success": True,
            "command": command,
            "returncode": 0,
            "stdout": '{"launched": true, "pid": 245, "returncode": null}\n',
            "stderr": "",
        },
    )
    def fake_status_service_payload(service):
        status_calls["count"] += 1
        if status_calls["count"] == 1:
            return {
                "success": True,
                "action": "status",
                "running": True,
                "service": service,
                "service_running": False,
            }
        return {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "service_pid": "245",
            "service_running": True,
            "whoami": {"returncode": 0, "stdout": "CONNECTED (PID 245)\n", "stderr": ""},
        }

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        fake_status_service_payload,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(
        hyperspace_sidecar(
            action="start",
            service="hyperspace",
            service_args="--alpha",
            sandbox_timeout_seconds=1234,
        )
    )

    assert result["success"] is True
    assert result["action"] == "start"
    assert result["created"] is True
    assert result["service"] == "hyperspace"
    assert result["service_args"] == "--alpha"
    assert result["disable_startup_update"] is True
    assert result["startup_command"] == KEEPALIVE_COMMAND
    assert result["launch_command"] == _build_hyperspace_service_command("--alpha")
    assert result["service_running"] is True
    assert result["sandbox_id"] == "sb-service"
    assert captured == {
        "startup_command": "",
        "sandbox_timeout_seconds": 1234,
        "bootstrap": True,
        "launch_command": _build_hyperspace_service_command("--alpha"),
        "launch_timeout_seconds": 120,
        "launch_bootstrap": True,
        "detached": True,
    }


def test_hyperspace_sidecar_start_does_not_launch_duplicate_supervisor(monkeypatch):
    sandbox = _FakeSandbox(object_id="sb-supervisor")
    captured = {}

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: sandbox,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "supervisor_pid": "999",
            "supervisor_running": True,
            "service_pid": "1234",
            "service_running": False,
            "api_healthy": False,
            "log_tail": "restarting\n",
            "whoami": {"returncode": 0, "stdout": "DISCONNECTED\n", "stderr": ""},
        },
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._run_sidecar_command_in_sandbox",
        lambda *args, **kwargs: captured.setdefault("launch_attempted", True),
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        lambda sandbox: captured.setdefault("detached", True),
    )

    result = json.loads(hyperspace_sidecar(action="start", service="hyperspace"))

    assert result["success"] is True
    assert result["created"] is False
    assert result["supervisor_running"] is True
    assert result["api_healthy"] is False
    assert result["warning"].startswith("Hyperspace supervisor is already running")
    assert "launch_attempted" not in captured
    assert captured["detached"] is True


def test_hyperspace_status_marks_connected_node_ready(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "command": [
                "/hyperspace-state/home/.local/bin/hyperspace",
                "start",
                "--headless",
                "--cuda",
                "--profile",
                "inference",
                "--mode",
                "power",
            ],
            "supervisor_running": True,
            "service_running": True,
            "api_listening": True,
            "api_healthy": True,
            "startup_update_disabled": True,
            "whoami": {
                "returncode": 0,
                "stdout": "CONNECTED (PID 245)\n",
                "stderr": "",
            },
        },
    )

    result = json.loads(hyperspace(action="status"))

    assert result["success"] is True
    assert result["connection_state"] == "connected"
    assert result["connected_to_hive"] is True
    assert result["hive_status"] == "CONNECTED"
    assert result["hive_connected"] is True
    assert result["api_state"] == "healthy"
    assert result["ready"] is True
    assert result["health"] == "healthy"
    assert result["whoami_stdout"] == "CONNECTED (PID 245)"
    assert result["launch_profile"] == "inference"
    assert result["resource_mode"] == "power"
    assert result["resource_mode_budget_percent"] == 80
    assert result["startup_update_disabled"] is True
    assert result["managed_startup_update_default"] is True
    assert result["model_request_pins_startup"] is False
    assert "chill=30%" in result["model_selection_guidance"]


def test_hyperspace_status_marks_disconnected_node_degraded(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "supervisor_running": True,
            "service_running": True,
            "api_listening": True,
            "api_healthy": True,
            "whoami": {
                "returncode": 0,
                "stdout": "DISCONNECTED\n",
                "stderr": "",
            },
        },
    )

    result = json.loads(hyperspace(action="status"))

    assert result["success"] is True
    assert result["connection_state"] == "disconnected"
    assert result["connected_to_hive"] is False
    assert result["hive_status"] == "DISCONNECTED"
    assert result["hive_connected"] is False
    assert result["api_state"] == "healthy"
    assert result["ready"] is False
    assert result["health"] == "degraded"


def test_hyperspace_status_marks_stalled_api_when_port_accepts_without_response(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "supervisor_running": True,
            "service_running": True,
            "api_listening": True,
            "api_healthy": False,
            "api_error": "TimeoutError: timed out",
            "whoami": {
                "returncode": 0,
                "stdout": "CONNECTED\n",
                "stderr": "",
            },
        },
    )

    result = json.loads(hyperspace(action="status"))

    assert result["success"] is True
    assert result["api_state"] == "stalled"
    assert result["connection_state"] == "connected"
    assert result["health"] == "degraded"
    assert result["ready"] is False


def test_hyperspace_status_marks_loading_model_as_warming_up(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "supervisor_running": True,
            "service_running": True,
            "api_listening": True,
            "api_healthy": False,
            "api_error": "TimeoutError: timed out",
            "log_tail": "[INFERENCE] Loading gpt-oss-20b: 25%\n",
            "status": {
                "allocationMode": "power",
                "loadedModels": ["gpt-oss-20b"],
            },
            "whoami": {
                "returncode": 0,
                "stdout": "CONNECTED\n",
                "stderr": "",
            },
        },
    )

    result = json.loads(hyperspace(action="status"))

    assert result["success"] is True
    assert result["api_state"] == "warming_up"
    assert result["loading_model"] == "gpt-oss-20b"
    assert result["model_loading"] is True
    assert result["model_loading_progress_percent"] == 25
    assert result["loaded_models"] == ["gpt-oss-20b"]
    assert result["resource_mode"] == "power"


def test_hyperspace_status_treats_loading_model_as_warming_up_even_when_health_probe_passes(
    monkeypatch,
):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "supervisor_running": True,
            "service_running": True,
            "api_listening": True,
            "api_healthy": True,
            "log_tail": "[INFERENCE] Loading gpt-oss-20b: 18%\n",
            "status": {
                "allocationMode": "power",
                "loadedModels": [],
            },
            "whoami": {
                "returncode": 0,
                "stdout": "DISCONNECTED\n",
                "stderr": "",
            },
        },
    )

    result = json.loads(hyperspace(action="status"))

    assert result["success"] is True
    assert result["api_state"] == "warming_up"
    assert result["model_loading"] is True
    assert result["model_loading_progress_percent"] == 18


def test_summarize_hyperspace_connection_extracts_peer_fields():
    result = _summarize_hyperspace_connection(
        {
            "returncode": 0,
            "stdout": (
                "CONNECTED\n"
                "peer count: 3\n"
                "Peer ID: 12D3KooWJ7xQ5vQjC6m3uW5x5x5x5x5x5x5x5x5x5x5\n"
            ),
            "stderr": "",
        }
    )

    assert result["connection_state"] == "connected"
    assert result["connected_to_hive"] is True
    assert result["hive_status"] == "CONNECTED"
    assert result["hive_connected"] is True
    assert result["peer_count"] == 3
    assert result["peer_id"] == "12D3KooWJ7xQ5vQjC6m3uW5x5x5x5x5x5x5x5x5x5x5"


def test_hyperspace_report_includes_api_health(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._status_service_payload",
        lambda service: {
            "success": True,
            "action": "status",
            "running": True,
            "service": service,
            "supervisor_running": True,
            "service_running": True,
            "api_listening": True,
            "api_healthy": True,
            "whoami": {
                "returncode": 0,
                "stdout": "CONNECTED\n",
                "stderr": "",
            },
        },
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._request_hyperspace_api",
        lambda *args, **kwargs: {
            "ok": True,
            "status": 200,
            "body": {"status": "ok", "version": "3.8.5"},
        },
    )

    result = json.loads(hyperspace(action="report"))

    assert result["success"] is True
    assert result["api_state"] == "healthy"
    assert result["health"] == "healthy"
    assert result["api_health"] == {
        "ok": True,
        "status": 200,
        "body": {"status": "ok", "version": "3.8.5"},
    }


def test_hyperspace_chat_requires_messages():
    result = json.loads(hyperspace(action="chat"))

    assert result["success"] is False
    assert result["action"] == "chat"
    assert "messages" in result["error"]


def test_hyperspace_chat_returns_api_response(monkeypatch):
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._ensure_hyperspace_payload",
        lambda service_args, sandbox_timeout_seconds, disable_startup_update: {
            "success": True,
            "running": True,
            "service": "hyperspace",
            "service_running": True,
            "supervisor_running": True,
            "api_listening": True,
            "api_healthy": True,
            "connection_state": "connected",
            "connected_to_hive": True,
            "api_state": "healthy",
            "ready": True,
            "health": "healthy",
            "whoami": {
                "returncode": 0,
                "stdout": "CONNECTED\n",
                "stderr": "",
            },
            "whoami_stdout": "CONNECTED",
            "whoami_stderr": "",
        },
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._request_hyperspace_api",
        lambda *args, **kwargs: {
            "ok": True,
            "status": 200,
            "body": {
                "id": "chatcmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            },
        },
    )

    result = json.loads(
        hyperspace(
            action="chat",
            model="llama-3.1-8b-instruct",
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert result["success"] is True
    assert result["action"] == "chat"
    assert result["model"] == "llama-3.1-8b-instruct"
    assert result["message_count"] == 1
    assert result["connection_state"] == "connected"
    assert result["ready"] is True
    assert result["response"]["choices"][0]["message"]["content"] == "hi"


def test_hyperspace_chat_waits_for_api_warmup(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._ensure_hyperspace_payload",
        lambda service_args, sandbox_timeout_seconds, disable_startup_update: {
            "success": True,
            "running": True,
            "service": "hyperspace",
            "service_running": True,
            "supervisor_running": True,
            "api_listening": True,
            "api_healthy": False,
            "api_state": "warming_up",
            "health": "degraded",
            "ready": False,
            "connection_state": "connected",
            "connected_to_hive": True,
            "loading_model": "gpt-oss-20b",
            "model_loading": True,
            "model_loading_progress_percent": 25,
            "whoami": {
                "returncode": 0,
                "stdout": "CONNECTED\n",
                "stderr": "",
            },
        },
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._wait_for_hyperspace_api_ready",
        lambda status_payload, timeout_seconds: {
            **status_payload,
            "api_healthy": True,
            "api_state": "healthy",
            "health": "healthy",
            "ready": True,
            "model_loading": False,
            "model_loading_progress_percent": 100,
        },
    )

    def fake_request_hyperspace_api(path, **kwargs):
        calls.append(path)
        return {
            "ok": True,
            "status": 200,
            "body": {
                "id": "chatcmpl-2",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
        }

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._request_hyperspace_api",
        fake_request_hyperspace_api,
    )

    result = json.loads(
        hyperspace(
            action="chat",
            messages=[{"role": "user", "content": "hello"}],
            timeout_seconds=60,
        )
    )

    assert result["success"] is True
    assert result["api_healthy"] is True
    assert result["model_loading"] is False
    assert calls == ["/v1/chat/completions"]


def test_hyperspace_chat_waits_when_health_probe_is_green_but_model_is_still_loading(
    monkeypatch,
):
    wait_calls = []

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._ensure_hyperspace_payload",
        lambda service_args, sandbox_timeout_seconds, disable_startup_update: {
            "success": True,
            "running": True,
            "service": "hyperspace",
            "service_running": True,
            "supervisor_running": True,
            "api_listening": True,
            "api_healthy": True,
            "api_state": "warming_up",
            "health": "degraded",
            "ready": False,
            "connection_state": "disconnected",
            "connected_to_hive": False,
            "loading_model": "gpt-oss-20b",
            "model_loading": True,
            "model_loading_progress_percent": 18,
            "status": {"loadedModels": []},
            "whoami": {
                "returncode": 0,
                "stdout": "DISCONNECTED\n",
                "stderr": "",
            },
        },
    )

    def fake_wait_for_hyperspace_api_ready(status_payload, timeout_seconds):
        wait_calls.append((status_payload["api_healthy"], status_payload["model_loading"]))
        return {
            **status_payload,
            "api_healthy": True,
            "api_state": "healthy",
            "health": "degraded",
            "model_loading": False,
            "model_loading_progress_percent": 100,
            "status": {"loadedModels": ["gpt-oss-20b"]},
        }

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._wait_for_hyperspace_api_ready",
        fake_wait_for_hyperspace_api_ready,
    )
    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._request_hyperspace_api",
        lambda *args, **kwargs: {
            "ok": True,
            "status": 200,
            "body": {
                "id": "chatcmpl-3",
                "choices": [{"message": {"role": "assistant", "content": "ready"}}],
            },
        },
    )

    result = json.loads(
        hyperspace(
            action="chat",
            messages=[{"role": "user", "content": "hello"}],
            timeout_seconds=60,
        )
    )

    assert result["success"] is True
    assert result["model_loading"] is False
    assert wait_calls == [(True, True)]


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


def test_hyperspace_sidecar_status_reports_hyperspace_service(monkeypatch):
    sandbox = _FakeSandbox(object_id="sb-running")
    captured = {"exec_calls": 0}

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._get_running_sidecar_sandbox",
        lambda: sandbox,
    )

    def fake_detach_sidecar_sandbox(sandbox):
        captured["detached"] = captured.get("detached", 0) + 1

    monkeypatch.setattr(
        "tools.hyperspace_sidecar_tool._detach_sidecar_sandbox",
        fake_detach_sidecar_sandbox,
    )

    def fake_exec(*args, **kwargs):
        captured["exec_calls"] += 1
        return _FakeProcess(
            stdout=json.dumps(
                {
                    "service": "hyperspace",
                    "service_pid": "4321",
                    "service_running": True,
                    "log_tail": "ready\n",
                    "whoami": {"returncode": 0, "stdout": "CONNECTED\n", "stderr": ""},
                }
            )
        )

    sandbox.exec = fake_exec

    result = json.loads(hyperspace_sidecar(action="status", service="hyperspace"))

    assert result["success"] is True
    assert result["action"] == "status"
    assert result["running"] is True
    assert result["service"] == "hyperspace"
    assert result["service_pid"] == "4321"
    assert result["service_running"] is True
    assert result["whoami"]["stdout"] == "CONNECTED\n"
    assert captured == {
        "exec_calls": 1,
        "detached": 2,
    }


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


def test_hyperspace_sidecar_surfaces_invalid_services():
    result = json.loads(hyperspace_sidecar(action="start", service="bogus"))

    assert result["success"] is False
    assert "Unknown service 'bogus'" in result["error"]
