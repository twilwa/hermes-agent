# ABOUTME: Defines an on-demand Modal L4 shell target for Hyperspace experiments with a persistent home directory.
# ABOUTME: Keeps GPU usage at zero while idle and persists installs under a named Modal volume between shell sessions.

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import modal

APP_NAME = os.getenv("HERMES_MODAL_HYPERSPACE_APP_NAME", "hermes-hyperspace-sidecar")
VOLUME_NAME = os.getenv("HERMES_MODAL_HYPERSPACE_VOLUME_NAME", f"{APP_NAME}-state")
STATE_ROOT = "/hyperspace-state"
HOME_DIR = f"{STATE_ROOT}/home"
CONFIG_DIR = f"{STATE_ROOT}/config"
DATA_DIR = f"{STATE_ROOT}/share"
CACHE_DIR = f"{STATE_ROOT}/cache"
LINUX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SCRIPT_PATH = "scripts/modal_hyperspace_sidecar.py"
BASE_IMAGE_TAG = "python:3.11-slim-bookworm"
SIDECAR_APT_PACKAGES = (
    "bash",
    "curl",
    "git",
    "ca-certificates",
    "procps",
    "lsof",
    "libgomp1",
    "libssl3",
    "libstdc++6",
)


def _sidecar_env() -> dict[str, str]:
    return {
        "HOME": HOME_DIR,
        "XDG_CONFIG_HOME": CONFIG_DIR,
        "XDG_DATA_HOME": DATA_DIR,
        "XDG_CACHE_HOME": CACHE_DIR,
        "PATH": f"{HOME_DIR}/.local/bin:{LINUX_PATH}",
    }


def _sidecar_metadata() -> dict[str, str]:
    return {
        "app": APP_NAME,
        "gpu": "L4",
        "home": HOME_DIR,
        "volume": VOLUME_NAME,
        "bootstrap": f"python -m modal run {SCRIPT_PATH}",
        "shell": f"python -m modal shell {SCRIPT_PATH}::hyperspace_sidecar --cmd /bin/bash",
    }


def _ensure_sidecar_directories() -> None:
    for path in (HOME_DIR, CONFIG_DIR, DATA_DIR, CACHE_DIR):
        Path(path).mkdir(parents=True, exist_ok=True)


def _execute_hyperspace_command(
    command: str,
    timeout_seconds: int,
    bootstrap: bool,
) -> dict[str, Any]:
    command = (command or "").strip()
    timeout_seconds = max(1, int(timeout_seconds))
    metadata = _sidecar_metadata()

    if not command:
        return {
            "success": True,
            "metadata": metadata,
        }

    try:
        if bootstrap:
            _ensure_sidecar_directories()

        completed = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, **_sidecar_env()},
        )
        result = {
            "success": completed.returncode == 0,
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "metadata": metadata,
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "success": False,
            "command": command,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
            "error": f"Command timed out after {timeout_seconds} seconds",
            "metadata": metadata,
        }
    except Exception as exc:
        result = {
            "success": False,
            "command": command,
            "error": f"{type(exc).__name__}: {exc}",
            "metadata": metadata,
        }
    finally:
        state_volume.commit()

    return result


state_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
image = (
    modal.Image.from_registry(BASE_IMAGE_TAG)
    .apt_install(*SIDECAR_APT_PACKAGES)
    .env(_sidecar_env())
)

app = modal.App(APP_NAME)


@app.function(
    image=image,
    gpu="L4",
    volumes={STATE_ROOT: state_volume},
    timeout=8 * 60 * 60,
)
def hyperspace_sidecar() -> dict[str, str]:
    _ensure_sidecar_directories()
    state_volume.commit()

    metadata = _sidecar_metadata()
    metadata["path"] = os.environ["PATH"]
    return metadata


@app.function(
    image=image,
    gpu="L4",
    volumes={STATE_ROOT: state_volume},
    timeout=8 * 60 * 60,
)
def run_hyperspace_command(
    command: str,
    timeout_seconds: int = 900,
    bootstrap: bool = True,
) -> dict[str, Any]:
    return _execute_hyperspace_command(
        command=command,
        timeout_seconds=timeout_seconds,
        bootstrap=bootstrap,
    )


@app.local_entrypoint()
def main() -> None:
    print(json.dumps(hyperspace_sidecar.remote(), indent=2))
