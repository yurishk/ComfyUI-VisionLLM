"""VisionLLM ComfyUI node.

A single node that sends an image (optional) + text prompt to an
OpenAI-compatible vision LLM and returns the generated text plus reasoning.

Credentials (base URL + API key) are read from the server-side config store —
they are **never** node widgets, so a shared workflow cannot leak them.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import re

from . import client, config_store

CATEGORY = "llm/vision"
NODE_NAME = "VisionLLM"

AUTO_IMAGE_MAX_EDGE = 2048
AUTO_IMAGE_MAX_PIXELS = 6_000_000
AUTO_IMAGE_MAX_PNG_BYTES = 8 * 1024 * 1024
AUTO_IMAGE_JPEG_QUALITY = 90

# DeepSeek-style reasoning tags. Built via chr() so the literal tags are not
# stripped by tooling that treats them as HTML.
REASONING_OPEN = chr(60) + "think" + chr(62)
REASONING_CLOSE = chr(60) + "/" + "think" + chr(62)


def _to_numpy(image):
    """Best-effort conversion of a ComfyUI IMAGE tensor to a numpy array."""
    try:
        if hasattr(image, "cpu"):
            return image.cpu().numpy()
    except Exception:  # noqa: BLE001
        pass
    try:
        import numpy as np  # noqa: F401
        return image
    except Exception:  # noqa: BLE001
        return image


def _encode_images(image) -> list[str]:
    """Encode images losslessly unless their dimensions or payload are excessive."""
    import numpy as np  # local import keeps module import light
    from PIL import Image  # noqa: F401

    arr = _to_numpy(image)
    if arr is None:
        return []
    arr = np.asarray(arr)
    if arr.ndim == 3:  # (H, W, C) -> single image
        arr = arr[None, ...]  # add batch dim
    if arr.ndim != 4:
        return []
    urls: list[str] = []
    for frame in arr:
        frame = np.clip(255.0 * frame, 0, 255).astype(np.uint8)
        pil = Image.fromarray(frame)
        if pil.mode == "RGBA":
            pil = pil.convert("RGB")

        width, height = pil.size
        pixels = width * height
        dimensions_are_large = (
            max(width, height) > AUTO_IMAGE_MAX_EDGE or pixels > AUTO_IMAGE_MAX_PIXELS
        )
        png_data = b""
        if not dimensions_are_large:
            png_buf = io.BytesIO()
            pil.save(png_buf, format="PNG")
            png_data = png_buf.getvalue()
        is_large = dimensions_are_large or len(png_data) > AUTO_IMAGE_MAX_PNG_BYTES

        if not is_large:
            mime = "image/png"
            encoded = png_data
        else:
            scale = min(
                1.0,
                AUTO_IMAGE_MAX_EDGE / max(width, height),
                math.sqrt(AUTO_IMAGE_MAX_PIXELS / pixels),
            )
            if scale < 1.0:
                target = (max(1, round(width * scale)), max(1, round(height * scale)))
                pil = pil.resize(target, Image.Resampling.LANCZOS)
            if pil.mode != "RGB":
                pil = pil.convert("RGB")

            jpeg_buf = io.BytesIO()
            pil.save(
                jpeg_buf,
                format="JPEG",
                quality=AUTO_IMAGE_JPEG_QUALITY,
                optimize=True,
            )
            encoded = jpeg_buf.getvalue()
            mime = "image/jpeg"
            source_size = (
                f"PNG {len(png_data) / 1024 / 1024:.1f} MiB"
                if png_data
                else f"原始像素约 {pixels * 3 / 1024 / 1024:.1f} MiB"
            )
            print(
                "[VisionLLM] 大图自动优化: "
                f"{width}x{height} -> {pil.width}x{pil.height}, "
                f"{source_size} -> JPEG {len(encoded) / 1024 / 1024:.1f} MiB"
            )

        b64 = base64.b64encode(encoded).decode("ascii")
        urls.append(f"data:{mime};base64,{b64}")
    return urls


def _split_reasoning(text: str, tag_open: str, tag_close: str) -> tuple[str, str]:
    """Split reasoning blocks enclosed by ``tag_open``/``tag_close`` out of text."""
    if not tag_open or not tag_close:
        return text.strip(), ""
    start = re.escape(tag_open)
    end = re.escape(tag_close)
    blocks = re.findall(f"{start}(.*?){end}", text, flags=re.DOTALL)
    reasoning = "\n".join(b.strip() for b in blocks if b.strip())
    cleaned = re.sub(f"{start}.*?{end}", "", text, flags=re.DOTALL)
    return cleaned.strip(), reasoning


class VisionLLM:
    """Call an OpenAI-compatible vision LLM with an image + text prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "dynamicPrompts": True,
                        "default": "",
                        "tooltip": "发送给大模型的用户提示词。",
                    },
                ),
                "model": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "tooltip": "模型名称，可在 API 设置中为每个档案预置候选列表。",
                    },
                ),
                "system_prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "系统提示词（可选）。"},
                ),
                "pre_prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "拼接到用户提示词之前的内容（可选）。"},
                ),
                "temperature": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "temperature_enabled": ("BOOLEAN", {"default": False, "label_on": "启用", "label_off": "自动"}),
                "max_tokens": ("INT", {"default": 1024, "min": 1, "max": 1048576, "step": 1}),
                "max_tokens_enabled": ("BOOLEAN", {"default": False, "label_on": "启用", "label_off": "自动"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2**32 - 1, "control_after_generate": True}),
                "strip_reasoning": ("BOOLEAN", {"default": True, "label_on": "剥离", "label_off": "保留"}),
                "reasoning_tag_open": ("STRING", {"multiline": False, "default": REASONING_OPEN}),
                "reasoning_tag_close": ("STRING", {"multiline": False, "default": REASONING_CLOSE}),
                "image_detail": (["auto", "low", "high"], {"default": "auto"}),
                "sleep": ("INT", {"default": 0, "min": 0, "max": 86400, "tooltip": "调用后等待秒数（本地同机部署时有用）。"}),
                "profile": (
                    "STRING",
                    {"multiline": False, "default": "auto", "tooltip": "使用哪个 API 档案；auto 表示当前活动档案。"},
                ),
            },
            "optional": {
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "reasoning")
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    DESCRIPTION = "Send an image + text prompt to an OpenAI-compatible vision LLM and return text."
    OUTPUT_TOOLTIPS = ("大模型回复的文本内容", "推理内容（若有）")

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        parts = [
            kwargs.get("text_prompt", ""),
            kwargs.get("system_prompt", ""),
            kwargs.get("pre_prompt", ""),
            kwargs.get("model", ""),
            kwargs.get("profile", ""),
            kwargs.get("seed", ""),
            f"{kwargs.get('temperature_enabled')}{kwargs.get('temperature')}",
            f"{kwargs.get('max_tokens_enabled')}{kwargs.get('max_tokens')}",
            f"{kwargs.get('strip_reasoning')}{kwargs.get('reasoning_tag_open')}{kwargs.get('reasoning_tag_close')}",
            kwargs.get("image_detail", ""),
            kwargs.get("sleep", ""),
        ]
        digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()
        return f"vision:{digest}"

    async def generate(
        self,
        text_prompt: str,
        model: str,
        system_prompt: str,
        pre_prompt: str,
        temperature: float,
        temperature_enabled: bool,
        max_tokens: int,
        max_tokens_enabled: bool,
        seed: int,
        strip_reasoning: bool,
        reasoning_tag_open: str,
        reasoning_tag_close: str,
        image_detail: str,
        sleep: int,
        profile: str = "auto",
        image=None,
    ):
        import comfy.model_management as model_management

        model_management.throw_exception_if_processing_interrupted()
        profile_obj = config_store.get_profile_for_node(profile)
        base_url = profile_obj.get("base_url", "")
        api_key = profile_obj.get("api_key", "")
        proxy_mode = profile_obj.get("proxy_mode", "direct")
        proxy_url = profile_obj.get("proxy_url", "")
        model = (model or "").strip() or (profile_obj.get("models") or [""])[0]
        if not model:
            raise ValueError("未指定模型名称，请在节点中选择或输入模型。")

        # Build messages (vision array format works for both text-only and image)
        messages: list[dict] = []
        sys_text = (system_prompt or "").strip()
        if sys_text:
            messages.append({"role": "system", "content": [{"type": "text", "text": sys_text}]})

        user_text = (text_prompt or "").strip()
        pre = (pre_prompt or "").strip()
        if pre:
            user_text = f"{pre}\n{user_text}" if user_text else pre

        content: list[dict] = [{"type": "text", "text": user_text}]
        if image is not None:
            for url in _encode_images(image):
                content.append({"type": "image_url", "image_url": {"url": url, "detail": image_detail}})
        messages.append({"role": "user", "content": content})

        model_management.throw_exception_if_processing_interrupted()
        try:
            result = await client.chat_completion(
                base_url,
                api_key,
                model,
                messages,
                seed=seed,
                temperature=temperature if temperature_enabled else None,
                max_tokens=max_tokens if max_tokens_enabled else None,
                proxy_mode=proxy_mode,
                proxy_url=proxy_url,
                interrupt_check=model_management.processing_interrupted,
            )
        except client.RequestInterrupted:
            model_management.throw_exception_if_processing_interrupted()
            raise model_management.InterruptProcessingException()
        text = result.get("content", "")
        reasoning = result.get("reasoning", "")

        if strip_reasoning:
            text_only, tagged = _split_reasoning(text, reasoning_tag_open, reasoning_tag_close)
            if tagged:
                reasoning = (reasoning + "\n" + tagged).strip() if reasoning else tagged
            text = text_only
        else:
            text = text.strip()

        if sleep and sleep > 0:
            remaining = float(int(sleep))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + remaining
            while remaining > 0:
                model_management.throw_exception_if_processing_interrupted()
                await asyncio.sleep(min(0.25, remaining))
                remaining = deadline - loop.time()

        return (text, reasoning)


NODE_CLASS_MAPPINGS = {
    NODE_NAME: VisionLLM,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    NODE_NAME: "Vision LLM",
}
