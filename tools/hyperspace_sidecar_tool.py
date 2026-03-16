# ABOUTME: Runs one-shot commands inside the dedicated Modal L4 Hyperspace sidecar with a persistent home directory.
# ABOUTME: Boots the sidecar on demand, returns structured command output, and exposes the exact bootstrap and shell commands Hermes can reuse.

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from tools.registry import registry

HYPERSPACE_SIDECAR_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "modal_hyperspace_sidecar.py"
)
APP_NAME = os.getenv("HERMES_MODAL_HYPERSPACE_APP_NAME", "hermes-hyperspace-sidecar")
VOLUME_NAME = os.getenv("HERMES_MODAL_HYPERSPACE_VOLUME_NAME", f"{APP_NAME}-state")
DEFAULT_TIMEOUT_SECONDS = 900
COMMAND_FUNCTION_NAME = "run_hyperspace_command"

def _sidecar_metadata() -> dict[str, str]:
    script = str(HYPERSPACE_SIDECAR_SCRIPT)
    return {
        "app": APP_NAME,
        "volume": VOLUME_NAME,
        "script": script,
        "gpu": "L4",
        "bootstrap": f"{sys.executable} -m modal run {script}",
        "shell": (
            f"{sys.executable} -m modal shell "
            f"{script}::hyperspace_sidecar --cmd /bin/bash"
        ),
    }


def _ensure_modal_sdk():
    import modal
    return modal


def _get_sidecar_command_function():
    modal = _ensure_modal_sdk()
    return modal.Function.from_name(APP_NAME, COMMAND_FUNCTION_NAME)


def check_hyperspace_sidecar_requirements() -> bool:
    if not HYPERSPACE_SIDECAR_SCRIPT.exists():
        return False
    return importlib.util.find_spec("modal") is not None


def hyperspace_sidecar(
    command: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    bootstrap: bool = True,
) -> str:
    metadata = _sidecar_metadata()
    command = (command or "").strip()
    timeout_seconds = max(1, int(timeout_seconds))

    if not command:
        return json.dumps(
            {
                "success": True,
                "metadata": metadata,
            }
        )

    try:
        function = _get_sidecar_command_function()
        result = function.remote(
            command=command,
            timeout_seconds=timeout_seconds,
            bootstrap=bootstrap,
        )
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "stage": "remote",
                "error": f"{type(exc).__name__}: {exc}",
                "metadata": metadata,
            }
        )

    return json.dumps(result)


HYPERSPACE_SIDECAR_SCHEMA = {
    "name": "hyperspace_sidecar",
    "description": (
        "Run a one-shot shell command inside the dedicated Modal L4 Hyperspace "
        "sidecar with a persistent home directory. Use this for Hyperspace "
        "agent installs, GPU checks, and experiments that should not run in the "
        "current local or CPU-only environment. If called without a command, it "
        "returns the bootstrap and shell metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Shell command to run inside the Hyperspace sidecar. Leave "
                    "empty to return sidecar metadata only."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum time to wait for the bootstrap and command.",
                "default": DEFAULT_TIMEOUT_SECONDS,
            },
            "bootstrap": {
                "type": "boolean",
                "description": (
                    "Run the sidecar bootstrap step before executing the command. "
                    "Keep this true unless the sidecar is already initialized in "
                    "the current workflow."
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
        command=args.get("command", ""),
        timeout_seconds=args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        bootstrap=args.get("bootstrap", True),
    ),
    check_fn=check_hyperspace_sidecar_requirements,
    description=HYPERSPACE_SIDECAR_SCHEMA["description"],
)
