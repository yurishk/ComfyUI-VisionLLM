from __future__ import annotations

import pytest


def _profile(name="OpenAI", base_url="https://api.openai.com/v1", api_key="sk-secret123", models=None, pid=None, proxy_mode="direct", proxy_url=""):
    return {
        "id": pid or "p1",
        "name": name,
        "base_url": base_url,
        "api_key": api_key,
        "proxy_mode": proxy_mode,
        "proxy_url": proxy_url,
        "models": models if models is not None else ["gpt-4o"],
    }


def test_empty_config_returns_no_profiles_and_no_active(isolated_config):
    cfg = isolated_config.get_config_masked()
    assert cfg["profiles"] == []
    assert cfg["active"] is None


def test_saved_config_masks_key_and_keeps_active(isolated_config):
    saved = isolated_config.save_config_from_frontend({
        "active": "p1",
        "profiles": [_profile()],
    })
    prof = saved["profiles"][0]
    assert prof["api_key"] == ""  # plaintext never returned
    assert prof["api_key_masked"].endswith("t123")
    assert "secret" not in prof["api_key_masked"]
    assert prof["has_key"] is True
    assert saved["active"] == "p1"


def test_partial_edit_without_retyping_key_preserves_it(isolated_config):
    isolated_config.save_config_from_frontend({
        "active": "p1",
        "profiles": [_profile(api_key="sk-secret123")],
    })
    masked = isolated_config.get_config_masked()["profiles"][0]["api_key_masked"]
    # send back the masked placeholder + a new model list, no fresh key
    isolated_config.save_config_from_frontend({
        "active": "p1",
        "profiles": [_profile(api_key=masked, models=["gpt-4o", "gpt-4o-mini"])],
    })
    full = isolated_config.load_config()
    assert full["profiles"][0]["api_key"] == "sk-secret123"
    assert full["profiles"][0]["models"] == ["gpt-4o", "gpt-4o-mini"]


def test_retyping_key_replaces_it(isolated_config):
    isolated_config.save_config_from_frontend({"active": "p1", "profiles": [_profile(api_key="sk-old")]})
    isolated_config.save_config_from_frontend({"active": "p1", "profiles": [_profile(api_key="sk-new")]})
    full = isolated_config.load_config()
    assert full["profiles"][0]["api_key"] == "sk-new"


def test_profile_persists_explicit_proxy_settings(isolated_config):
    isolated_config.save_config_from_frontend({
        "active": "p1",
        "profiles": [_profile(proxy_mode="custom", proxy_url="http://127.0.0.1:7897")],
    })
    profile = isolated_config.load_config()["profiles"][0]
    assert profile["proxy_mode"] == "custom"
    assert profile["proxy_url"] == "http://127.0.0.1:7897"


def test_resolve_profile_auto_uses_active_then_first(isolated_config):
    isolated_config.save_config_from_frontend({
        "active": "p2",
        "profiles": [_profile(name="A", pid="p1"), _profile(name="B", pid="p2", models=["m"])],
    })
    cfg = isolated_config.load_config()
    assert isolated_config.resolve_profile(cfg, "auto")["id"] == "p2"
    assert isolated_config.resolve_profile(cfg, "A")["id"] == "p1"
    # missing selector falls back to active/first so shared workflows still run
    assert isolated_config.resolve_profile(cfg, "does-not-exist")["id"] == "p2"


def test_resolve_profile_raises_when_none_configured(isolated_config):
    with pytest.raises(RuntimeError, match="档案"):
        isolated_config.resolve_profile({"profiles": []}, "auto")


def test_delete_profile_reassigns_active(isolated_config):
    isolated_config.save_config_from_frontend({
        "active": "p1",
        "profiles": [_profile(name="A", pid="p1"), _profile(name="B", pid="p2", models=["m"])],
    })
    assert isolated_config.delete_profile("p1") is True
    full = isolated_config.load_config()
    assert [p["id"] for p in full["profiles"]] == ["p2"]
    assert full["active"] == "p2"


def test_set_active_only_accepts_existing(isolated_config):
    isolated_config.save_config_from_frontend({"active": "p1", "profiles": [_profile(pid="p1")]})
    assert isolated_config.set_active("p1") is True
    assert isolated_config.set_active("nope") is False


def test_is_changed_is_deterministic_and_input_sensitive(node_module):
    base = dict(text_prompt="a", model="m", seed=1)
    h1 = node_module.VisionLLM.IS_CHANGED(**base)
    h2 = node_module.VisionLLM.IS_CHANGED(**base)
    h3 = node_module.VisionLLM.IS_CHANGED(text_prompt="b", model="m", seed=1)
    assert h1 == h2
    assert h1 != h3


def test_reasoning_split_extracts_tagged_block(node_module):
    sample = "before " + node_module.REASONING_OPEN + "secret" + node_module.REASONING_CLOSE + " after"
    text, reasoning = node_module._split_reasoning(sample, node_module.REASONING_OPEN, node_module.REASONING_CLOSE)
    assert "before" in text and "after" in text
    assert "secret" in reasoning
    assert node_module.REASONING_OPEN not in text


def test_image_encode_handles_batch(node_module):
    import numpy as np

    arr = (np.random.rand(2, 8, 8, 3) * 255).astype("float32") / 255.0
    urls = node_module._encode_images(arr)
    assert len(urls) == 2
    assert all(u.startswith("data:image/png;base64,") for u in urls)
