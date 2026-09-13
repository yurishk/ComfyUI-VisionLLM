"""OpenAI-compatible HTTP client built on aiohttp.

No ``openai`` package dependency: we POST JSON to ``{base_url}/chat/completions``
and GET ``{base_url}/models``. Used both by the node at execution time and by the
settings "test connection" / "fetch models" routes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

DEFAULT_TIMEOUT = 300  # seconds; LLM generation can be slow


class APIError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class RequestInterrupted(BaseException):
    """Internal cancellation signal converted to ComfyUI's interrupt upstream."""


async def _await_interruptibly(
    awaitable: Awaitable[Any],
    interrupt_check: Callable[[], bool] | None,
    poll_interval: float,
) -> Any:
    """Await an operation while polling ComfyUI's process-wide interrupt flag."""
    task = asyncio.ensure_future(awaitable)
    if interrupt_check is None:
        return await task

    interval = max(0.01, float(poll_interval))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                return task.result()
            if interrupt_check():
                raise RequestInterrupted()
    except BaseException:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        raise


def _sanitize_error_text(value: Any, limit: int = 400) -> str:
    detail = re.sub(r"\s+", " ", str(value or "")).strip()
    detail = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer ***", detail)
    detail = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-***", detail)
    return detail[:limit]


def _response_error_detail(text: str) -> str:
    """Extract a concise, display-safe reason from an API error response."""
    detail: Any = ""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or error.get("detail") or error.get("code")
            elif error:
                detail = error
            detail = detail or data.get("message") or data.get("detail")
    except (json.JSONDecodeError, TypeError):
        detail = text

    return _sanitize_error_text(detail)


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = []
        for part in value:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif isinstance(part, str):
                texts.append(part)
        return "".join(texts)
    return ""


def _parse_completion_response(data: Any) -> tuple[str, str]:
    """Accept OpenAI chat-completion and Gemini native response envelopes."""
    if not isinstance(data, dict):
        raise APIError(
            "接口响应格式异常: 顶层内容不是对象",
            body=_sanitize_error_text(data),
        )

    error_detail = _response_error_detail(json.dumps(data, ensure_ascii=False))
    if error_detail:
        raise APIError(f"接口返回错误信息: {error_detail}", body=error_detail)

    prompt_feedback = data.get("promptFeedback") or data.get("prompt_feedback")
    if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
        reason = _sanitize_error_text(prompt_feedback.get("blockReason"))
        explanation = _sanitize_error_text(prompt_feedback.get("blockReasonMessage"))
        detail = f"{reason}: {explanation}" if explanation else reason
        raise APIError(f"图像或提示词被模型安全策略拦截: {detail}", body=detail)

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = _content_text(message.get("content"))
            reasoning = _content_text(
                message.get("reasoning_content") or message.get("reasoning")
            )
            return content, reasoning

    candidates = data.get("candidates")
    if isinstance(candidates, list) and candidates:
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        content_obj = candidate.get("content") if isinstance(candidate, dict) else None
        parts = content_obj.get("parts") if isinstance(content_obj, dict) else None
        visible: list[str] = []
        reasoning: list[str] = []
        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                continue
            (reasoning if part.get("thought") else visible).append(part["text"])
        if visible or reasoning:
            return "".join(visible), "".join(reasoning)
        finish_reason = _sanitize_error_text(candidate.get("finishReason"))
        if finish_reason and finish_reason not in {"STOP", "MAX_TOKENS"}:
            raise APIError(
                f"模型没有返回文本，结束原因: {finish_reason}",
                body=finish_reason,
            )

    if isinstance(data.get("output_text"), str):
        return data["output_text"], ""

    excerpt = _sanitize_error_text(json.dumps(data, ensure_ascii=False), limit=500)
    raise APIError(
        f"接口返回成功状态，但没有可读取的文本: {excerpt}",
        body=excerpt,
    )


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _join_url(base_url: str, path: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise APIError("base_url 为空，请在 API 设置中填写接口地址。")
    return f"{base}{path}"


def _resolve_proxy(proxy_mode: str = "direct", proxy_url: str = "") -> str | None:
    """Resolve a profile's proxy without allowing global aiohttp patches to decide."""
    mode = (proxy_mode or "direct").strip().lower()
    if mode == "direct":
        return None
    if mode == "system":
        return (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or None
        )
    if mode != "custom":
        raise APIError(f"未知代理模式: {proxy_mode}")

    proxy = (proxy_url or "").strip()
    parsed = urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise APIError("自定义代理地址无效，请填写 http://127.0.0.1:端口。")
    return proxy


def _network_hint(proxy_mode: str, proxy: str | None) -> str:
    if proxy:
        return f"（代理: {proxy}）"
    if (proxy_mode or "direct").strip().lower() == "system":
        return "（系统代理未设置，已直连）"
    return "（直连）"


async def chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    seed: int | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    proxy_mode: str = "direct",
    proxy_url: str = "",
    interrupt_check: Callable[[], bool] | None = None,
    interrupt_poll_interval: float = 0.25,
) -> dict[str, str]:
    """Call the chat completions endpoint.

    Returns ``{"content": str, "reasoning": str, "raw": dict}``. ``reasoning`` is
    populated from ``reasoning_content`` / ``reasoning`` fields when the server
    returns them (DeepSeek-style thinking models).
    """
    import aiohttp

    payload: dict[str, Any] = {"model": model, "messages": messages}
    if seed is not None:
        payload["seed"] = int(seed)
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    url = _join_url(base_url, "/chat/completions")
    proxy = _resolve_proxy(proxy_mode, proxy_url)
    timeout_config = aiohttp.ClientTimeout(total=timeout, connect=min(30, timeout))

    async def request_once() -> Any:
        async with aiohttp.ClientSession(timeout=timeout_config) as sess:
            # Always pass proxy, including None. This prevents another
            # extension from silently injecting a process-wide proxy.
            async with sess.post(
                url,
                json=payload,
                headers=_headers(api_key),
                proxy=proxy,
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    detail = _response_error_detail(text)
                    message = f"接口返回错误 {resp.status}"
                    if detail:
                        message += f": {detail}"
                    raise APIError(
                        message,
                        status=resp.status,
                        body=detail,
                    )
                return json.loads(text)

    try:
        for attempt in range(2):
            try:
                data = await _await_interruptibly(
                    request_once(),
                    interrupt_check,
                    interrupt_poll_interval,
                )
                break
            except aiohttp.ClientConnectorError:
                if attempt == 0:
                    await _await_interruptibly(
                        asyncio.sleep(0.75),
                        interrupt_check,
                        interrupt_poll_interval,
                    )
                    continue
                raise
    except APIError:
        raise
    except aiohttp.ServerDisconnectedError as exc:
        raise APIError(
            "服务端在生成完成前断开连接。模型列表测试成功不代表长时间生成可用；"
            "请限制 max_tokens、缩短输入，或检查 API 网关的请求超时。"
        ) from exc
    except aiohttp.ClientProxyConnectionError as exc:
        raise APIError(f"无法连接代理 {_network_hint(proxy_mode, proxy)}: {exc}") from exc
    except aiohttp.ClientConnectorError as exc:
        raise APIError(f"无法连接 API {_network_hint(proxy_mode, proxy)}: {exc}") from exc
    except asyncio.TimeoutError as exc:
        raise APIError(
            f"请求超过 {timeout:g} 秒仍未完成 {_network_hint(proxy_mode, proxy)}。"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise APIError(f"请求失败: {exc}") from exc

    content, reasoning = _parse_completion_response(data)
    return {"content": content, "reasoning": reasoning, "raw": data}


async def list_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = 30,
    proxy_mode: str = "direct",
    proxy_url: str = "",
) -> list[str]:
    import aiohttp

    url = _join_url(base_url, "/models")
    proxy = _resolve_proxy(proxy_mode, proxy_url)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout, connect=min(15, timeout))
        ) as sess:
            async with sess.get(url, headers=_headers(api_key), proxy=proxy) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    detail = _response_error_detail(text)
                    message = f"接口返回错误 {resp.status}"
                    if detail:
                        message += f": {detail}"
                    raise APIError(message, status=resp.status, body=detail)
                data = json.loads(text)
    except APIError:
        raise
    except aiohttp.ClientProxyConnectionError as exc:
        raise APIError(f"无法连接代理 {_network_hint(proxy_mode, proxy)}: {exc}") from exc
    except aiohttp.ClientConnectorError as exc:
        raise APIError(f"无法连接 API {_network_hint(proxy_mode, proxy)}: {exc}") from exc
    except asyncio.TimeoutError as exc:
        raise APIError(f"连接测试超时 {_network_hint(proxy_mode, proxy)}。") from exc
    except Exception as exc:  # noqa: BLE001
        raise APIError(f"请求失败: {exc}") from exc

    models: list[str] = []
    for item in data.get("data") or []:
        mid = item.get("id") if isinstance(item, dict) else None
        if mid:
            models.append(str(mid))
    # some servers return a bare list
    if not models and isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                models.append(str(item["id"]))
            elif isinstance(item, str):
                models.append(item)
    return models
