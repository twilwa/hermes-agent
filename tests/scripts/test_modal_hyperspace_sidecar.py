import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "modal_hyperspace_sidecar.py"
    spec = importlib.util.spec_from_file_location("modal_hyperspace_sidecar", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sidecar_env_uses_persistent_home_and_linux_path():
    module = _load_module()

    env = module._sidecar_env()

    assert env["HOME"] == module.HOME_DIR
    assert env["XDG_CONFIG_HOME"] == module.CONFIG_DIR
    assert env["XDG_DATA_HOME"] == module.DATA_DIR
    assert env["XDG_CACHE_HOME"] == module.CACHE_DIR
    assert env["PATH"] == f"{module.HOME_DIR}/.local/bin:{module.LINUX_PATH}"


def test_sidecar_command_metadata_uses_modal_cli_paths():
    module = _load_module()

    metadata = module._sidecar_metadata()

    assert metadata["app"] == module.APP_NAME
    assert metadata["gpu"] == "L4"
    assert metadata["home"] == module.HOME_DIR
    assert metadata["volume"] == module.VOLUME_NAME
    assert metadata["bootstrap"] == f"python -m modal run {module.SCRIPT_PATH}"
    assert metadata["shell"] == f"python -m modal shell {module.SCRIPT_PATH}::hyperspace_sidecar --cmd /bin/bash"


def test_sidecar_runtime_image_matches_hyperspace_binary_requirements():
    module = _load_module()

    assert module.BASE_IMAGE_TAG == "python:3.11-slim-bookworm"
    assert {"libgomp1", "libssl3", "libstdc++6", "lsof"}.issubset(
        set(module.SIDECAR_APT_PACKAGES)
    )


def test_execute_hyperspace_command_runs_in_sidecar_environment(monkeypatch):
    module = _load_module()
    captured = {}

    class _CompletedProcess:
        returncode = 0
        stdout = "gpu ready\n"
        stderr = ""

    monkeypatch.setattr(
        module,
        "_ensure_sidecar_directories",
        lambda: captured.setdefault("bootstrapped", True),
    )
    monkeypatch.setattr(
        module.state_volume,
        "commit",
        lambda: captured.setdefault("committed", True),
    )

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _CompletedProcess()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._execute_hyperspace_command(
        command="nvidia-smi",
        timeout_seconds=42,
        bootstrap=True,
    )

    assert result["success"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "gpu ready\n"
    assert captured["bootstrapped"] is True
    assert captured["committed"] is True
    assert captured["args"] == ["bash", "-lc", "nvidia-smi"]
    assert captured["kwargs"]["timeout"] == 42
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["env"]["HOME"] == module.HOME_DIR


def test_execute_hyperspace_command_surfaces_timeout(monkeypatch):
    module = _load_module()
    captured = {}

    monkeypatch.setattr(
        module.state_volume,
        "commit",
        lambda: captured.setdefault("committed", True),
    )

    def fake_run(args, **kwargs):
        raise module.subprocess.TimeoutExpired(
            cmd=args,
            timeout=kwargs["timeout"],
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._execute_hyperspace_command(
        command="sleep 999",
        timeout_seconds=5,
        bootstrap=False,
    )

    assert result["success"] is False
    assert result["returncode"] == 124
    assert result["timed_out"] is True
    assert result["stdout"] == "partial stdout"
    assert result["stderr"] == "partial stderr"
    assert captured["committed"] is True
