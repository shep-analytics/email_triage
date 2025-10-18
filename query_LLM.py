import os
from typing import Optional

import requests

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5"
DEFAULT_TIMEOUT = 60

try:
    from keys import OPENROUTER_API_Key  # type: ignore
except ImportError:  # pragma: no cover - keys.py is project-specific
    OPENROUTER_API_Key = None  # type: ignore


def _resolve_api_key(explicit_key: Optional[str]) -> str:
    if explicit_key:
        return explicit_key

    if OPENROUTER_API_Key:  # type: ignore
        return OPENROUTER_API_Key  # type: ignore

    env_key = os.getenv("OPENROUTER_API_KEY")
    if env_key:
        return env_key

    raise ValueError(
        "Provide an OpenRouter API key via function argument, keys.OPENROUTER_API_Key, "
        "or the OPENROUTER_API_KEY environment variable."
    )


def query_llm(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    Submit a single-turn prompt to OpenRouter and return the raw model response text.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")

    resolved_key = _resolve_api_key(api_key)

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to reach OpenRouter: {exc}") from exc

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected response format from OpenRouter: {exc}") from exc
