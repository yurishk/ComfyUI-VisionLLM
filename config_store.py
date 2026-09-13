"""Server-side storage for API profiles.

API keys live here (in ``config/api_settings.json``, which is git-ignored) and
never become node widgets, so they are never serialized into a workflow. The
frontend only ever sees a *masked* key; when the user does not retype the key
while editing other fields, the existing key is preserved.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid

_VERSION = 2
_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.join(_HERE, "config")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "api_settings.json")
_LOCK = threading.RLock()


def _gen_id() -> str:
    return f"profile_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _default_config() -> dict:
    return {"version": _VERSION, "active": None, "profiles": []}


def _ensure_loaded() -> dict:
    if not os.path.isdir(_CONFIG_DIR):
        os.makedirs(_CONFIG_DIR, exist_ok=True)
    if not os.path.isfile(_CONFIG_FILE):
        cfg = _default_config()
        _write(cfg)
        return cfg
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        cfg = _default_config()
        _write(cfg)
        return cfg
    cfg.setdefault("version", _VERSION)
    cfg.setdefault("active", None)
    cfg.setdefault("profiles", [])
    return cfg


def _write(cfg: dict) -> None:
    if not os.path.isdir(_CONFIG_DIR):
        os.makedirs(_CONFIG_DIR, exist_ok=True)
    tmp = _CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _CONFIG_FILE)


def _mask(key: str) -> str:
    key = key or ""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:3]}••••{key[-4:]}"


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def load_config() -> dict:
    with _LOCK:
        return copy.deepcopy(_ensure_loaded())


def resolve_profile(cfg: dict, selector) -> dict:
    """Resolve a profile from ``cfg`` given a selector (id, name, or "auto")."""
    profiles = cfg.get("profiles") or []
    if not profiles:
        raise RuntimeError("尚未配置任何 API 档案，请先在设置中添加。")
    selector = (selector or "auto").strip() if isinstance(selector, str) else selector
    if selector in (None, "", "auto"):
        active = cfg.get("active")
        if active:
            for p in profiles:
                if p.get("id") == active:
                    return p
        return profiles[0]
    for p in profiles:
        if p.get("id") == selector or p.get("name") == selector:
            return p
    # not found -> fall back to active (then first) so a shared workflow still runs
    active = cfg.get("active")
    if active:
        for p in profiles:
            if p.get("id") == active:
                return p
    return profiles[0]


def get_profile_for_node(selector) -> dict:
    with _LOCK:
        cfg = _ensure_loaded()
        prof = resolve_profile(cfg, selector)
        return copy.deepcopy(prof)


def get_config_masked() -> dict:
    with _LOCK:
        cfg = _ensure_loaded()
        out = copy.deepcopy(cfg)
        for p in out.get("profiles", []):
            key = p.get("api_key", "")
            p["api_key_masked"] = _mask(key)
            p["has_key"] = bool(key)
            p["api_key"] = ""
        return out


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


def save_config_from_frontend(incoming: dict) -> dict:
    """Save profiles from the frontend, preserving keys that were not retyped.

    Each incoming profile may carry ``api_key`` equal to the masked placeholder
    (or empty) meaning "keep the existing key". A genuinely new value replaces it.
    """
    with _LOCK:
        cfg = _ensure_loaded()
        existing = {p.get("id"): p for p in cfg.get("profiles", [])}
        new_profiles: list[dict] = []
        for item in incoming.get("profiles") or []:
            pid = item.get("id") or _gen_id()
            old = existing.get(pid)
            new_key = (item.get("api_key") or "").strip()
            if not new_key or new_key == _mask(old.get("api_key", "") if old else ""):
                # keep existing key
                key = (old.get("api_key", "") if old else "")
            else:
                key = new_key
            profile = {
                "id": pid,
                "name": (item.get("name") or "").strip() or "未命名",
                "base_url": (item.get("base_url") or "").strip(),
                "api_key": key,
                "proxy_mode": (item.get("proxy_mode") or "direct").strip(),
                "proxy_url": (item.get("proxy_url") or "").strip(),
                "models": [str(m) for m in (item.get("models") or []) if str(m).strip()],
            }
            new_profiles.append(profile)
            existing.pop(pid, None)

        cfg["profiles"] = new_profiles
        active = incoming.get("active")
        ids = {p["id"] for p in new_profiles}
        if active in ids:
            cfg["active"] = active
        elif new_profiles:
            cfg["active"] = new_profiles[0]["id"]
        else:
            cfg["active"] = None
        _write(cfg)
        return get_config_masked()


def upsert_profile(data: dict) -> dict:
    """Create or update a single profile (admin route convenience)."""
    with _LOCK:
        cfg = _ensure_loaded()
        profiles = cfg.setdefault("profiles", [])
        pid = data.get("id")
        if pid:
            for p in profiles:
                if p.get("id") == pid:
                    p["name"] = (data.get("name") or p.get("name") or "未命名").strip()
                    p["base_url"] = (data.get("base_url") or p.get("base_url", "")).strip()
                    if "proxy_mode" in data:
                        p["proxy_mode"] = (data.get("proxy_mode") or "direct").strip()
                    if "proxy_url" in data:
                        p["proxy_url"] = (data.get("proxy_url") or "").strip()
                    if "api_key" in data and data["api_key"]:
                        p["api_key"] = data["api_key"].strip()
                    if "models" in data:
                        p["models"] = [str(m) for m in data["models"] if str(m).strip()]
                    _write(cfg)
                    return get_config_masked()
        pid = _gen_id()
        profiles.append(
            {
                "id": pid,
                "name": (data.get("name") or "未命名").strip(),
                "base_url": (data.get("base_url") or "").strip(),
                "api_key": (data.get("api_key") or "").strip(),
                "proxy_mode": (data.get("proxy_mode") or "direct").strip(),
                "proxy_url": (data.get("proxy_url") or "").strip(),
                "models": [str(m) for m in (data.get("models") or []) if str(m).strip()],
            }
        )
        if not cfg.get("active"):
            cfg["active"] = pid
        _write(cfg)
        return get_config_masked()


def delete_profile(pid: str) -> bool:
    with _LOCK:
        cfg = _ensure_loaded()
        before = len(cfg.get("profiles", []))
        cfg["profiles"] = [p for p in cfg.get("profiles", []) if p.get("id") != pid]
        if len(cfg["profiles"]) == before:
            return False
        if cfg.get("active") == pid:
            cfg["active"] = cfg["profiles"][0]["id"] if cfg["profiles"] else None
        _write(cfg)
        return True


def set_active(pid: str) -> bool:
    with _LOCK:
        cfg = _ensure_loaded()
        if not any(p.get("id") == pid for p in cfg.get("profiles", [])):
            return False
        cfg["active"] = pid
        _write(cfg)
        return True
