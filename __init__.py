"""Vision LLM for ComfyUI.

A single node that sends an image + text prompt to an OpenAI-compatible vision
LLM and returns text. API credentials live in a server-side, git-ignored config
file and are managed through a settings dialog — they never become node widgets.
"""

import logging

logger = logging.getLogger(__name__)

if __package__:
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
else:  # Allows tools such as pytest to inspect a hyphenated plugin directory.
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./web"

# Register API routes when loaded by a running ComfyUI server.
if __package__:
    try:
        from .server_routes import register_routes

        register_routes()
    except Exception:  # pragma: no cover
        logger.exception("VisionLLM backend route registration failed")

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
