"""Hugging Face text-to-video integration (optional dependency).

This module is intentionally import-safe even when `huggingface_hub` is not
installed. The import happens only when you call `text_to_video(...)`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HfVideoRequest:
    prompt: str
    model: str
    provider: str = "fal-ai"


def text_to_video(*, prompt: str, model: str, hf_token: str, provider: str = "fal-ai"):
    """Generate a video from text using Hugging Face Inference providers.

    Returns whatever the underlying client returns (often a URL or an object
    containing a URL, depending on provider/model).
    """
    try:
        from huggingface_hub import InferenceClient  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing optional dependency `huggingface_hub`. "
            "Install it to enable text-to-video."
        ) from e

    client = InferenceClient(provider=provider, api_key=hf_token)
    return client.text_to_video(prompt, model=model)

