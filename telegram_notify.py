import os
import time
from typing import Iterable, Optional

import requests

try:
    from keys import telegram_token as DEFAULT_TOKEN  # type: ignore
    from keys import telegram_chat_id as DEFAULT_CHAT_ID  # type: ignore
except ImportError:  # pragma: no cover - keys.py is project-specific
    DEFAULT_TOKEN = None  # type: ignore
    DEFAULT_CHAT_ID = None  # type: ignore


TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_TIMEOUT = 10


def _resolve(value: Optional[str], *, env_var: str, default: Optional[str]) -> str:
    if value:
        return value
    env_value = os.getenv(env_var)
    if env_value:
        return env_value
    if default:
        return default
    raise ValueError(f"{env_var} must be provided via argument, environment variable, or keys.py")


def send_telegram_message(
    text: str,
    *,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    disable_notification: bool = False,
    reply_markup: Optional[dict] = None,
) -> dict:
    """
    Send a text message to a Telegram chat using the Bot API.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Message text must be a non-empty string.")

    resolved_token = _resolve(token, env_var="TELEGRAM_BOT_TOKEN", default=DEFAULT_TOKEN)
    resolved_chat_id = _resolve(chat_id, env_var="TELEGRAM_CHAT_ID", default=DEFAULT_CHAT_ID)

    url = TELEGRAM_API_BASE.format(token=resolved_token, method="sendMessage")
    payload: dict = {
        "chat_id": resolved_chat_id,
        "text": text,
        "disable_notification": disable_notification,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to send Telegram message: {exc}") from exc

    data = response.json()
    if not data.get("ok"):
        description = data.get("description", "Unknown error")
        raise RuntimeError(f"Telegram API returned an error: {description}")
    return data


def _build_url(token: str, method: str) -> str:
    if not token:
        raise ValueError("Telegram token is required.")
    return TELEGRAM_API_BASE.format(token=token, method=method)


def get_telegram_updates(
    *,
    token: Optional[str] = None,
    offset: Optional[int] = None,
    timeout: int = 0,
) -> dict:
    resolved_token = _resolve(token, env_var="TELEGRAM_BOT_TOKEN", default=DEFAULT_TOKEN)
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset

    url = _build_url(resolved_token, "getUpdates")
    try:
        response = requests.get(url, params=params, timeout=timeout or DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch Telegram updates: {exc}") from exc
    data = response.json()
    if not data.get("ok"):
        description = data.get("description", "Unknown error")
        raise RuntimeError(f"Telegram API returned an error: {description}")
    return data


def answer_callback_query(
    *,
    callback_query_id: str,
    token: Optional[str] = None,
    text: Optional[str] = None,
    show_alert: bool = False,
) -> None:
    if not callback_query_id:
        raise ValueError("callback_query_id is required.")
    resolved_token = _resolve(token, env_var="TELEGRAM_BOT_TOKEN", default=DEFAULT_TOKEN)
    payload = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert,
    }
    if text:
        payload["text"] = text

    url = _build_url(resolved_token, "answerCallbackQuery")
    try:
        response = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to answer Telegram callback query: {exc}") from exc
    data = response.json()
    if not data.get("ok"):
        description = data.get("description", "Unknown error")
        raise RuntimeError(f"Telegram API returned an error: {description}")


def wait_for_callback_selection(
    expected_callback_data: Iterable[str],
    *,
    token: Optional[str] = None,
    timeout: int = 300,
    poll_interval: float = 2.0,
) -> Optional[str]:
    expected = {item for item in expected_callback_data if item}
    if not expected:
        return None

    resolved_token = _resolve(token, env_var="TELEGRAM_BOT_TOKEN", default=DEFAULT_TOKEN)

    initial = get_telegram_updates(token=resolved_token, timeout=0)
    offset = None
    initial_results = initial.get("result", [])
    if initial_results:
        offset = initial_results[-1]["update_id"] + 1

    deadline = time.time() + max(timeout, 0)
    while time.time() < deadline:
        remaining = int(deadline - time.time())
        updates = get_telegram_updates(
            token=resolved_token,
            offset=offset,
            timeout=min(max(remaining, 0), 30),
        )
        results = updates.get("result", [])
        for item in results:
            offset = item["update_id"] + 1
            callback_query = item.get("callback_query")
            if not callback_query:
                continue
            data = callback_query.get("data")
            if data in expected:
                callback_id = callback_query.get("id")
                if callback_id:
                    try:
                        answer_callback_query(callback_query_id=callback_id, token=resolved_token)  # best-effort
                    except RuntimeError:
                        pass
                return data
        if not results:
            time.sleep(poll_interval)
    return None
