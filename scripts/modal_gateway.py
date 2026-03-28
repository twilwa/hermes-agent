# ABOUTME: Deploy the Hermes gateway to Modal as a single warm web endpoint with a status dashboard.
# ABOUTME: Packages the repo, injects the local Hermes config as deploy-time secrets, and keeps Discord online in one hosted container.

from __future__ import annotations

import base64
import os
from pathlib import Path

from gateway.modal_runtime import named_modal_secret_names

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    import modal
except ModuleNotFoundError as import_error:
    FastAPI = Request = HTMLResponse = JSONResponse = None
    modal = None
    _RUNTIME_IMPORT_ERROR = import_error
else:
    _RUNTIME_IMPORT_ERROR = None

LOCAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_HERMES_HOME = Path(os.getenv("HERMES_MODAL_SOURCE_HOME", Path.home() / ".hermes"))

REMOTE_PROJECT_ROOT = "/opt/hermes/hermes-agent"
REMOTE_STATE_ROOT = "/hermes-state"
REMOTE_HERMES_HOME = f"{REMOTE_STATE_ROOT}/home"

APP_NAME = os.getenv("HERMES_MODAL_APP_NAME", "hermes-gateway")
VOLUME_NAME = os.getenv("HERMES_MODAL_VOLUME_NAME", f"{APP_NAME}-state")
VOICE_RUNTIME_APT_PACKAGES = ("ffmpeg", "libopus0")


def _read_optional_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _build_runtime_secret_env() -> dict[str, str]:
    preloaded = {
        key: os.getenv(key, "").strip()
        for key in ("HERMES_MODAL_CONFIG_B64", "HERMES_MODAL_ENV_B64", "HERMES_MODAL_AUTH_B64")
        if os.getenv(key, "").strip()
    }
    if preloaded:
        return preloaded

    payload: dict[str, str] = {}
    candidates = {
        "HERMES_MODAL_CONFIG_B64": LOCAL_HERMES_HOME / "config.yaml",
        "HERMES_MODAL_ENV_B64": LOCAL_HERMES_HOME / ".env",
        "HERMES_MODAL_AUTH_B64": LOCAL_HERMES_HOME / "auth.json",
    }
    for env_name, path in candidates.items():
        encoded = _read_optional_file(path)
        if encoded:
            payload[env_name] = encoded
    return payload


def _raise_runtime_import_error() -> None:
    if _RUNTIME_IMPORT_ERROR is None:
        return
    raise ModuleNotFoundError(
        "scripts.modal_gateway requires the optional 'modal' and 'fastapi' dependencies"
    ) from _RUNTIME_IMPORT_ERROR


if modal is not None:
    runtime_secret_env = _build_runtime_secret_env()
    runtime_secret = modal.Secret.from_dict(runtime_secret_env)
    named_secrets = [runtime_secret]
    for secret_name in named_modal_secret_names():
        named_secrets.append(modal.Secret.from_name(secret_name))
    state_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

    image = (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install(*VOICE_RUNTIME_APT_PACKAGES)
        .pip_install_from_pyproject(
            str(LOCAL_PROJECT_ROOT / "pyproject.toml"),
            optional_dependencies=["messaging"],
        )
        .uv_pip_install("fastapi>=0.115,<1")
        .add_local_dir(
            LOCAL_PROJECT_ROOT,
            REMOTE_PROJECT_ROOT,
            ignore=[
                ".git",
                ".pytest_cache",
                ".ruff_cache",
                ".venv",
                "__pycache__",
                "*.pyc",
                "*.pyo",
            ],
        )
    )

    app = modal.App(APP_NAME)

    @app.function(
        image=image,
        volumes={REMOTE_STATE_ROOT: state_volume},
        secrets=named_secrets,
        env={
            "PYTHONPATH": REMOTE_PROJECT_ROOT,
            "HERMES_MODAL_PROJECT_ROOT": REMOTE_PROJECT_ROOT,
        },
        min_containers=1,
        max_containers=1,
        scaledown_window=900,
        startup_timeout=300,
    )
    @modal.concurrent(max_inputs=100)
    @modal.asgi_app(label="dashboard")
    def gateway_dashboard():
        import asyncio

        from gateway.modal_runtime import ModalGatewayService, render_dashboard_html

        service = ModalGatewayService(
            hermes_home=Path(REMOTE_HERMES_HOME),
            project_root=REMOTE_PROJECT_ROOT,
            commit_fn=state_volume.commit,
        )

        web_app = FastAPI(title="Hermes Gateway Dashboard")

        @web_app.on_event("startup")
        async def _startup() -> None:
            service.start()
            await asyncio.to_thread(service.wait_until_ready, 45)

        @web_app.get("/health")
        async def health() -> JSONResponse:
            snapshot = service.snapshot()
            runtime_status = snapshot.get("runtime_status") or {}
            ok = runtime_status.get("gateway_state") == "running"
            return JSONResponse(
                {
                    "ok": ok,
                    "gateway_state": runtime_status.get("gateway_state"),
                    "platforms": runtime_status.get("platforms", {}),
                    "last_error": snapshot.get("last_error"),
                },
                status_code=200 if ok else 503,
            )

        @web_app.get("/status")
        async def status() -> JSONResponse:
            return JSONResponse(service.snapshot())

        @web_app.get("/", response_class=HTMLResponse)
        async def dashboard(request: Request) -> HTMLResponse:
            snapshot = service.snapshot()
            return HTMLResponse(render_dashboard_html(snapshot, request_url=str(request.url)))

        return web_app
else:
    runtime_secret_env = {}
    named_secrets = []
    state_volume = None
    image = None
    app = None

    def gateway_dashboard():
        _raise_runtime_import_error()
