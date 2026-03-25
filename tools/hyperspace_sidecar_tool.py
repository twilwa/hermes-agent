# ABOUTME: Manages a named Modal L4 sandbox for Hyperspace so Hermes can start, reuse, inspect, and stop a durable GPU sidecar.
# ABOUTME: Keeps the GPU off until explicitly started, reuses the same sandbox across tool calls, and exposes structured lifecycle results.

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import sys
import time
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
ENV_FILE_PATH = f"{DATA_DIR}/../bin/env"
HYPERSPACE_BIN = f"{HOME_DIR}/.local/bin/hyperspace"
HYPERSPACE_STATE_DIR = f"{HOME_DIR}/.hyperspace"
HYPERSPACE_SERVICE_PID_FILE = f"{HYPERSPACE_STATE_DIR}/service.pid"
HYPERSPACE_SUPERVISOR_PID_FILE = f"{HYPERSPACE_STATE_DIR}/supervisor.pid"
HYPERSPACE_PID_FILE = f"{HYPERSPACE_STATE_DIR}/hyperspace.pid"
HYPERSPACE_STATUS_FILE = f"{HYPERSPACE_STATE_DIR}/status.json"
HYPERSPACE_SERVICE_LOG_FILE = f"{HYPERSPACE_STATE_DIR}/runtime.log"
HYPERSPACE_FLASH_ATTN_PATCH_OLD = b'args.push("--flash-attn");'
HYPERSPACE_FLASH_ATTN_PATCH_NEW = b'args.push("-fa","on"    );'
HYPERSPACE_SQLITE_LOADER_PATCH_OLD = (
    "const exeDir = path28.dirname(process.execPath);\n"
    "      const exePath = path28.join(exeDir, name3);\n"
    "      if (fs30.existsSync(exePath)) {\n"
    "        return require(exePath);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const mainDir = path28.dirname(require.main.filename);\n"
    "        const mainPath = path28.join(mainDir, name3);\n"
    "        if (fs30.existsSync(mainPath)) {\n"
    "          return require(mainPath);\n"
    "        }\n"
    "      }"
).encode()
HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_OLD = (
    "const e=path28.dirname(process.execPath);   \n"
    "      const exePath = path28.join(e, name3);\n"
    "      if (fs30.existsSync(exePath)) {\n"
    "        return module2.require(exePath);    \n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path28.dirname(require.main.filename);  \n"
    "        const mainPath = path28.join(m, name3);\n"
    "        if (fs30.existsSync(mainPath)) {\n"
    "          return module2.require(mainPath); \n"
    "        }\n"
    "      }"
).encode()
HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_OLD_2 = (
    "const e=path28.dirname(process.execPath);    \n"
    "      const exePath = path28.join(e, name3);\n"
    "      if (fs30.existsSync(exePath)) {\n"
    "        return module.require(exePath);    \n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path28.dirname(require.main.filename);   \n"
    "        const mainPath = path28.join(m, name3);\n"
    "        if (fs30.existsSync(mainPath)) {\n"
    "          return module.require(mainPath); \n"
        "        }\n"
        "      }"
).encode()
HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_BAD_OLD = (
    "const e=path28.dirname(process.execPath),x=path28.join(e,name3);\n"
    "      if (fs30.existsSync(x)) {\n"
    "        return require.main.require(x);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path28.dirname(require.main.filename),p=path28.join(m,name3);\n"
    "        if (fs30.existsSync(p)) {\n"
    "          return require.main.require(p);\n"
    "        }\n"
    "      }"
).encode().ljust(len(HYPERSPACE_SQLITE_LOADER_PATCH_OLD), b" ")
HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_BAD_OLD_2 = (
    "const d=path28.dirname(process.execPath);\n"
    "      const exePath = path28.join(d, name3);\n"
    "      if (fs30.existsSync(exePath)) {\n"
        "        return module2.require(exePath);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path28.dirname(require.main.filename);\n"
    "        const mainPath = path28.join(m, name3);\n"
    "        if (fs30.existsSync(mainPath)) {\n"
    "          return module2.require(mainPath);\n"
    "        }\n"
    "      }"
).encode().ljust(len(HYPERSPACE_SQLITE_LOADER_PATCH_OLD), b" ")
HYPERSPACE_SQLITE_LOADER_PATCH_NEW = (
    'const r=require("module").createRequire(process.execPath),d=path28.dirname(process.execPath),x=path28.join(d,name3);\n'
    "      if (fs30.existsSync(x)) {\n"
    "        return r(x);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path28.dirname(require.main.filename),p=path28.join(m,name3);\n"
    "        if (fs30.existsSync(p)) {\n"
    "          return r(p);\n"
    "        }\n"
    "      }"
).encode().ljust(len(HYPERSPACE_SQLITE_LOADER_PATCH_OLD), b" ")
HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_OLD = (
    "const exeDir = path30.dirname(process.execPath);\n"
    "      const exePath = path30.join(exeDir, name3);\n"
    "      if (fs32.existsSync(exePath)) {\n"
    "        return require(exePath);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const mainDir = path30.dirname(require.main.filename);\n"
    "        const mainPath = path30.join(mainDir, name3);\n"
    "        if (fs32.existsSync(mainPath)) {\n"
    "          return require(mainPath);\n"
    "        }\n"
    "      }"
).encode()
HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_NEW = (
    'const r=require("module").createRequire(process.execPath),d=path30.dirname(process.execPath),x=path30.join(d,name3);\n'
    "      if (fs32.existsSync(x)) {\n"
    "        return r(x);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path30.dirname(require.main.filename),p=path30.join(m,name3);\n"
    "        if (fs32.existsSync(p)) {\n"
    "          return r(p);\n"
    "        }\n"
    "      }"
).encode().ljust(len(HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_OLD), b" ")
HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_BAD_OLD = (
    "const d=path30.dirname(process.execPath);\n"
    "      const exePath = path30.join(d, name3);\n"
    "      if (fs32.existsSync(exePath)) {\n"
    "        return module2.require(exePath);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path30.dirname(require.main.filename);\n"
    "        const mainPath = path30.join(m, name3);\n"
    "        if (fs32.existsSync(mainPath)) {\n"
    "          return module2.require(mainPath);\n"
    "        }\n"
    "      }"
).encode().ljust(len(HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_OLD), b" ")
HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_BAD_OLD_2 = (
    "const d=path30.dirname(process.execPath);\n"
    "      const exePath = path30.join(d, name3);\n"
    "      if (fs32.existsSync(exePath)) {\n"
    "        return module.require(exePath);\n"
    "      }\n"
    "      if (require.main && require.main.filename) {\n"
    "        const m=path30.dirname(require.main.filename);\n"
    "        const mainPath = path30.join(m, name3);\n"
    "        if (fs32.existsSync(mainPath)) {\n"
    "          return module.require(mainPath);\n"
    "        }\n"
    "      }"
).encode().ljust(len(HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_OLD), b" ")
HYPERSPACE_GEMMA_12B_MIN_VRAM_PATCH_OLD = (
    'id: "gemma-3-12b",\n'
    '        name: "Gemma 3 12B",\n'
    '        parameters: "12B",\n'
    "        sizeGB: 7,\n"
    "        minVRAM: 10,\n"
).encode()
HYPERSPACE_GEMMA_12B_MIN_VRAM_PATCH_NEW = (
    'id: "gemma-3-12b",\n'
    '        name: "Gemma 3 12B",\n'
    '        parameters: "12B",\n'
    "        sizeGB: 7,\n"
    "        minVRAM: 12,\n"
).encode()
HYPERSPACE_DEFAULT_MAX_MODELS_PATCH_OLD = b"DEFAULT_MAX_MODELS = 3;"
HYPERSPACE_DEFAULT_MAX_MODELS_PATCH_NEW = b"DEFAULT_MAX_MODELS = 1;"
HYPERSPACE_LINUX_CUDA_PLATFORM_PATCH_OLD = (
    b'return hasNvidiaGPU() ? "linux-cuda" : "linux-x64";'
)
HYPERSPACE_LINUX_CUDA_PLATFORM_PATCH_NEW = (
    b'return hasNvidiaGPU() ? "linux-x64"  : "linux-x64";'
)
HYPERSPACE_RUNTIME_BINARY_PATCHES = (
    (
        "flash_attn_flag",
        (HYPERSPACE_FLASH_ATTN_PATCH_OLD,),
        HYPERSPACE_FLASH_ATTN_PATCH_NEW,
    ),
    (
        "sqlite_native_loader",
        (
            HYPERSPACE_SQLITE_LOADER_PATCH_OLD,
            HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_OLD,
            HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_OLD_2,
            HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_BAD_OLD,
            HYPERSPACE_SQLITE_LOADER_PATCH_REPAIR_BAD_OLD_2,
        ),
        HYPERSPACE_SQLITE_LOADER_PATCH_NEW,
    ),
    (
        "sqlite_native_loader_current",
        (
            HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_OLD,
            HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_BAD_OLD,
            HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_BAD_OLD_2,
        ),
        HYPERSPACE_SQLITE_LOADER_PATCH_CURRENT_NEW,
    ),
    (
        "gemma_12b_min_vram",
        (HYPERSPACE_GEMMA_12B_MIN_VRAM_PATCH_OLD,),
        HYPERSPACE_GEMMA_12B_MIN_VRAM_PATCH_NEW,
    ),
    (
        "default_max_models",
        (HYPERSPACE_DEFAULT_MAX_MODELS_PATCH_OLD,),
        HYPERSPACE_DEFAULT_MAX_MODELS_PATCH_NEW,
    ),
    (
        "linux_cuda_platform",
        (HYPERSPACE_LINUX_CUDA_PLATFORM_PATCH_OLD,),
        HYPERSPACE_LINUX_CUDA_PLATFORM_PATCH_NEW,
    ),
)
VALID_SERVICES = {"", "hyperspace"}
VALID_ACTIONS = {"metadata", "start", "exec", "status", "stop"}
VALID_HYPERSPACE_ACTIONS = {"chat", "ensure", "report", "status"}
HYPERSPACE_API_BASE_URL = "http://127.0.0.1:8080"
HYPERSPACE_DEFAULT_PROFILE = "full"
HYPERSPACE_DEFAULT_RESOURCE_MODE = "balanced"
HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT = True
HYPERSPACE_RESOURCE_MODE_BUDGET_PERCENT = {
    "chill": 30,
    "balanced": 50,
    "power": 80,
}
HYPERSPACE_MODEL_SELECTION_GUIDANCE = (
    "Startup model selection is automatic and depends on detected VRAM plus "
    "the resource mode budget: chill=30%, balanced=50%, power=80%. The chat "
    "'model' parameter only affects the API request and does not pin startup "
    "model selection."
)
HYPERSPACE_API_READY_POLL_INTERVAL_SECONDS = 2
HYPERSPACE_API_READY_PROBE_TIMEOUT_SECONDS = 5
HYPERSPACE_API_READY_STATUS_REFRESH_SECONDS = 10
HYPERSPACE_CHAT_WARMUP_WAIT_LIMIT_SECONDS = 300
HYPERSPACE_PEER_ID_PATTERN = re.compile(r"\b12D3Koo[A-Za-z0-9]+\b")
HYPERSPACE_PEER_COUNT_PATTERNS = (
    re.compile(r"\bpeers?\s*[:=]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bpeer\s+count\s*[:=]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bconnected\s+to\s+(\d+)\s+peers?\b", re.IGNORECASE),
)
HYPERSPACE_MODEL_LOADING_PATTERN = re.compile(
    r"Loading\s+([A-Za-z0-9._-]+):\s*(\d+)%",
    re.IGNORECASE,
)


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
            f"if [ -f {shlex.quote(ENV_FILE_PATH)} ]; then . {shlex.quote(ENV_FILE_PATH)}; fi",
            'export PATH="$HOME/.local/bin:$PATH"',
            'export XDG_RUNTIME_DIR="/run/user/$(id -u)"',
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


def _apply_hyperspace_runtime_binary_patches(
    binary_data: bytes,
) -> tuple[bytes, list[str], list[str], list[str]]:
    patched_data = binary_data
    applied: list[str] = []
    already_patched: list[str] = []
    missing: list[str] = []

    for name, old_variants, new in HYPERSPACE_RUNTIME_BINARY_PATCHES:
        for old in old_variants:
            if len(old) != len(new):
                raise ValueError(
                    f"Hyperspace runtime patch '{name}' must preserve binary size."
                )
        if new in patched_data:
            already_patched.append(name)
            continue
        for old in old_variants:
            if old in patched_data:
                patched_data = patched_data.replace(old, new, 1)
                applied.append(name)
                break
        else:
            missing.append(name)

    return patched_data, applied, already_patched, missing


def _build_hyperspace_service_command(
    service_args: str = "",
    *,
    disable_startup_update: bool = HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
) -> str:
    command = [HYPERSPACE_BIN, "start", "--headless", "--cuda"]
    extra_args = (service_args or "").strip()
    if extra_args:
        command.extend(shlex.split(extra_args))

    command_json = json.dumps(command)
    state_dir_json = json.dumps(HYPERSPACE_STATE_DIR)
    log_path_json = json.dumps(HYPERSPACE_SERVICE_LOG_FILE)
    service_pid_json = json.dumps(HYPERSPACE_SERVICE_PID_FILE)
    supervisor_pid_json = json.dumps(HYPERSPACE_SUPERVISOR_PID_FILE)
    hyperspace_pid_json = json.dumps(HYPERSPACE_PID_FILE)
    status_json = json.dumps(HYPERSPACE_STATUS_FILE)
    binary_path_json = json.dumps(HYPERSPACE_BIN)
    runtime_patches_repr = repr(HYPERSPACE_RUNTIME_BINARY_PATCHES)
    disable_startup_update_json = json.dumps(bool(disable_startup_update))
    supervisor_runtime_patches_json = json.dumps(
        [
            (
                name,
                [variant.decode("latin1") for variant in old_variants],
                new.decode("latin1"),
            )
            for name, old_variants, new in HYPERSPACE_RUNTIME_BINARY_PATCHES
        ]
    )
    return f"""python - <<'PY'
import json
import os
import pathlib
import subprocess
import sys
import time

state_dir = pathlib.Path({state_dir_json})
log_path = pathlib.Path({log_path_json})
service_pid_path = pathlib.Path({service_pid_json})
supervisor_pid_path = pathlib.Path({supervisor_pid_json})
hyperspace_pid_path = pathlib.Path({hyperspace_pid_json})
status_path = pathlib.Path({status_json})
binary_path = pathlib.Path({binary_path_json})
command = {command_json}
runtime_patches = {runtime_patches_repr}

state_dir.mkdir(parents=True, exist_ok=True)
log_path.touch()
for stale_path in (service_pid_path, supervisor_pid_path, hyperspace_pid_path, status_path):
    stale_path.unlink(missing_ok=True)

applied_patches = []
already_patched = []
missing_patches = []
if binary_path.exists():
    binary_data = binary_path.read_bytes()
    for name, old_variants, new in runtime_patches:
        for old in old_variants:
            if len(old) != len(new):
                raise RuntimeError(
                    f"Hyperspace runtime patch '{{name}}' must preserve binary size."
                )
        if new in binary_data:
            already_patched.append(name)
            continue
        for old in old_variants:
            if old in binary_data:
                binary_data = binary_data.replace(old, new, 1)
                applied_patches.append(name)
                break
        else:
            missing_patches.append(name)
    if applied_patches:
        binary_path.write_bytes(binary_data)

supervisor_config = {{
    "state_dir": str(state_dir),
    "log_path": str(log_path),
    "service_pid_path": str(service_pid_path),
    "supervisor_pid_path": str(supervisor_pid_path),
    "status_path": str(status_path),
    "binary_path": str(binary_path),
    "command": command,
    "disable_startup_update": json.loads({disable_startup_update_json!r}),
    "runtime_patches": json.loads({supervisor_runtime_patches_json!r}),
}}
supervisor_code = '''
import json
import os
import pathlib
import signal
import subprocess
import time

config = json.loads(os.environ["HYPERSPACE_SUPERVISOR_CONFIG"])
state_dir = pathlib.Path(config["state_dir"])
log_path = pathlib.Path(config["log_path"])
service_pid_path = pathlib.Path(config["service_pid_path"])
supervisor_pid_path = pathlib.Path(config["supervisor_pid_path"])
status_path = pathlib.Path(config["status_path"])
binary_path = pathlib.Path(config["binary_path"])
command = config["command"]
disable_startup_update = bool(config.get("disable_startup_update", False))
runtime_patches = config["runtime_patches"]

state_dir.mkdir(parents=True, exist_ok=True)
log_path.touch()

child = None
stopping = False

def write_status(state, **extra):
    payload = {{"service": "hyperspace", "state": state, "command": command}}
    payload["startup_update_disabled"] = disable_startup_update
    payload.update(extra)
    status_path.write_text(json.dumps(payload))

def apply_runtime_patches():
    if not binary_path.exists():
        return []
    binary_data = binary_path.read_bytes()
    applied = []
    for name, old_variants, new in runtime_patches:
        old_variants = [variant.encode("latin1") for variant in old_variants]
        new = new.encode("latin1")
        if new in binary_data:
            continue
        for old in old_variants:
            if old in binary_data:
                binary_data = binary_data.replace(old, new, 1)
                applied.append(name)
                break
    if applied:
        binary_path.write_bytes(binary_data)
    return applied

def handle_signal(signum, frame):
    global stopping
    stopping = True
    write_status(
        "stopping",
        supervisor_pid=str(os.getpid()),
        service_pid=str(child.pid) if child else None,
    )
    if child and child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass

for signum in (signal.SIGTERM, signal.SIGINT):
    signal.signal(signum, handle_signal)

supervisor_pid_path.write_text(str(os.getpid()))
write_status("starting", supervisor_pid=str(os.getpid()))

while True:
    if stopping:
        break
    try:
        applied_patches = apply_runtime_patches()
        child_env = os.environ.copy()
        if disable_startup_update:
            child_env.setdefault("HYPERSPACE_SKIP_STARTUP_UPDATE", "1")
        else:
            child_env.pop("HYPERSPACE_SKIP_STARTUP_UPDATE", None)
        with log_path.open("a") as log_file:
            child = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=child_env,
            )
    except Exception as exc:
        write_status(
            "launch_failed",
            supervisor_pid=str(os.getpid()),
            error=f"{{type(exc).__name__}}: {{exc}}",
        )
        time.sleep(5)
        continue

    service_pid_path.write_text(str(child.pid))
    write_status(
        "running",
        supervisor_pid=str(os.getpid()),
        service_pid=str(child.pid),
        applied_patches=applied_patches,
    )
    returncode = child.wait()
    current_pid = service_pid_path.read_text(errors="replace").strip() if service_pid_path.exists() else ""
    if current_pid == str(child.pid):
        service_pid_path.unlink(missing_ok=True)
    child = None
    if stopping:
        break
    write_status(
        "restarting",
        supervisor_pid=str(os.getpid()),
        last_returncode=returncode,
        last_exit_at=time.time(),
    )
    time.sleep(5)

service_pid_path.unlink(missing_ok=True)
supervisor_pid_path.unlink(missing_ok=True)
write_status("stopped", stopped_at=time.time())
'''
env = os.environ.copy()
env["HYPERSPACE_SUPERVISOR_CONFIG"] = json.dumps(supervisor_config)
with log_path.open("a") as log_file:
    child = subprocess.Popen(
        [sys.executable, "-c", supervisor_code],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

time.sleep(2)
returncode = child.poll()
payload = {{
    "launched": returncode is None,
    "pid": child.pid,
    "returncode": returncode,
    "applied_patches": applied_patches,
    "already_patched": already_patched,
    "missing_patches": missing_patches,
}}
print(json.dumps(payload))
if returncode is not None:
    sys.exit(returncode)
PY"""


def _coerce_hyperspace_command(command: object) -> list[str]:
    if isinstance(command, list):
        return [str(item) for item in command]
    if isinstance(command, tuple):
        return [str(item) for item in command]
    if isinstance(command, str):
        try:
            return shlex.split(command)
        except ValueError:
            return []
    return []


def _extract_hyperspace_launch_metadata(payload: dict[str, object]) -> dict[str, object]:
    command = _coerce_hyperspace_command(payload.get("command"))
    profile = HYPERSPACE_DEFAULT_PROFILE
    resource_mode = HYPERSPACE_DEFAULT_RESOURCE_MODE
    status = payload.get("status")

    for index, arg in enumerate(command):
        if arg == "--profile" and index + 1 < len(command):
            profile = str(command[index + 1]).strip().lower() or profile
        if arg == "--mode" and index + 1 < len(command):
            resource_mode = str(command[index + 1]).strip().lower() or resource_mode

    if isinstance(status, dict):
        reported_mode = str(status.get("allocationMode") or "").strip().lower()
        if reported_mode:
            resource_mode = reported_mode

    if resource_mode not in HYPERSPACE_RESOURCE_MODE_BUDGET_PERCENT:
        resource_mode = HYPERSPACE_DEFAULT_RESOURCE_MODE

    metadata: dict[str, object] = {
        "launch_profile": profile,
        "resource_mode": resource_mode,
        "resource_mode_budget_percent": HYPERSPACE_RESOURCE_MODE_BUDGET_PERCENT[
            resource_mode
        ],
        "managed_startup_update_default": HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
        "model_request_pins_startup": False,
        "model_selection_guidance": HYPERSPACE_MODEL_SELECTION_GUIDANCE,
    }
    startup_update_disabled = payload.get("startup_update_disabled")
    if startup_update_disabled is None and "disable_startup_update" in payload:
        startup_update_disabled = payload["disable_startup_update"]
    if startup_update_disabled is not None:
        metadata["startup_update_disabled"] = bool(startup_update_disabled)
    return metadata


def _extract_hyperspace_runtime_metadata(payload: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    log_tail = str(payload.get("log_tail") or "")
    matches = list(HYPERSPACE_MODEL_LOADING_PATTERN.finditer(log_tail))
    if matches:
        latest = matches[-1]
        metadata["loading_model"] = latest.group(1)
        metadata["model_loading_progress_percent"] = int(latest.group(2))
        metadata["model_loading"] = (
            metadata["model_loading_progress_percent"] < 100
        )

    status = payload.get("status")
    if isinstance(status, dict):
        loaded_models = status.get("loadedModels")
        if isinstance(loaded_models, list):
            metadata["loaded_models"] = [str(model) for model in loaded_models]

    return metadata


def _build_hyperspace_service_status_command() -> str:
    pid_path = json.dumps(HYPERSPACE_SERVICE_PID_FILE)
    supervisor_pid_path = json.dumps(HYPERSPACE_SUPERVISOR_PID_FILE)
    fallback_pid_path = json.dumps(HYPERSPACE_PID_FILE)
    status_path = json.dumps(HYPERSPACE_STATUS_FILE)
    log_path = json.dumps(HYPERSPACE_SERVICE_LOG_FILE)
    binary_path = json.dumps(HYPERSPACE_BIN)
    return f"""python - <<'PY'
import json
import os
import pathlib
import socket
import subprocess
import urllib.request

pid_path = pathlib.Path({pid_path})
supervisor_pid_path = pathlib.Path({supervisor_pid_path})
fallback_pid_path = pathlib.Path({fallback_pid_path})
status_path = pathlib.Path({status_path})
log_path = pathlib.Path({log_path})
binary_path = pathlib.Path({binary_path})

def read_pid(path):
    if not path.exists():
        return None, False
    text = path.read_text(errors="replace").strip()
    if text:
        pid = text
        try:
            os.kill(int(text), 0)
            return pid, True
        except Exception:
            return pid, False
    return None, False

supervisor_pid, supervisor_running = read_pid(supervisor_pid_path)
pid, service_running = read_pid(pid_path)
if pid is None:
    pid, service_running = read_pid(fallback_pid_path)

log_tail = ""
if log_path.exists():
    log_tail = "".join(log_path.read_text(errors="replace").splitlines(True)[-40:])

status_data = {{}}
if status_path.exists():
    try:
        loaded = json.loads(status_path.read_text(errors="replace"))
        if isinstance(loaded, dict):
            status_data = loaded
    except Exception:
        status_data = {{}}

api_healthy = False
api_listening = False
api_error = ""
api_connect_error = ""
try:
    with socket.create_connection(("127.0.0.1", 8080), timeout=2):
        api_listening = True
except Exception as exc:
    api_connect_error = f"{{type(exc).__name__}}: {{exc}}"

try:
    with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5) as response:
        api_healthy = 200 <= response.status < 300
except Exception as exc:
    api_error = f"{{type(exc).__name__}}: {{exc}}"

whoami = {{}}
if binary_path.exists():
    try:
        completed = subprocess.run(
            ["bash", "-lc", f'"{{binary_path}}" hive whoami'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        whoami = {{
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }}
    except Exception as exc:
        whoami = {{"error": f"{{type(exc).__name__}}: {{exc}}"}}

payload = {{
    "service": "hyperspace",
    "supervisor_pid": supervisor_pid,
    "supervisor_running": supervisor_running,
    "service_pid": pid,
    "service_running": service_running,
    "api_listening": api_listening,
    "api_healthy": api_healthy,
    "log_path": str(log_path),
    "log_tail": log_tail,
    "whoami": whoami,
}}
if status_data:
    payload["status"] = status_data
if api_connect_error:
    payload["api_connect_error"] = api_connect_error
if api_error:
    payload["api_error"] = api_error

print(json.dumps(payload))
PY"""


def _normalize_service(service: str) -> str:
    value = (service or "").strip().lower()
    if value not in VALID_SERVICES:
        raise ValueError(
            f"Unknown service '{service}'. Valid services: {sorted(s for s in VALID_SERVICES if s)}"
        )
    return value


def _get_sidecar_app(modal=None):
    modal = modal or _ensure_modal_sdk()
    return modal.App.lookup(APP_NAME, create_if_missing=True)


def _get_sidecar_volume(modal=None):
    modal = modal or _ensure_modal_sdk()
    return modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _get_sidecar_image(modal=None):
    modal = modal or _ensure_modal_sdk()
    return (
        modal.Image.from_registry(BASE_IMAGE_TAG)
        .apt_install(*SIDECAR_APT_PACKAGES)
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


def _status_service_payload(service: str) -> dict[str, object]:
    payload = _status_payload()
    if service != "hyperspace" or not payload.get("running"):
        return payload

    sandbox = _get_running_sidecar_sandbox()
    try:
        process = sandbox.exec(
            "bash",
            "-lc",
            _wrap_sidecar_command(_build_hyperspace_service_status_command(), True),
            timeout=60,
            text=True,
        )
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        returncode = process.wait()
        if returncode == 0 and stdout.strip():
            payload.update(json.loads(stdout))
        else:
            payload["service"] = service
            payload["service_running"] = False
            payload["service_status_error"] = (stderr or stdout).strip()
        return _normalize_hyperspace_payload(payload)
    finally:
        _detach_sidecar_sandbox(sandbox)


def _start_sidecar(
    command: str,
    service: str,
    service_args: str,
    sandbox_timeout_seconds: int,
    bootstrap: bool,
    disable_startup_update: bool,
) -> dict[str, object]:
    metadata = _sidecar_metadata()
    sandbox = _get_running_sidecar_sandbox()
    if service == "hyperspace":
        sandbox_created = False
        if sandbox is None:
            sandbox = _create_sidecar_sandbox(
                sandbox_timeout_seconds=sandbox_timeout_seconds,
                bootstrap=True,
            )
            sandbox_created = True

        try:
            current_status = _status_service_payload(service)
            supervisor_running = current_status.get(
                "supervisor_running",
                current_status.get("service_running", False),
            )
            if supervisor_running:
                payload = {
                    "success": True,
                    "action": "start",
                    "created": sandbox_created,
                    "startup_command": KEEPALIVE_COMMAND,
                    "launch_command": _build_hyperspace_service_command(
                        service_args,
                        disable_startup_update=disable_startup_update,
                    ),
                    "metadata": metadata,
                    "service": service,
                    "warning": "Hyperspace supervisor is already running.",
                }
                if service_args:
                    payload["service_args"] = service_args
                payload["disable_startup_update"] = disable_startup_update
                payload.update(_summarize_sandbox(sandbox))
                payload["supervisor_running"] = supervisor_running
                for key in (
                    "command",
                    "supervisor_pid",
                    "service_pid",
                    "service_running",
                    "api_healthy",
                    "startup_update_disabled",
                    "log_path",
                    "log_tail",
                    "status",
                    "api_error",
                    "whoami",
                ):
                    if key in current_status:
                        payload[key] = current_status[key]
                return payload

            launch_command = _build_hyperspace_service_command(
                service_args,
                disable_startup_update=disable_startup_update,
            )
            launch_payload = _run_sidecar_command_in_sandbox(
                sandbox=sandbox,
                command=launch_command,
                timeout_seconds=120,
                bootstrap=True,
            )
            launch_details = None
            if (launch_payload.get("stdout") or "").strip():
                try:
                    launch_details = json.loads(launch_payload["stdout"])
                except (TypeError, ValueError):
                    launch_details = None
            current_status = {}
            for attempt in range(12):
                current_status = _status_service_payload(service)
                supervisor_running = current_status.get(
                    "supervisor_running",
                    current_status.get("service_running", False),
                )
                if current_status.get("api_healthy") or current_status.get("service_running"):
                    break
                if not supervisor_running:
                    break
                if attempt >= 1:
                    time.sleep(2)
            supervisor_running = current_status.get(
                "supervisor_running",
                current_status.get("service_running", False),
            )

            payload = {
                "success": bool(
                    launch_payload.get("success")
                    and supervisor_running
                    and (current_status.get("service_running") or current_status.get("api_healthy"))
                ),
                "action": "start",
                "created": sandbox_created,
                "startup_command": KEEPALIVE_COMMAND,
                "launch_command": launch_command,
                "metadata": metadata,
                "service": service,
                "launch_returncode": launch_payload.get("returncode"),
                "launch_stdout": launch_payload.get("stdout", ""),
                "launch_stderr": launch_payload.get("stderr", ""),
            }
            if launch_details is not None:
                payload["launch_details"] = launch_details
                for key in ("applied_patches", "already_patched", "missing_patches"):
                    if key in launch_details:
                        payload[key] = launch_details[key]
            if service_args:
                payload["service_args"] = service_args
            payload["disable_startup_update"] = disable_startup_update
            payload.update(_summarize_sandbox(sandbox))
            payload["supervisor_running"] = supervisor_running
            for key in (
                "command",
                "supervisor_pid",
                "service_pid",
                "service_running",
                "api_healthy",
                "startup_update_disabled",
                "log_path",
                "log_tail",
                "status",
                "api_error",
                "whoami",
            ):
                if key in current_status:
                    payload[key] = current_status[key]
            if launch_payload.get("sync_error"):
                payload["sync_error"] = launch_payload["sync_error"]
            return payload
        finally:
            _detach_sidecar_sandbox(sandbox)

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
    service: str = "",
    service_args: str = "",
    command: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    sandbox_timeout_seconds: int = DEFAULT_SANDBOX_TIMEOUT_SECONDS,
    bootstrap: bool = True,
    disable_startup_update: bool = HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
) -> str:
    action = (action or "").strip().lower()
    try:
        service = _normalize_service(service)
    except ValueError as exc:
        return json.dumps(
            {
                "success": False,
                "error": str(exc),
                "metadata": _sidecar_metadata(),
            }
        )
    command = (command or "").strip()
    service_args = (service_args or "").strip()
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
            return json.dumps(_status_service_payload(service))
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
                    service=service,
                    service_args=service_args,
                    sandbox_timeout_seconds=sandbox_timeout_seconds,
                    bootstrap=bootstrap,
                    disable_startup_update=bool(disable_startup_update),
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


def _summarize_hyperspace_connection(whoami: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "connection_state": "unavailable",
        "connected_to_hive": None,
        "hive_status": "UNAVAILABLE",
        "hive_connected": None,
        "whoami_stdout": "",
        "whoami_stderr": "",
    }
    if not isinstance(whoami, dict):
        return payload

    stdout = (whoami.get("stdout") or "").strip()
    stderr = (whoami.get("stderr") or "").strip()
    payload["whoami_stdout"] = stdout
    payload["whoami_stderr"] = stderr

    if "returncode" in whoami:
        payload["whoami_returncode"] = whoami["returncode"]
    if whoami.get("error"):
        payload["whoami_error"] = whoami["error"]
        payload["connection_state"] = "error"
        payload["hive_status"] = "ERROR"
        return payload

    peer_id_match = HYPERSPACE_PEER_ID_PATTERN.search(stdout)
    if peer_id_match:
        payload["peer_id"] = peer_id_match.group(0)
    for pattern in HYPERSPACE_PEER_COUNT_PATTERNS:
        match = pattern.search(stdout)
        if match:
            payload["peer_count"] = int(match.group(1))
            break

    upper_stdout = stdout.upper()
    if "DISCONNECTED" in upper_stdout:
        payload["connection_state"] = "disconnected"
        payload["connected_to_hive"] = False
        payload["hive_status"] = "DISCONNECTED"
        payload["hive_connected"] = False
        return payload
    if "CONNECTED" in upper_stdout:
        payload["connection_state"] = "connected"
        payload["connected_to_hive"] = True
        payload["hive_status"] = "CONNECTED"
        payload["hive_connected"] = True
        return payload
    if stdout or stderr or "returncode" in whoami:
        payload["connection_state"] = "unknown"
        payload["hive_status"] = "UNKNOWN"
    return payload


def _normalize_hyperspace_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    normalized.update(_summarize_hyperspace_connection(normalized.get("whoami")))
    normalized.update(_extract_hyperspace_launch_metadata(normalized))
    normalized.update(_extract_hyperspace_runtime_metadata(normalized))

    running = bool(normalized.get("running"))
    supervisor_running = bool(normalized.get("supervisor_running"))
    service_running = bool(normalized.get("service_running"))
    api_healthy = bool(normalized.get("api_healthy"))
    api_listening = bool(normalized.get("api_listening"))
    connected_to_hive = normalized.get("connected_to_hive")
    api_error = str(normalized.get("api_error") or "")
    api_connect_error = str(normalized.get("api_connect_error") or "")
    model_loading = bool(normalized.get("model_loading"))

    if api_listening and model_loading:
        api_state = "warming_up"
    elif api_healthy:
        api_state = "healthy"
    elif api_listening and "timed out" in api_error.lower():
        api_state = "stalled"
    elif api_listening:
        api_state = "listening"
    elif api_connect_error or api_error:
        api_state = "unreachable"
    else:
        api_state = "unknown"

    if not running:
        health = "stopped"
    elif api_healthy and connected_to_hive is True:
        health = "healthy"
    elif supervisor_running or service_running or api_healthy:
        health = "degraded"
    else:
        health = "starting"

    normalized["api_state"] = api_state
    normalized["health"] = health
    normalized["ready"] = bool(api_healthy and connected_to_hive is True)
    return normalized


def _wait_for_hyperspace_api_ready(
    status_payload: dict[str, object],
    *,
    timeout_seconds: int,
) -> dict[str, object]:
    latest_status = dict(status_payload)
    if latest_status.get("api_healthy"):
        return latest_status

    wait_budget = min(max(1, int(timeout_seconds)), HYPERSPACE_CHAT_WARMUP_WAIT_LIMIT_SECONDS)
    deadline = time.time() + wait_budget
    next_status_refresh_at = 0.0
    last_probe_error = ""

    while time.time() < deadline:
        remaining_seconds = max(1, int(deadline - time.time()))
        probe = _request_hyperspace_api(
            "/health",
            timeout_seconds=min(
                remaining_seconds,
                HYPERSPACE_API_READY_PROBE_TIMEOUT_SECONDS,
            ),
        )
        if probe.get("ok"):
            refreshed_status = _get_hyperspace_status_payload()
            refreshed_status["api_healthy"] = True
            refreshed_status = _normalize_hyperspace_payload(refreshed_status)
            if not refreshed_status.get("model_loading"):
                return refreshed_status
            latest_status = refreshed_status
            last_probe_error = ""

        last_probe_error = str(probe.get("error") or "")
        now = time.time()
        if now >= next_status_refresh_at:
            latest_status = _get_hyperspace_status_payload()
            if not latest_status.get("running") or not latest_status.get("service_running"):
                return latest_status
            if not latest_status.get("api_listening") and not latest_status.get("model_loading"):
                return latest_status
            next_status_refresh_at = now + HYPERSPACE_API_READY_STATUS_REFRESH_SECONDS

        if not latest_status.get("model_loading") and "timed out" not in last_probe_error.lower():
            break

        time.sleep(
            min(
                HYPERSPACE_API_READY_POLL_INTERVAL_SECONDS,
                max(0.1, deadline - time.time()),
            )
        )

    if last_probe_error and not latest_status.get("api_error"):
        latest_status = dict(latest_status)
        latest_status["api_error"] = last_probe_error
        latest_status = _normalize_hyperspace_payload(latest_status)
    return latest_status


def _get_hyperspace_status_payload() -> dict[str, object]:
    return _normalize_hyperspace_payload(_status_service_payload("hyperspace"))


def _ensure_hyperspace_payload(
    service_args: str,
    sandbox_timeout_seconds: int,
    disable_startup_update: bool,
) -> dict[str, object]:
    payload = _start_sidecar(
        command="",
        service="hyperspace",
        service_args=service_args,
        sandbox_timeout_seconds=sandbox_timeout_seconds,
        bootstrap=True,
        disable_startup_update=disable_startup_update,
    )
    return _normalize_hyperspace_payload(payload)


def _build_hyperspace_api_request_command(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout_seconds: int,
) -> str:
    url_json = json.dumps(f"{HYPERSPACE_API_BASE_URL}{path}")
    body_expr = "None" if body is None else json.dumps(body)
    method_json = json.dumps((method or "GET").upper())
    timeout_json = json.dumps(max(1, int(timeout_seconds)))
    return f"""python - <<'PY'
import json
import sys
import urllib.error
import urllib.request

url = {url_json}
payload = {body_expr}
headers = {{"Accept": "application/json"}}
data = None
if payload is not None:
    data = json.dumps(payload).encode("utf-8")
    headers["Content-Type"] = "application/json"

request = urllib.request.Request(url, data=data, headers=headers, method={method_json})
try:
    with urllib.request.urlopen(request, timeout={timeout_json}) as response:
        raw = response.read().decode("utf-8", errors="replace")
        body = raw
        try:
            body = json.loads(raw)
        except Exception:
            pass
        print(json.dumps({{"ok": True, "status": response.status, "body": body}}))
except urllib.error.HTTPError as exc:
    raw = exc.read().decode("utf-8", errors="replace")
    body = raw
    try:
        body = json.loads(raw)
    except Exception:
        pass
    print(json.dumps({{"ok": False, "status": exc.code, "body": body, "error": f"HTTPError: {{exc}}"}}))
    sys.exit(1)
except Exception as exc:
    print(json.dumps({{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}))
    sys.exit(1)
PY"""


def _request_hyperspace_api(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    sandbox = _get_running_sidecar_sandbox()
    if sandbox is None:
        return {
            "ok": False,
            "error": "Hyperspace sandbox is not running.",
        }

    try:
        exec_payload = _run_sidecar_command_in_sandbox(
            sandbox=sandbox,
            command=_build_hyperspace_api_request_command(
                path,
                method=method,
                body=body,
                timeout_seconds=timeout_seconds,
            ),
            timeout_seconds=max(30, int(timeout_seconds) + 15),
            bootstrap=True,
        )
    finally:
        _detach_sidecar_sandbox(sandbox)

    stdout = (exec_payload.get("stdout") or "").strip()
    if stdout:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "Hyperspace API request returned invalid JSON.",
                "stdout": exec_payload.get("stdout", ""),
                "stderr": exec_payload.get("stderr", ""),
                "returncode": exec_payload.get("returncode"),
            }

    return {
        "ok": False,
        "error": (exec_payload.get("stderr") or "Hyperspace API request produced no output.").strip(),
        "returncode": exec_payload.get("returncode"),
    }


def check_hyperspace_requirements() -> bool:
    return check_hyperspace_sidecar_requirements()


def hyperspace(
    action: str = "",
    service_args: str = "",
    messages: list[dict[str, object]] | None = None,
    model: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    sandbox_timeout_seconds: int = DEFAULT_SANDBOX_TIMEOUT_SECONDS,
    disable_startup_update: bool = HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
) -> str:
    action = (action or "status").strip().lower()
    service_args = (service_args or "").strip()
    timeout_seconds = max(1, int(timeout_seconds))
    sandbox_timeout_seconds = max(1, int(sandbox_timeout_seconds))
    messages = list(messages or [])

    if action not in VALID_HYPERSPACE_ACTIONS:
        return json.dumps(
            {
                "success": False,
                "error": (
                    f"Unknown action '{action}'. Valid actions: "
                    f"{sorted(VALID_HYPERSPACE_ACTIONS)}"
                ),
                "metadata": _sidecar_metadata(),
            }
        )

    try:
        if action == "status":
            return json.dumps(_get_hyperspace_status_payload())

        if action == "ensure":
            return json.dumps(
                _ensure_hyperspace_payload(
                    service_args=service_args,
                    sandbox_timeout_seconds=sandbox_timeout_seconds,
                    disable_startup_update=bool(disable_startup_update),
                )
            )

        if action == "report":
            payload = _get_hyperspace_status_payload()
            if payload.get("running"):
                payload["api_health"] = _request_hyperspace_api(
                    "/health",
                    timeout_seconds=min(timeout_seconds, 60),
                )
            return json.dumps(payload)

        if not messages:
            return json.dumps(
                {
                    "success": False,
                    "action": "chat",
                    "error": "The 'messages' parameter is required for action 'chat'.",
                    "metadata": _sidecar_metadata(),
                }
            )

        status_payload = _ensure_hyperspace_payload(
            service_args=service_args,
            sandbox_timeout_seconds=sandbox_timeout_seconds,
            disable_startup_update=bool(disable_startup_update),
        )
        if not status_payload.get("success"):
            return json.dumps(status_payload)
        if (
            status_payload.get("running")
            and status_payload.get("service_running")
            and (
                not status_payload.get("api_healthy")
                or status_payload.get("model_loading")
            )
        ):
            status_payload = _wait_for_hyperspace_api_ready(
                status_payload,
                timeout_seconds=timeout_seconds,
            )

        request_body: dict[str, object] = {
            "messages": messages,
        }
        if model:
            request_body["model"] = model
        if temperature is not None:
            request_body["temperature"] = temperature
        if max_tokens is not None:
            request_body["max_tokens"] = max_tokens

        chat_payload = _request_hyperspace_api(
            "/v1/chat/completions",
            method="POST",
            body=request_body,
            timeout_seconds=timeout_seconds,
        )

        payload = {
            "success": bool(chat_payload.get("ok")),
            "action": "chat",
            "metadata": _sidecar_metadata(),
            "message_count": len(messages),
            "response": chat_payload.get("body"),
            "status_code": chat_payload.get("status"),
        }
        if model:
            payload["model"] = model
        for key in (
            "running",
            "sandbox_name",
            "sandbox_id",
            "sandbox_returncode",
            "service",
            "service_pid",
            "service_running",
            "supervisor_pid",
            "supervisor_running",
            "api_healthy",
            "api_error",
            "startup_update_disabled",
            "managed_startup_update_default",
            "whoami",
            "whoami_stdout",
            "whoami_stderr",
            "whoami_returncode",
            "whoami_error",
            "hive_status",
            "hive_connected",
            "peer_id",
            "peer_count",
            "connection_state",
            "connected_to_hive",
            "launch_profile",
            "resource_mode",
            "resource_mode_budget_percent",
            "loaded_models",
            "loading_model",
            "model_loading",
            "model_loading_progress_percent",
            "model_request_pins_startup",
            "model_selection_guidance",
            "health",
            "ready",
            "log_path",
            "log_tail",
            "status",
        ):
            if key in status_payload:
                payload[key] = status_payload[key]
        if not chat_payload.get("ok"):
            error = chat_payload.get("error") or "Hyperspace API request failed."
            if (
                "timed out" in str(error).lower()
                and status_payload.get("model_loading")
                and status_payload.get("loading_model")
            ):
                error = (
                    "Hyperspace inference is still warming up while loading "
                    f"{status_payload['loading_model']} "
                    f"({status_payload.get('model_loading_progress_percent', '?')}%)."
                )
            payload["error"] = error
        return json.dumps(payload)
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "action": action,
                "error": f"{type(exc).__name__}: {exc}",
                "metadata": _sidecar_metadata(),
            }
        )


HYPERSPACE_SIDECAR_SCHEMA = {
    "name": "hyperspace_sidecar",
    "description": (
        "Manage the named Modal L4 Hyperspace sidecar. Use action='start' to "
        "boot a durable sandbox, action='exec' to run commands inside it, "
        "action='status' to inspect whether it is still running, and "
        "action='stop' to tear it down. For a durable Hyperspace node, use "
        "action='start' with service='hyperspace' so Hermes launches it inside "
        "the reusable named sandbox through a detached Python supervisor. If "
        "called without an action or command, it returns sidecar metadata and "
        "current sandbox state. Hyperspace startup model selection remains "
        "automatic and depends on VRAM plus '--mode': chill=30%, balanced=50%, "
        "power=80%."
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
            "service": {
                "type": "string",
                "enum": sorted(s for s in VALID_SERVICES if s),
                "description": (
                    "Optional persistent service preset. Use service='hyperspace' "
                    "with action='start' to run a durable headless Hyperspace "
                    "node inside the reusable named sandbox."
                ),
            },
            "service_args": {
                "type": "string",
                "description": (
                    "Extra arguments appended to the service preset. For "
                    "service='hyperspace', these are appended after "
                    "'hyperspace start --headless --cuda'. Use '--profile' to "
                    "choose the coarse node role and '--mode chill|balanced|power' "
                    "to control the resource budget that influences startup "
                    "model selection."
                ),
            },
            "command": {
                "type": "string",
                "description": (
                    "Shell command to run. For action='exec', this runs inside "
                    "the existing sandbox. For action='start', this becomes the "
                    "sandbox entrypoint command; if omitted, Hermes starts a "
                    "keepalive sandbox you can reuse with later exec calls. "
                    "Long-lived services should prefer the 'service' parameter "
                    "instead of backgrounding through exec."
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
            "disable_startup_update": {
                "type": "boolean",
                "description": (
                    "When starting service='hyperspace', set the undocumented "
                    "HYPERSPACE_SKIP_STARTUP_UPDATE=1 guard so startup does not "
                    "self-update before the node comes up."
                ),
                "default": HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
            },
        },
        "required": [],
    },
}


HYPERSPACE_SCHEMA = {
    "name": "hyperspace",
    "description": (
        "High-level access to the durable Hyperspace node running inside the "
        "Modal sidecar. Use action='ensure' to start or reuse the node, "
        "action='status' to get normalized health and Hive connectivity "
        "signals, action='report' for verbose health details including the "
        "API health response, and action='chat' to send an OpenAI-compatible "
        "chat completion request through the local Hyperspace API. Managed "
        "launches disable startup self-update by default. Startup model choice "
        "is still automatic and depends on detected VRAM plus '--mode': "
        "chill=30%, balanced=50%, power=80%."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(VALID_HYPERSPACE_ACTIONS),
                "description": (
                    "High-level Hyperspace action. Defaults to 'status'."
                ),
            },
            "service_args": {
                "type": "string",
                "description": (
                    "Extra arguments appended after "
                    "'hyperspace start --headless --cuda' when Hermes ensures "
                    "the node is running. Use '--profile' for the coarse node "
                    "role and '--mode chill|balanced|power' to influence the "
                    "automatic startup model selection budget."
                ),
            },
            "messages": {
                "type": "array",
                "description": (
                    "OpenAI-compatible chat messages. Required for action='chat'."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "content": {},
                    },
                    "required": ["role", "content"],
                },
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional model name passed through to the Hyperspace "
                    "chat completions endpoint. This targets the chat request "
                    "only and does not pin startup model selection."
                ),
            },
            "temperature": {
                "type": "number",
                "description": "Optional sampling temperature for action='chat'.",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Optional max_tokens value for action='chat'.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "Timeout for API requests made through the sidecar."
                ),
                "default": DEFAULT_TIMEOUT_SECONDS,
            },
            "sandbox_timeout_seconds": {
                "type": "integer",
                "description": (
                    "Maximum lifetime for a sidecar sandbox Hermes creates "
                    "while ensuring Hyperspace is running."
                ),
                "default": DEFAULT_SANDBOX_TIMEOUT_SECONDS,
            },
            "disable_startup_update": {
                "type": "boolean",
                "description": (
                    "When Hermes has to start Hyperspace, set the undocumented "
                    "HYPERSPACE_SKIP_STARTUP_UPDATE=1 guard so startup is "
                    "repeatable."
                ),
                "default": HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
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
        service=args.get("service", ""),
        service_args=args.get("service_args", ""),
        command=args.get("command", ""),
        timeout_seconds=args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        sandbox_timeout_seconds=args.get(
            "sandbox_timeout_seconds",
            DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        ),
        bootstrap=args.get("bootstrap", True),
        disable_startup_update=args.get(
            "disable_startup_update",
            HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
        ),
    ),
    check_fn=check_hyperspace_sidecar_requirements,
    description=HYPERSPACE_SIDECAR_SCHEMA["description"],
)

registry.register(
    name="hyperspace",
    toolset="terminal",
    schema=HYPERSPACE_SCHEMA,
    handler=lambda args, **kw: hyperspace(
        action=args.get("action", ""),
        service_args=args.get("service_args", ""),
        messages=args.get("messages"),
        model=args.get("model", ""),
        temperature=args.get("temperature"),
        max_tokens=args.get("max_tokens"),
        timeout_seconds=args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        sandbox_timeout_seconds=args.get(
            "sandbox_timeout_seconds",
            DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        ),
        disable_startup_update=args.get(
            "disable_startup_update",
            HYPERSPACE_DISABLE_STARTUP_UPDATE_DEFAULT,
        ),
    ),
    check_fn=check_hyperspace_requirements,
    description=HYPERSPACE_SCHEMA["description"],
    emoji="🛰️",
)
