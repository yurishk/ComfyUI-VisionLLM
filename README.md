# Vision LLM for ComfyUI

A single ComfyUI node that sends an **image + text prompt** to an
**OpenAI-compatible vision LLM** and returns the generated text (and reasoning).

## Why this node

Unlike typical OpenAI nodes, **API keys never live in the node**. They are stored
in a server-side, git-ignored config file and managed through a settings dialog.
This means:

- Sharing a workflow never leaks your API key.
- The key/base URL is not serialized into the workflow JSON.

## Features

- One node, no clutter. Inputs: `image` (optional) + `text_prompt`.
- Vision by default: normal images are sent as lossless base64 PNG. Images over
  2048 px on either edge, 6 megapixels, or 8 MiB as PNG are automatically
  resized when needed and encoded as quality-90 JPEG to avoid gateway limits.
- System prompt, optional prepend prompt, temperature / max_tokens / seed.
- Reasoning extraction (DeepSeek-style `reasoning_content`, or custom tags).
- Multiple profiles (proxy + key + model list), per-node profile selection.
- Connection tester + model list fetch in the settings dialog.
- ComfyUI's standard interrupt action cancels an in-flight API request and
  releases the HTTP connection instead of waiting for the request timeout.

## Quick start

1. Drop the folder into `custom_nodes/`, restart ComfyUI.
2. Add the **Vision LLM** node (`llm/vision`).
3. Click ⚙ **API Settings**, add a profile (base URL incl. `/v1`, API key, models),
   set it active and test the connection.
4. Pick the profile + model in the node, connect an image and a text prompt, and
   run.

> The OpenAI-compatible endpoint is called directly from the ComfyUI server using
> `aiohttp` (no `openai` package dependency).

> Interrupting stops the local request immediately. A third-party provider may
> still finish or bill work that it already accepted before the connection closed.
