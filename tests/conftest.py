from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "vision_llm_under_test"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# Make the hyphenated plugin directory importable as a package so the relative
# imports in nodes.py / server_routes.py resolve under pytest.
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PLUGIN_ROOT)]
sys.modules[PACKAGE_NAME] = package
config_store = _load_module(f"{PACKAGE_NAME}.config_store", PLUGIN_ROOT / "config_store.py")
client = _load_module(f"{PACKAGE_NAME}.client", PLUGIN_ROOT / "client.py")
nodes = _load_module(f"{PACKAGE_NAME}.nodes", PLUGIN_ROOT / "nodes.py")


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_file = cfg_dir / "api_settings.json"
    monkeypatch.setattr(config_store, "_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(config_store, "_CONFIG_FILE", str(cfg_file))
    # start from a clean default
    config_store._write(config_store._default_config())
    return config_store


@pytest.fixture()
def node_module():
    return nodes
