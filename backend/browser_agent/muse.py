"""Browser-agent model client. OpenRouter, OpenAI-compatible chat completions."""

from __future__ import annotations

import logging
from typing import Any

from config import settings

log = logging.getLogger(__name__)

_client: Any = None
_images_supported: bool | None = None  # learned on first image call


def client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI

        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        _client = OpenAI(base_url=settings.openrouter_api_base, api_key=settings.openrouter_api_key)
    return _client


def _strip_images(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = [p for p in content if p.get("type") != "image_url"]
        out.append({**m, "content": content})
    return out


def _has_images(messages: list[dict]) -> bool:
    return any(
        isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"])
        for m in messages
    )


def images_supported() -> bool | None:
    return _images_supported


def complete(messages: list[dict], max_tokens: int | None = None, temperature: float = 0.0) -> str:
    """One chat completion. Falls back to text-only once if the API rejects image content."""
    global _images_supported
    max_tokens = max_tokens or settings.muse_max_tokens
    # reasoning_effort is a Muse Spark parameter. Claude Haiku on OpenRouter rejects it.
    kw = {}
    if settings.muse_reasoning_effort and settings.muse_model.startswith("muse"):
        kw = {"reasoning_effort": settings.muse_reasoning_effort}
    if _images_supported is False and _has_images(messages):
        messages = _strip_images(messages)
    try:
        resp = client().chat.completions.create(
            model=settings.muse_model, messages=messages, max_tokens=max_tokens, temperature=temperature, **kw
        )
    except Exception as e:  # noqa: BLE001
        if _has_images(messages) and _images_supported is not False:
            log.warning("model rejected a message with images (%s); retrying text-only", str(e)[:120])
            _images_supported = False
            resp = client().chat.completions.create(
                model=settings.muse_model, messages=_strip_images(messages), max_tokens=max_tokens, temperature=temperature, **kw
            )
        else:
            raise
    else:
        if _has_images(messages) and _images_supported is None:
            _images_supported = True
    return (resp.choices[0].message.content or "").strip()
