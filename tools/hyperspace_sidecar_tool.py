# ABOUTME: Manages a named Modal L4 sandbox for Hyperspace so Hermes can start, reuse, inspect, and stop a durable GPU sidecar.
# ABOUTME: Keeps the GPU off until explicitly started, reuses the same sandbox across tool calls, and exposes structured lifecycle results.

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sys
from pathlib import Path

from tools.registry import registry

HYPERSPACE_SIDECAR_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "modal_hyperspace_sidecar.py"
)
APP_NAME = os.getenv("HERMES_MODAL_HYPERSPACE_APP_NAME", "hermes-hyperspace-sidecar")
VOLUME_NAME = os.getenv("HERMES_MODAL_HYPERSPACE_VOLUME_NAME", f"{APP_NAME}-state")
SANDBOX_NAME = os.getenv(
    "HERMES_MODAL_HYPERSPACE_SANDBOX_NAME",
    f"{APP_NAME}-sandbox",
)
STATE_ROOT = "/hyperspace-state"
HOME_DIR = f"{STATE_ROOT}/home"
CONFIG_DIR = f"{STATE_ROOT}/config"
DATA_DIR = f"{STATE_ROOT}/share"
CACHE_DIR = f"{STATE_ROOT}/cache"
LINUX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_SANDBOX_TIMEOUT_SECONDS = int(
    os.getenv("HERMES_MODAL_HYPERSPACE_SANDBOX_TIMEOUT_SECONDS", "86340")
)
KEEPALIVE_COMMAND = "trap 'exit 0' TERM INT; while true; do sleep 3600; done"
SYNC_VOLUME_COMMAND = f"sync {shlex.quote(STATE_ROOT)}"
VALID_ACTIONS = {"metadata", "start", "exec", "status", "stop"}


def _sidecar_metadata() -> dict[str, str]:
    script = str(HYPERSPACE_SIDECAR_SCRIPT)
    return {
        "app": APP_NAME,
        "volume": VOLUME_NAME,
        "sandbox_name": SANDBOX_NAME,
        "script": script,
        "gpu": "L4",
        "home": HOME_DIR,
        "mode": "named_sandbox",
        "bootstrap": f"{sys.executable} -m modal run {script}",
        "shell": (
            f"{sys.executable} -m modal shell "
            f"{script}::hyperspace_sidecar --cmd /bin/bash"
        ),
    }


def _ensure_modal_sdk():
    import modal
    return modal


def _sidecar_env() -> dict[str, str]:
    return {
        "HOME": HOME_DIR,
        "XDG_CONFIG_HOME": CONFIG_DIR,
        "XDG_DATA_HOME": DATA_DIR,
        "XDG_CACHE_HOME": CACHE_DIR,
        "PATH": f"{HOME_DIR}/.local/bin:{LINUX_PATH}",
    }


def _sidecar_bootstrap_prefix() -> str:
    return " && ".join(
        [
            f"mkdir -p {shlex.quote(HOME_DIR)}",
            f"mkdir -p {shlex.quote(CONFIG_DIR)}",
            f"mkdir -p {shlex.quote(DATA_DIR)}",
            f"mkdir -p {shlex.quote(CACHE_DIR)}",
        ]
    )


def _wrap_sidecar_command(command: str, bootstrap: bool) -> str:
    command = (command or "").strip()
    if not bootstrap:
        return command
    prefix = _sidecar_bootstrap_prefix()
    if not command:
        return prefix
    return f"{prefix} && {command}"


def _get_sidecar_app(modal=None):
    modal = modal or _ensure_modal_sdk()
    return modal.App.lookup(APP_NAME, create_if_missing=True)


def _get_sidecar_volume(modal=None):
    modal = modal or _ensure_modal_sdk()
    return modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _get_sidecar_image(modal=None):
    modal = modal or _ensure_modal_sdk()
    return (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install("bash", "curl", "git", "ca-certificates", "procps")
        .env(_sidecar_env())
    )


def _detach_sidecar_sandbox(sandbox) -> None:
    if sandbox is None:
        return
    try:
        sandbox.detach()
    except Exception:
        pass


def _get_running_sidecar_sandbox():
    modal = _ensure_modal_sdk()
    try:
        return modal.Sandbox.from_name(APP_NAME, SANDBOX_NAME)
    except modal.exception.NotFoundError:
        return None


def _create_sidecar_sandbox(
    startup_command: str = "",
    sandbox_timeout_seconds: int = DEFAULT_SANDBOX_TIMEOUT_SECONDS,
    bootstrap: bool = True,
):
    modal = _ensure_modal_sdk()
    command = startup_command or KEEPALIVE_COMMAND
    sandbox = modal.Sandbox.create(
        "bash",
        "-lc",
        _wrap_sidecar_command(command, bootstrap),
        app=_get_sidecar_app(modal),
        name=SANDBOX_NAME,
        image=_get_sidecar_image(modal),
        gpu="L4",
        timeout=max(1, int(sandbox_timeout_seconds)),
        workdir=HOME_DIR,
        volumes={STATE_ROOT: _get_sidecar_volume(modal)},
    )
    return sandbox


def _summarize_sandbox(sandbox) -> dict[str, object]:
    payload: dict[str, object] = {
        "sandbox_name": SANDBOX_NAME,
    }
    if sandbox is None:
        payload["running"] = False
        return payload

    payload["running"] = True
    try:
        payload["sandbox_id"] = sandbox.object_id
    except Exception:
        pass
    try:
        payload["sandbox_returncode"] = sandbox.poll()
    except Exception:
        pass
    return payload


def _run_sidecar_command_in_sandbox(
    sandbox,
    command: str,
    timeout_seconds: int,
    bootstrap: bool,
) -> dict[str, object]:
    process = sandbox.exec(
        "bash",
        "-lc",
        _wrap_sidecar_command(command, bootstrap),
        timeout=max(1, int(timeout_seconds)),
        text=True,
    )
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    returncode = process.wait()

    payload = {
        "success": returncode == 0,
        "command": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }

    try:
        sync_process = sandbox.exec(
            "bash",
            "-lc",
            SYNC_VOLUME_COMMAND,
            timeout=min(max(30, int(timeout_seconds)), 120),
            text=True,
        )
        sync_stdout = sync_process.stdout.read()
        sync_stderr = sync_process.stderr.read()
        sync_returncode = sync_process.wait()
        if sync_returncode != 0:
            payload["sync_error"] = (
                f"sync exited with {sync_returncode}: "
                f"{(sync_stderr or sync_stdout).strip()}"
            )
    except Exception as exc:
        payload["sync_error"] = f"{type(exc).__name__}: {exc}"

    return payload


def _metadata_payload() -> dict[str, object]:
    metadata = _sidecar_metadata()
    sandbox = _get_running_sidecar_sandbox()
    try:
        payload = {
            "success": True,
            "action": "metadata",
            "metadata": metadata,
        }
        payload.update(_summarize_sandbox(sandbox))
        return payload
    finally:
        _detach_sidecar_sandbox(sandbox)


def _status_payload() -> dict[str, object]:
    metadata = _sidecar_metadata()
    sandbox = _get_running_sidecar_sandbox()
    try:
        payload = {
            "success": True,
            "action": "status",
            "metadata": metadata,
        }
        payload.update(_summarize_sandbox(sandbox))
        return payload
    finally:
        _detach_sidecar_sandbox(sandbox)


def _start_sidecar(
    command: str,
    sandbox_timeout_seconds: int,
    bootstrap: bool,
) -> dict[str, object]:
    metadata = _sidecar_metadata()
    sandbox = _get_running_sidecar_sandbox()
    if sandbox is not None:
        try:
            payload = {
                "success": True,
                "action": "start",
                "created": False,
                "metadata": metadata,
            }
            payload.update(_summarize_sandbox(sandbox))
            if command:
                payload["warning"] = (
                    "Sidecar is already running. Stop it before starting a "
                    "new entrypoint command."
                )
            return payload
        finally:
            _detach_sidecar_sandbox(sandbox)

    sandbox = _create_sidecar_sandbox(
        startup_command=command,
        sandbox_timeout_seconds=sandbox_timeout_seconds,
        bootstrap=bootstrap,
    )
    try:
        payload = {
            "success": True,
            "action": "start",
            "created": True,
            "startup_command": command or KEEPALIVE_COMMAND,
            "metadata": metadata,
        }
        payload.update(_summarize_sandbox(sandbox))
        return payload
    finally:
        _detach_sidecar_sandbox(sandbox)


def _exec_sidecar_command(
    command: str,
    timeout_seconds: int,
    sandbox_timeout_seconds: int,
    bootstrap: bool,
) -> dict[str, object]:
    metadata = _sidecar_metadata()
    sandbox = _get_running_sidecar_sandbox()
    auto_started = False

    if sandbox is None:
        sandbox = _create_sidecar_sandbox(
            sandbox_timeout_seconds=sandbox_timeout_seconds,
            bootstrap=True,
        )
        auto_started = True

    try:
        payload = _run_sidecar_command_in_sandbox(
            sandbox=sandbox,
            command=command,
            timeout_seconds=timeout_seconds,
            bootstrap=bootstrap,
        )
        payload["action"] = "exec"
        payload["auto_started"] = auto_started
        payload["metadata"] = metadata
        payload.update(_summarize_sandbox(sandbox))
        return payload
    finally:
        _detach_sidecar_sandbox(sandbox)


def _stop_sidecar() -> dict[str, object]:
    metadata = _sidecar_metadata()
    sandbox = _get_running_sidecar_sandbox()
    if sandbox is None:
        return {
            "success": True,
            "action": "stop",
            "stopped": False,
            "running": False,
            "sandbox_name": SANDBOX_NAME,
            "metadata": metadata,
        }

    try:
        sandbox.terminate(wait=True)
        return {
            "success": True,
            "action": "stop",
            "stopped": True,
            "running": False,
            "sandbox_name": SANDBOX_NAME,
            "metadata": metadata,
        }
    finally:
        _detach_sidecar_sandbox(sandbox)


def check_hyperspace_sidecar_requirements() -> bool:
    if not HYPERSPACE_SIDECAR_SCRIPT.exists():
        return False
    return importlib.util.find_spec("modal") is not None


def hyperspace_sidecar(
    action: str = "",
    command: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    sandbox_timeout_seconds: int = DEFAULT_SANDBOX_TIMEOUT_SECONDS,
    bootstrap: bool = True,
) -> str:
    action = (action or "").strip().lower()
    command = (command or "").strip()
    timeout_seconds = max(1, int(timeout_seconds))
    sandbox_timeout_seconds = max(1, int(sandbox_timeout_seconds))

    if not action:
        action = "exec" if command else "metadata"

    if action not in VALID_ACTIONS:
        return json.dumps(
            {
                "success": False,
                "error": f"Unknown action '{action}'. Valid actions: {sorted(VALID_ACTIONS)}",
                "metadata": _sidecar_metadata(),
            }
        )

    if action == "metadata":
        try:
            return json.dumps(_metadata_payload())
        except Exception as exc:
            return json.dumps(
                {
                    "success": False,
                    "stage": "metadata",
                    "error": f"{type(exc).__name__}: {exc}",
                    "metadata": _sidecar_metadata(),
                }
            )

    if action == "status":
        try:
            return json.dumps(_status_payload())
        except Exception as exc:
            return json.dumps(
                {
                    "success": False,
                    "stage": "status",
                    "error": f"{type(exc).__name__}: {exc}",
                    "metadata": _sidecar_metadata(),
                }
            )

    if action == "stop":
        try:
            return json.dumps(_stop_sidecar())
        except Exception as exc:
            return json.dumps(
                {
                    "success": False,
                    "stage": "stop",
                    "error": f"{type(exc).__name__}: {exc}",
                    "metadata": _sidecar_metadata(),
                }
            )

    if action == "start":
        try:
            return json.dumps(
                _start_sidecar(
                    command=command,
                    sandbox_timeout_seconds=sandbox_timeout_seconds,
                    bootstrap=bootstrap,
                )
            )
        except Exception as exc:
            return json.dumps(
                {
                    "success": False,
                    "stage": "start",
                    "error": f"{type(exc).__name__}: {exc}",
                    "metadata": _sidecar_metadata(),
                }
            )

    if not command:
        return json.dumps(
            {
                "success": False,
                "stage": "exec",
                "error": "A command is required for action 'exec'.",
                "metadata": _sidecar_metadata(),
            }
        )

    try:
        result = _exec_sidecar_command(
            command=command,
            timeout_seconds=timeout_seconds,
            sandbox_timeout_seconds=sandbox_timeout_seconds,
            bootstrap=bootstrap,
        )
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "stage": "exec",
                "error": f"{type(exc).__name__}: {exc}",
                "metadata": _sidecar_metadata(),
            }
        )

    return json.dumps(result)


HYPERSPACE_SIDECAR_SCHEMA = {
    "name": "hyperspace_sidecar",
    "description": (
        "Manage the named Modal L4 Hyperspace sidecar. Use action='start' to "
        "boot a durable sandbox, action='exec' to run commands inside it, "
        "action='status' to inspect whether it is still running, and "
        "action='stop' to tear it down. If called without an action or command, "
        "it returns sidecar metadata and current sandbox state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(VALID_ACTIONS),
                "description": (
                    "Lifecycle action for the named sidecar sandbox. Defaults to "
                    "'exec' when a command is provided, otherwise 'metadata'."
                ),
            },
            "command": {
                "type": "string",
                "description": (
                    "Shell command to run. For action='exec', this runs inside "
                    "the existing sandbox. For action='start', this becomes the "
                    "sandbox entrypoint command; if omitted, Hermes starts a "
                    "keepalive sandbox you can reuse with later exec calls."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "Maximum time to wait for an exec command. Ignored by "
                    "metadata, status, and stop."
                ),
                "default": DEFAULT_TIMEOUT_SECONDS,
            },
            "sandbox_timeout_seconds": {
                "type": "integer",
                "description": (
                    "Maximum lifetime for a started sandbox. Modal sandboxes can "
                    "run for up to 24 hours."
                ),
                "default": DEFAULT_SANDBOX_TIMEOUT_SECONDS,
            },
            "bootstrap": {
                "type": "boolean",
                "description": (
                    "Create the persistent home/config/cache directories before "
                    "running the sandbox entrypoint or exec command."
                ),
                "default": True,
            },
        },
        "required": [],
    },
}


registry.register(
    name="hyperspace_sidecar",
    toolset="terminal",
    schema=HYPERSPACE_SIDECAR_SCHEMA,
    handler=lambda args, **kw: hyperspace_sidecar(
        action=args.get("action", ""),
        command=args.get("command", ""),
        timeout_seconds=args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        sandbox_timeout_seconds=args.get(
            "sandbox_timeout_seconds",
            DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        ),
        bootstrap=args.get("bootstrap", True),
    ),
    check_fn=check_hyperspace_sidecar_requirements,
    description=HYPERSPACE_SIDECAR_SCHEMA["description"],
)
