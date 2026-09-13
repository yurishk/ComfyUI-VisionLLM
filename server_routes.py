"""HTTP routes for the VisionLLM frontend settings dialog.

All routes are prefixed with ``/visionllm/``. The chat call itself happens inside
the node at execution time; these routes only manage configuration, test
connections, and list models.
"""

from __future__ import annotations

import json
import logging

from . import client, config_store

logger = logging.getLogger(__name__)

ROUTE_PREFIX = "/visionllm"
_REGISTERED_FLAG = "_visionllm_routes_registered"


def _resolve_credentials(data: dict) -> tuple[str, str, str, str]:
    """Merge edited fields with the selected profile's saved credentials."""
    selector = data.get("profile") or data.get("id") or data.get("name") or "auto"
    profile = {}
    try:
        profile = config_store.resolve_profile(config_store.load_config(), selector)
    except Exception:
        if not data.get("base_url"):
            raise

    return (
        data.get("base_url") or profile.get("base_url", ""),
        data.get("api_key") or profile.get("api_key", ""),
        data.get("proxy_mode") or profile.get("proxy_mode", "direct"),
        data.get("proxy_url") if "proxy_url" in data else profile.get("proxy_url", ""),
    )


def register_routes() -> None:
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:  # pragma: no cover - ComfyUI not available in unit tests
        return

    instance = getattr(PromptServer, "instance", None)
    if instance is None or not hasattr(instance, "routes"):
        return
    if getattr(instance, _REGISTERED_FLAG, False):
        return

    routes = instance.routes

    async def read_object(request):  # noqa: ANN001
        try:
            data = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(
                text=json.dumps({"ok": False, "error": "请求不是有效的 JSON"}, ensure_ascii=False),
                content_type="application/json",
            ) from exc
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(
                text=json.dumps({"ok": False, "error": "请求内容必须是对象"}, ensure_ascii=False),
                content_type="application/json",
            )
        return data

    def failure(message: str, status: int):
        return web.json_response({"ok": False, "error": message}, status=status)

    @routes.get(f"{ROUTE_PREFIX}/config")
    async def get_config(request):  # noqa: ANN001
        try:
            return web.json_response({"ok": True, "data": config_store.get_config_masked()})
        except Exception as exc:  # noqa: BLE001
            logger.exception("visionllm: get_config failed")
            return failure(str(exc), 500)

    @routes.post(f"{ROUTE_PREFIX}/config")
    async def save_config(request):  # noqa: ANN001
        data = await read_object(request)
        try:
            return web.json_response({"ok": True, "data": config_store.save_config_from_frontend(data)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("visionllm: save_config failed")
            return failure(str(exc), 500)

    @routes.post(f"{ROUTE_PREFIX}/profile")
    async def upsert_profile_route(request):  # noqa: ANN001
        data = await read_object(request)
        try:
            return web.json_response({"ok": True, "data": config_store.upsert_profile(data)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("visionllm: upsert_profile failed")
            return failure(str(exc), 500)

    @routes.post(f"{ROUTE_PREFIX}/profile/delete")
    async def delete_profile_route(request):  # noqa: ANN001
        data = await read_object(request)
        if not config_store.delete_profile(data.get("id", "")):
            return failure("档案不存在", 404)
        return web.json_response({"ok": True, "data": config_store.get_config_masked()})

    @routes.post(f"{ROUTE_PREFIX}/active")
    async def set_active_route(request):  # noqa: ANN001
        data = await read_object(request)
        if not config_store.set_active(data.get("id", "")):
            return failure("档案不存在", 404)
        return web.json_response({"ok": True, "data": config_store.get_config_masked()})

    @routes.post(f"{ROUTE_PREFIX}/test")
    async def test_connection(request):  # noqa: ANN001
        data = await read_object(request)
        base_url, api_key, proxy_mode, proxy_url = _resolve_credentials(data)
        try:
            models = await client.list_models(
                base_url,
                api_key,
                timeout=30,
                proxy_mode=proxy_mode,
                proxy_url=proxy_url,
            )
            return web.json_response({"ok": True, "models": models})
        except client.APIError as exc:
            return web.json_response({"ok": False, "error": str(exc), "models": []}, status=502)
        except Exception as exc:  # noqa: BLE001
            logger.exception("visionllm: test failed")
            return failure(str(exc), 502)

    @routes.get(f"{ROUTE_PREFIX}/models")
    async def list_models_route(request):  # noqa: ANN001
        cfg = config_store.load_config()
        try:
            prof = config_store.resolve_profile(cfg, request.rel_url.query.get("profile") or "auto")
        except Exception as exc:  # noqa: BLE001
            return failure(str(exc), 400)
        try:
            models = await client.list_models(
                prof.get("base_url", ""),
                prof.get("api_key", ""),
                timeout=30,
                proxy_mode=prof.get("proxy_mode", "direct"),
                proxy_url=prof.get("proxy_url", ""),
            )
            return web.json_response({"ok": True, "models": models})
        except client.APIError as exc:
            return web.json_response({"ok": False, "error": str(exc), "models": []}, status=502)
        except Exception as exc:  # noqa: BLE001
            logger.exception("visionllm: list models failed")
            return failure(str(exc), 502)

    setattr(instance, _REGISTERED_FLAG, True)
