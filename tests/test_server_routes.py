from __future__ import annotations

from conftest import PACKAGE_NAME, PLUGIN_ROOT, _load_module, config_store


def test_inline_test_keeps_saved_key_and_edited_network(monkeypatch):
    routes = _load_module(f"{PACKAGE_NAME}.server_routes", PLUGIN_ROOT / "server_routes.py")
    saved = {
        "base_url": "https://saved.test/v1",
        "api_key": "saved-key",
        "proxy_mode": "system",
        "proxy_url": "http://saved-proxy:7897",
    }
    monkeypatch.setattr(config_store, "load_config", lambda: {})
    monkeypatch.setattr(config_store, "resolve_profile", lambda _cfg, _selector: saved)

    result = routes._resolve_credentials(
        {
            "profile": "existing",
            "base_url": "https://edited.test/v1",
            "proxy_mode": "direct",
            "proxy_url": "",
        }
    )

    assert result == ("https://edited.test/v1", "saved-key", "direct", "")
