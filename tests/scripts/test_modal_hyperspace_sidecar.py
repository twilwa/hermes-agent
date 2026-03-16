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
