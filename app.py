import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from gmail_processor import GmailProcessor
from gmail_watch import GmailAccount, build_gmail_service, start_watch
try:
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:  # pragma: no cover
    HttpError = Exception  # fallback type alias
from supabase_state import BaseStateStore, MailboxState, get_state_store
from telegram_notify import send_telegram_message

try:
    import config  # type: ignore
except ImportError:  # pragma: no cover - optional configuration module
    config = None  # type: ignore

try:
    from keys import telegram_chat_id as keys_telegram_chat_id, telegram_token as keys_telegram_token  # type: ignore
except ImportError:  # pragma: no cover - optional keys module
    keys_telegram_chat_id = None  # type: ignore
    keys_telegram_token = None  # type: ignore


def _config_value(attr: str, env_name: str, default=None):
    if config and hasattr(config, attr):
        value = getattr(config, attr)
        if value not in (None, "", []):
            return value
    env_value = os.getenv(env_name)
    if env_value not in (None, ""):
        return env_value
    return default


def _configured_mailboxes() -> List[str]:
    if config and getattr(config, "GMAIL_ACCOUNTS", None):
        return [account.strip() for account in config.GMAIL_ACCOUNTS if account.strip()]  # type: ignore[attr-defined]
    raw = os.getenv("GMAIL_ACCOUNTS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _classification_prompt_path() -> Path:
    path_value = _config_value("CLASSIFICATION_PROMPT_PATH", "CLASSIFICATION_PROMPT_PATH", "classification_prompt.txt")
    path = Path(path_value)
    if not path.exists():
        raise RuntimeError(f"Classification prompt file not found at {path.resolve()}")
    return path


def _token_dir() -> Path:
    path_value = _config_value("GMAIL_OAUTH_TOKEN_DIR", "GMAIL_OAUTH_TOKEN_DIR", ".gmail_tokens")
    directory = Path(path_value)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _token_file_for(email: str) -> Path:
    token_dir = _token_dir()
    sanitized = email.replace("@", "_at_").replace(".", "_")
    return token_dir / f"token_{sanitized}.json"


def _telegram_value(config_attr: str, keys_value: Optional[str], env_name: str) -> Optional[str]:
    config_val = _config_value(config_attr, env_name)
    if config_val not in (None, ""):
        return config_val
    return keys_value or os.getenv(env_name)


def _true(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def gmail_service_factory(email: str):
    service_account_file = _config_value("GMAIL_SERVICE_ACCOUNT_FILE", "GMAIL_SERVICE_ACCOUNT_FILE")
    delegated_user = _config_value("GMAIL_DELEGATED_USER", "GMAIL_DELEGATED_USER", email)
    oauth_client_secret = _config_value("GMAIL_CLIENT_SECRET_PATH", "GMAIL_OAUTH_CLIENT_SECRET")

    if service_account_file:
        return build_gmail_service(
            service_account_file=service_account_file,
            delegated_user=delegated_user,
        )
    if not oauth_client_secret:
        raise RuntimeError(
            "Set GMAIL_SERVICE_ACCOUNT_FILE for domain-wide delegation or GMAIL_OAUTH_CLIENT_SECRET "
            "to use the installed app OAuth flow."
        )
    token_file = _token_file_for(email)
    allow_flow = _true(os.getenv("GMAIL_ALLOW_OAUTH_FLOW"))
    return build_gmail_service(
        oauth_client_secret=oauth_client_secret,
        oauth_token_file=str(token_file),
        allow_oauth_flow=allow_flow,
    )


telegram_token = _telegram_value("TELEGRAM_BOT_TOKEN", keys_telegram_token, "TELEGRAM_BOT_TOKEN")
telegram_chat_id = _telegram_value("TELEGRAM_CHAT_ID", keys_telegram_chat_id, "TELEGRAM_CHAT_ID")

state_store: BaseStateStore = get_state_store(
    url=_config_value("SUPABASE_URL", "SUPABASE_URL"),
    service_role_key=_config_value("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
)
processor = GmailProcessor(
    gmail_service_factory=gmail_service_factory,
    state_store=state_store,
    classification_prompt_path=_classification_prompt_path(),
    telegram_token=telegram_token,
    telegram_chat_id=telegram_chat_id,
)

app = FastAPI()


class DryRunPayload(BaseModel):
    sender: str
    to: str
    subject: str
    snippet: str
    date: Optional[str] = ""


class CleanupRequest(BaseModel):
    email: str
    batch_size: int = 50
    await_user_confirmation: bool = True
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


@app.post("/gmail/push")
async def gmail_push(request: Request):
    envelope = await request.json()
    if not isinstance(envelope, Dict):
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub envelope.")
    try:
        processor.handle_pubsub_envelope(envelope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok"}


@app.post("/gmail/watch")
async def gmail_watch():
    topic_name = _config_value("GMAIL_TOPIC_NAME", "GMAIL_TOPIC_NAME")
    if not topic_name:
        raise HTTPException(status_code=400, detail="GMAIL_TOPIC_NAME must be configured.")

    accounts = _configured_mailboxes()
    if not accounts:
        raise HTTPException(status_code=400, detail="Set GMAIL_ACCOUNTS to a comma-separated list of addresses.")

    results = []
    for email in accounts:
        try:
            service = gmail_service_factory(email)
            response = start_watch(
                service,
                GmailAccount(
                    user_id=email,
                    topic_name=topic_name,
                    label_ids=("INBOX",),
                ),
            )
            state_store.upsert_mailbox(
                MailboxState(
                    email=email,
                    history_id=response.get("historyId"),
                    watch_expiration=response.get("expiration"),
                )
            )
            results.append(
                {
                    "email": email,
                    "historyId": response.get("historyId"),
                    "expiration": response.get("expiration"),
                }
            )
        except HttpError as he:  # type: ignore
            content = getattr(he, "content", b"")
            try:
                detail = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
            except Exception:
                detail = str(he)
            raise HTTPException(status_code=500, detail=f"Gmail watch failed for {email}: {detail}")
        except Exception as exc:  # pragma: no cover - unexpected
            raise HTTPException(status_code=500, detail=f"Gmail watch failed for {email}: {exc}")
    return {"watches": results}


@app.post("/dry-run")
async def dry_run(payload: DryRunPayload):
    metadata = {
        "snippet": payload.snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": payload.sender},
                {"name": "To", "value": payload.to},
                {"name": "Subject", "value": payload.subject},
                {"name": "Date", "value": payload.date or ""},
            ]
        },
    }
    headers = processor._extract_headers(metadata)  # pylint: disable=protected-access
    decision = processor._classify_message(metadata, headers)  # pylint: disable=protected-access
    return {
        "action": decision.action,
        "summary": decision.summary,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "labels": list(decision.labels),
    }


@app.post("/gmail/cleanup")
async def gmail_cleanup(payload: CleanupRequest):
    try:
        result = processor.clear_inbox(
            payload.email,
            batch_size=payload.batch_size,
            await_user_confirmation=payload.await_user_confirmation,
            telegram_token=payload.telegram_token,
            telegram_chat_id=payload.telegram_chat_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@app.get("/healthz")
@app.get("/health")
async def healthz():
    accounts = _configured_mailboxes()
    status: List[Dict[str, Optional[str]]] = []
    for email in accounts:
        mailbox = state_store.get_mailbox(email)
        status.append(
            {
                "email": email,
                "history_id": mailbox.history_id if mailbox else None,
                "watch_expiration": str(mailbox.watch_expiration) if mailbox else None,
            }
        )
    return {
        "gmail_accounts": status,
        "telegram_configured": bool(telegram_token and telegram_chat_id),
        "supabase_mode": state_store.__class__.__name__,
    }


@app.post("/alerts/digest")
async def send_daily_digest():
    if not (telegram_token and telegram_chat_id):
        raise HTTPException(status_code=400, detail="Telegram is not configured.")

    queued = state_store.list_queued_alerts()
    if not queued:
        return {"sent": 0, "groups": []}

    # Group alerts by mailbox
    groups: Dict[str, List[Dict[str, str]]] = {}
    for item in queued:
        groups.setdefault(item["mailbox_email"], []).append(item)

    sent = 0
    details = []
    for mailbox, items in groups.items():
        # Compose a concise digest message
        header = f"Daily digest for {mailbox}:\n"
        body_lines = [f"- {it.get('summary','').strip()}" for it in items]
        message = header + "\n".join(body_lines)
        try:
            send_telegram_message(message, token=telegram_token, chat_id=telegram_chat_id, disable_notification=False)
            state_store.mark_alerts_sent(items)
            sent += 1
            details.append({"mailbox": mailbox, "items": len(items), "status": "sent"})
        except Exception as exc:  # pragma: no cover - external call
            details.append({"mailbox": mailbox, "items": len(items), "status": "error", "error": str(exc)})

    return {"groups": details, "group_count": len(details)}


# Simple cron-friendly endpoints that reuse existing handlers.
# These are intentionally unauthenticated per user preference.
@app.post("/cron/refresh")
async def cron_refresh():
    return await gmail_watch()


@app.post("/cron/digest")
async def cron_digest():
    return await send_daily_digest()
