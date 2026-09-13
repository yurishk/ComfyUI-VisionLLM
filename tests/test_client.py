from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from conftest import client


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def text(self):
        return json.dumps({"choices": [{"message": {"content": "ok"}}]})

    def release(self):
        return None

    async def wait_for_close(self):
        return None


class ErrorResponse(FakeResponse):
    status = 400

    async def text(self):
        return json.dumps({"error": {"message": "image payload is too large"}})


class GeminiResponse(FakeResponse):
    async def text(self):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "internal", "thought": True},
                                {"text": "visible answer"},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )


class WrappedErrorResponse(FakeResponse):
    async def text(self):
        return json.dumps({"error": {"message": "upstream model is temporarily unavailable"}})


class SafetyBlockedResponse(FakeResponse):
    async def text(self):
        return json.dumps(
            {
                "promptFeedback": {
                    "blockReason": "PROHIBITED_CONTENT",
                    "blockReasonMessage": "The image was blocked by safety filters.",
                }
            }
        )


class SlowResponse(FakeResponse):
    def __init__(self, state):
        self.state = state

    async def text(self):
        self.state["reading"] = True
        try:
            await asyncio.Event().wait()
        finally:
            self.state["cancelled"] = True


def run_chat():
    return asyncio.run(
        client.chat_completion(
            "https://example.test/v1",
            "key",
            "model",
            [{"role": "user", "content": "hello"}],
        )
    )


def test_direct_mode_passes_explicit_none_proxy(monkeypatch):
    captured = {}

    async def fake_request(_self, _method, _url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)
    result = run_chat()

    assert result["content"] == "ok"
    assert "proxy" in captured
    assert captured["proxy"] is None


def test_custom_proxy_is_passed_explicitly(monkeypatch):
    captured = {}

    async def fake_request(_self, _method, _url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)
    asyncio.run(
        client.chat_completion(
            "https://example.test/v1",
            "key",
            "model",
            [{"role": "user", "content": "hello"}],
            proxy_mode="custom",
            proxy_url="http://127.0.0.1:7897",
        )
    )

    assert captured["proxy"] == "http://127.0.0.1:7897"


def test_custom_proxy_requires_http_url():
    with pytest.raises(client.APIError, match="代理地址无效"):
        client._resolve_proxy("custom", "127.0.0.1:7897")


def test_api_error_includes_server_message(monkeypatch):
    async def fake_request(_self, _method, _url, **kwargs):
        return ErrorResponse()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)
    with pytest.raises(client.APIError, match="image payload is too large"):
        run_chat()


def test_gemini_native_response_is_supported(monkeypatch):
    async def fake_request(_self, _method, _url, **kwargs):
        return GeminiResponse()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)
    result = run_chat()

    assert result["content"] == "visible answer"
    assert result["reasoning"] == "internal"


def test_success_status_error_envelope_is_reported(monkeypatch):
    async def fake_request(_self, _method, _url, **kwargs):
        return WrappedErrorResponse()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)
    with pytest.raises(client.APIError, match="upstream model is temporarily unavailable"):
        run_chat()


def test_gemini_safety_block_is_reported(monkeypatch):
    async def fake_request(_self, _method, _url, **kwargs):
        return SafetyBlockedResponse()

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)
    with pytest.raises(client.APIError, match="PROHIBITED_CONTENT"):
        run_chat()


def test_chat_completion_cancels_response_read_when_interrupted(monkeypatch):
    state = {"reading": False, "cancelled": False, "checks": 0}

    async def fake_request(_self, _method, _url, **kwargs):
        return SlowResponse(state)

    def interrupted():
        state["checks"] += 1
        return state["checks"] >= 2

    monkeypatch.setattr(aiohttp.ClientSession, "_request", fake_request)

    with pytest.raises(client.RequestInterrupted):
        asyncio.run(
            client.chat_completion(
                "https://example.test/v1",
                "key",
                "model",
                [{"role": "user", "content": "hello"}],
                interrupt_check=interrupted,
                interrupt_poll_interval=0.01,
            )
        )

    assert state["reading"] is True
    assert state["cancelled"] is True
