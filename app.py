from __future__ import annotations

import os
from pathlib import Path
import asyncio
import uuid
import json
from typing import Any, Dict, List, Optional, Tuple
import base64
import email.utils as email_utils

from fastapi import Depends, FastAPI, HTTPException, Request, Body
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from gmail_processor import CleanupCategory, GmailProcessor
from gmail_watch import GmailAccount, build_gmail_service, start_watch
try:
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:  # pragma: no cover
    HttpError = Exception  # fallback type alias
from prompt_manager import PromptManager
from supabase_state import BaseStateStore, MailboxState, get_state_store
from telegram_notify import send_telegram_message

try:
    import config  # type: ignore
except ImportError:  # pragma: no cover - optional configuration module
    config = None  # type: ignore

try:
    from keys import telegram_chat_id as keys_telegram_chat_id, telegram_token as keys_telegram_token  # type: ignore
    from keys import SUPABASE_URL as keys_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY as keys_SUPABASE_SERVICE_ROLE_KEY  # type: ignore
    try:
        from keys import GOOGLE_OAUTH_CLIENT_ID as keys_GOOGLE_OAUTH_CLIENT_ID  # type: ignore
    except Exception:  # pragma: no cover
        keys_GOOGLE_OAUTH_CLIENT_ID = None  # type: ignore
except ImportError:  # pragma: no cover - optional keys module
    keys_telegram_chat_id = None  # type: ignore
    keys_telegram_token = None  # type: ignore
    keys_SUPABASE_URL = None  # type: ignore
    keys_SUPABASE_SERVICE_ROLE_KEY = None  # type: ignore
    keys_GOOGLE_OAUTH_CLIENT_ID = None  # type: ignore


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


def _allowed_login_emails() -> List[str]:
    if config and getattr(config, "ALLOWED_LOGIN_EMAILS", None):
        return [addr.strip().lower() for addr in config.ALLOWED_LOGIN_EMAILS if addr.strip()]  # type: ignore[attr-defined]
    raw = os.getenv("ALLOWED_LOGIN_EMAILS", "")
    items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if items:
        return items
    fallback = [acct.lower() for acct in _configured_mailboxes()]
    if fallback:
        return fallback
    return ["alexsheppert@gmail.com"]


def _cleanup_action_description(category: CleanupCategory, label: Optional[str]) -> str:
    if category == "spam":
        return "delete them as spam."
    if category == "receipt":
        return "treat them as receipts and archive them."
    if category == "useful_archive":
        label_name = label or "Filed"
        return f"archive them with the '{label_name}' label."
    if category == "requires_response":
        return "leave them in the inbox under the 'Requiring Response' label."
    if category == "should_read":
        return "leave them in the inbox under the 'User Should Read' label."
    return "apply the specified cleanup action."


def _build_criterion_text(
    *,
    subject: str,
    sender: str,
    category: CleanupCategory,
    label: Optional[str],
    comment: str,
) -> str:
    subject_text = subject.strip() or "(no subject)"
    sender_text = sender.strip() or "unknown sender"
    reason = comment.strip().replace("\n", " ")
    action_sentence = _cleanup_action_description(category, label)
    base = f"For emails similar to '{subject_text}' from {sender_text}, {action_sentence}"
    if reason:
        if not reason.endswith("."):
            reason += "."
        return f"{base} Reason: {reason}"
    return base


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
# Global kill-switch for Telegram (useful to stop message floods quickly)
if str(os.getenv("DISABLE_TELEGRAM", "")).strip().lower() in {"1", "true", "yes", "on"}:
    telegram_token = None
    telegram_chat_id = None

state_store: BaseStateStore = get_state_store(
    url=_config_value("SUPABASE_URL", "SUPABASE_URL") or keys_SUPABASE_URL,
    service_role_key=_config_value("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY") or keys_SUPABASE_SERVICE_ROLE_KEY,
)
classification_prompt_path = _classification_prompt_path()
prompt_manager = PromptManager(classification_prompt_path)
google_client_id = _config_value("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_ID") or keys_GOOGLE_OAUTH_CLIENT_ID
allowed_login_emails = {email.lower() for email in _allowed_login_emails()}
auth_scheme = HTTPBearer(auto_error=False)
_google_request_session = google_auth_requests.Request()
processor = GmailProcessor(
    gmail_service_factory=gmail_service_factory,
    state_store=state_store,
    classification_prompt_path=classification_prompt_path,
    prompt_manager=prompt_manager,
    telegram_token=telegram_token,
    telegram_chat_id=telegram_chat_id,
)

app = FastAPI()
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _authenticate(credentials: Optional[HTTPAuthorizationCredentials]) -> Dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if not google_client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CLIENT_ID is not configured.")
    token = credentials.credentials
    try:
        id_info = id_token.verify_oauth2_token(token, _google_request_session, google_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid ID token: {exc}") from exc
    email = str(id_info.get("email", "")).lower()
    if email not in allowed_login_emails:
        raise HTTPException(status_code=403, detail="Email not authorized.")
    return {"email": email, "claims": id_info}


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme)) -> Dict[str, Any]:
    return _authenticate(credentials)


# -----------------------------
# Helpers for message parsing/sending
# -----------------------------

def _extract_headers_from_metadata(metadata: Dict[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    try:
        for header in metadata.get("payload", {}).get("headers", []):
            name = header.get("name")
            value = header.get("value")
            if name and value:
                headers[name.lower()] = value
    except Exception:
        pass
    return headers


def _decode_b64url(data: str) -> bytes:
    s = data.strip()
    # Pad base64 string if necessary
    padding = 4 - (len(s) % 4)
    if padding and padding < 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def _extract_bodies(payload: Dict[str, Any]) -> Tuple[str, str]:
    text_parts: List[str] = []
    html_parts: List[str] = []

    def visit(part: Dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data and isinstance(data, str):
            try:
                decoded = _decode_b64url(data).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
        else:
            decoded = ""
        if mime_type.startswith("text/plain") and decoded:
            text_parts.append(decoded)
        elif mime_type.startswith("text/html") and decoded:
            html_parts.append(decoded)
        for child in part.get("parts", []) or []:
            visit(child)

    if payload:
        # Top-level may contain data directly
        visit(payload)
        if not text_parts and not html_parts:
            data = payload.get("body", {}).get("data")
            if data:
                try:
                    text_parts.append(_decode_b64url(data).decode("utf-8", errors="replace"))
                except Exception:
                    pass
    return ("\n".join(text_parts).strip(), "\n".join(html_parts).strip())


# ---------------------------------------------------------------------------
# Request/response models (Pydantic)
# Define these before route declarations so FastAPI correctly treats them
# as request bodies instead of query params.
# ---------------------------------------------------------------------------

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


class CleanupRunRequest(BaseModel):
    mailbox_email: Optional[str] = None
    batch_size: int = 50


class FeedbackRequest(BaseModel):
    mailbox_email: Optional[str] = None
    gmail_id: str
    desired_category: CleanupCategory
    label: Optional[str] = None
    comment: str = Field(default="", max_length=500)


class CriterionPayload(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class CriterionUpdatePayload(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    enabled: Optional[bool] = None


# -----------------------------
# Message viewer + actions models
# -----------------------------

class ReplyPayload(BaseModel):
    mailbox_email: Optional[str] = None
    body_text: str = Field(min_length=1)
    to: Optional[str] = None  # overrides default reply target
    subject: Optional[str] = None  # overrides auto Re: subject


class MailboxPayload(BaseModel):
    mailbox_email: Optional[str] = None


@app.get("/")
async def serve_root():
    if not static_dir.exists():
        raise HTTPException(status_code=404, detail="Web UI not available.")
    return FileResponse(static_dir / "index.html")


@app.get("/api/config")
async def api_config():
    return {
        "google_client_id": google_client_id,
        "allowed_emails": sorted(allowed_login_emails),
        "criteria_count": len(prompt_manager.list_criteria()),
    }


@app.post("/api/cleanup/run")
async def api_cleanup_run(payload: CleanupRunRequest = Body(...), user=Depends(get_current_user)):
    batch_size = payload.batch_size or 50
    if batch_size <= 0 or batch_size > 500:
        raise HTTPException(status_code=400, detail="batch_size must be between 1 and 500.")
    mailbox = (payload.mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    # UI should run exactly one batch and avoid Telegram notifications
    result = processor.clear_inbox(
        mailbox,
        batch_size=batch_size,
        await_user_confirmation=False,
        notify_via_telegram=False,
        stop_after_one_batch=True,
    )
    return result


# -----------------------------
# Live cleanup (SSE + cancel)
# -----------------------------

class CleanupJob:
    def __init__(self, job_id: str, owner_email: str) -> None:
        self.id = job_id
        self.owner = owner_email
        self.queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self.cancel_event = asyncio.Event()
        self.done = asyncio.Event()
        self.result: Optional[dict] = None
        self.error: Optional[str] = None


_jobs: Dict[str, CleanupJob] = {}


def _sse_format(data: dict, event: Optional[str] = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    if event:
        return f"event: {event}\n" f"data: {payload}\n\n"
    return f"data: {payload}\n\n"


async def _enqueue(queue: asyncio.Queue, item: dict) -> None:
    try:
        await queue.put(item)
    except Exception:
        pass


@app.post("/api/cleanup/start")
async def api_cleanup_start(payload: CleanupRunRequest = Body(...), user=Depends(get_current_user)):
    batch_size = payload.batch_size or 50
    if batch_size <= 0 or batch_size > 500:
        raise HTTPException(status_code=400, detail="batch_size must be between 1 and 500.")
    mailbox = (payload.mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")

    job_id = uuid.uuid4().hex
    job = CleanupJob(job_id, owner_email=user["email"])
    _jobs[job_id] = job

    loop = asyncio.get_running_loop()

    def progress_cb(event: dict) -> None:
        try:
            loop.call_soon_threadsafe(lambda: job.queue.put_nowait(event))
        except Exception:
            pass

    def is_cancelled() -> bool:
        return job.cancel_event.is_set()

    async def runner() -> None:
        await _enqueue(job.queue, {"type": "connected", "job_id": job_id})
        try:
            # UI runs a single batch by default; Telegram off
            result = await asyncio.to_thread(
                processor.clear_inbox,
                mailbox,
                batch_size=batch_size,
                await_user_confirmation=False,
                notify_via_telegram=False,
                stop_after_one_batch=True,
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
            )
            job.result = result
            await _enqueue(job.queue, {"type": "complete", "result": result})
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            await _enqueue(job.queue, {"type": "error", "error": job.error})
        finally:
            await _enqueue(job.queue, {"type": "end"})
            job.done.set()

    asyncio.create_task(runner())
    return {"job_id": job_id}


@app.get("/api/cleanup/events/{job_id}")
async def api_cleanup_events(job_id: str, token: Optional[str] = None):
    # EventSource cannot set Authorization header; allow token as query param
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        id_info = id_token.verify_oauth2_token(token, _google_request_session, google_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid ID token: {exc}") from exc
    email = str(id_info.get("email", "")).lower()
    job = _jobs.get(job_id)
    if job is None or job.owner != email:
        raise HTTPException(status_code=404, detail="Job not found.")

    async def event_generator():
        # Initial connect event
        yield _sse_format({"type": "ok", "job_id": job_id})
        while True:
            try:
                item = await asyncio.wait_for(job.queue.get(), timeout=15)
                yield _sse_format(item)
                if item.get("type") == "end":
                    break
            except asyncio.TimeoutError:
                # Keep-alive ping
                yield "event: ping\n" "data: {}\n\n"

        # Cleanup completed; drop from registry
        try:
            _jobs.pop(job_id, None)
        except Exception:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class CancelPayload(BaseModel):
    job_id: str


@app.post("/api/cleanup/cancel")
async def api_cleanup_cancel(payload: CancelPayload = Body(...), user=Depends(get_current_user)):
    job = _jobs.get(payload.job_id)
    if not job or job.owner != user["email"]:
        raise HTTPException(status_code=404, detail="Job not found.")
    job.cancel_event.set()
    return {"status": "cancelling"}


@app.post("/api/cleanup/feedback")
async def api_cleanup_feedback(payload: FeedbackRequest = Body(...), user=Depends(get_current_user)):
    mailbox = (payload.mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    comment = payload.comment.strip()
    try:
        override_result = processor.apply_manual_cleanup_decision(
            email_address=mailbox,
            gmail_id=payload.gmail_id,
            category=payload.desired_category,
            label=payload.label,
        )
    except Exception as exc:  # noqa: BLE001 - bubble as HTTP error
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    headers = override_result.get("headers", {})
    subject = str(headers.get("subject", "(no subject)"))
    sender = str(headers.get("from", ""))
    criterion_text = _build_criterion_text(
        subject=subject,
        sender=sender,
        category=payload.desired_category,
        label=override_result.get("label") or payload.label,
        comment=comment,
    )
    metadata = {
        "gmail_id": payload.gmail_id,
        "mailbox_email": mailbox,
        "category": payload.desired_category,
        "label": override_result.get("label") or payload.label,
        "comment": comment,
    }
    criterion = prompt_manager.add_criterion(criterion_text, metadata=metadata)
    return {
        "status": "ok",
        "action": override_result,
        "criterion": criterion.to_dict(),
    }


@app.get("/api/criteria")
async def list_criteria(user=Depends(get_current_user)):
    items = [item.to_dict() for item in prompt_manager.list_criteria()]
    return {"items": items}


@app.post("/api/criteria")
async def create_criterion(payload: CriterionPayload = Body(...), user=Depends(get_current_user)):
    criterion = prompt_manager.add_criterion(payload.text.strip())
    return {"item": criterion.to_dict()}


@app.patch("/api/criteria/{criterion_id}")
async def update_criterion(criterion_id: str, payload: CriterionUpdatePayload = Body(...), user=Depends(get_current_user)):
    updated = None
    if payload.text is not None:
        updated = prompt_manager.update_criterion(criterion_id, payload.text)
    if payload.enabled is not None:
        updated = prompt_manager.toggle_criterion(criterion_id, enabled=payload.enabled)
    if updated is None:
        updated = prompt_manager.get_criterion(criterion_id)
    return {"item": updated.to_dict()}


@app.delete("/api/criteria/{criterion_id}")
async def delete_criterion(criterion_id: str, user=Depends(get_current_user)):
    prompt_manager.delete_criterion(criterion_id)
    return {"status": "deleted"}


# -----------------------------
# Message viewer + actions
# -----------------------------

@app.get("/api/messages")
async def list_messages(
    label: str = "inbox",
    max_results: int = 50,
    page_token: Optional[str] = None,
    mailbox_email: Optional[str] = None,
    user=Depends(get_current_user),
):
    mailbox = (mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    if max_results <= 0 or max_results > 500:
        raise HTTPException(status_code=400, detail="max_results must be between 1 and 500.")

    service = gmail_service_factory(mailbox)
    kwargs: Dict[str, Any] = {
        "userId": mailbox,
        "maxResults": max_results,
    }
    q = None
    if label == "inbox":
        kwargs["labelIds"] = ["INBOX"]
    elif label == "requires_response":
        q = 'label:"Requiring Response"'
    elif label == "should_read":
        q = 'label:"User Should Read"'
    elif label == "all":
        # no filters
        pass
    else:
        raise HTTPException(status_code=400, detail="Unsupported label filter.")
    if q:
        kwargs["q"] = q
    if page_token:
        kwargs["pageToken"] = page_token

    try:
        response = service.users().messages().list(**kwargs).execute()
    except HttpError as he:  # type: ignore
        # Provide clearer error details for common permission/scope issues
        status = getattr(getattr(he, "resp", None), "status", 500)
        raw = getattr(he, "content", b"")
        try:
            detail = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except Exception:
            detail = str(he)
        msg = detail or str(he)
        if status == 403 or "insufficientPermissions" in msg or "insufficient authentication scopes" in msg:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Gmail permission error. Token may lack required scopes or be invalid. "
                    "If using OAuth tokens, re-consent locally with GMAIL_AUTO_REAUTH=1 and GMAIL_ALLOW_OAUTH_FLOW=1. "
                    "If using domain-wide delegation, verify delegated user and scopes. Details: " + msg
                ),
            )
        raise HTTPException(status_code=500, detail=f"Failed to list messages: {msg}")
    items: List[Dict[str, Any]] = []
    for msg in response.get("messages", []) or []:
        mid = msg.get("id")
        if not mid:
            continue
        try:
            metadata = (
                service.users()
                .messages()
                .get(
                    userId=mailbox,
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
        except Exception:
            # Fallback to minimal fields if metadata fetch fails
            metadata = {"id": mid, "snippet": ""}
        headers = _extract_headers_from_metadata(metadata)
        items.append(
            {
                "gmail_id": metadata.get("id", mid),
                "thread_id": metadata.get("threadId", ""),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "snippet": metadata.get("snippet", ""),
            }
        )
    return {
        "items": items,
        "next_page_token": response.get("nextPageToken"),
        "result_size_estimate": response.get("resultSizeEstimate"),
    }


@app.get("/api/messages/{gmail_id}")
async def get_message(gmail_id: str, mailbox_email: Optional[str] = None, user=Depends(get_current_user)):
    mailbox = (mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    service = gmail_service_factory(mailbox)
    try:
        message = (
            service.users()
            .messages()
            .get(userId=mailbox, id=gmail_id, format="full")
            .execute()
        )
    except Exception as exc:  # pragma: no cover - external
        raise HTTPException(status_code=500, detail=str(exc))
    headers = _extract_headers_from_metadata(message)
    text_body, html_body = _extract_bodies(message.get("payload", {}))
    return {
        "gmail_id": message.get("id", gmail_id),
        "thread_id": message.get("threadId", ""),
        "headers": headers,
        "snippet": message.get("snippet", ""),
        "body_text": text_body,
        "body_html": html_body,
    }


@app.post("/api/messages/{gmail_id}/reply")
async def reply_message(gmail_id: str, payload: ReplyPayload = Body(...), user=Depends(get_current_user)):
    mailbox = (payload.mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    body_text = payload.body_text.strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="body_text is required.")

    service = gmail_service_factory(mailbox)
    try:
        original = (
            service.users()
            .messages()
            .get(userId=mailbox, id=gmail_id, format="full")
            .execute()
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))
    headers = _extract_headers_from_metadata(original)
    thread_id = original.get("threadId")
    orig_subject = headers.get("subject", "")
    orig_msg_id = headers.get("message-id", "")
    references = headers.get("references", "").strip()

    to_addr = (payload.to or headers.get("reply-to") or headers.get("from") or "").strip()
    if not to_addr:
        raise HTTPException(status_code=400, detail="Could not determine reply target.")
    subject = (payload.subject or (orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}")).strip()

    lines = [
        f"From: {mailbox}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        f"Date: {email_utils.formatdate(localtime=True)}",
    ]
    if orig_msg_id:
        lines.append(f"In-Reply-To: {orig_msg_id}")
        ref_value = f"{references} {orig_msg_id}".strip() if references else orig_msg_id
        lines.append(f"References: {ref_value}")
    lines += [
        "MIME-Version: 1.0",
        'Content-Type: text/plain; charset="UTF-8"',
        "Content-Transfer-Encoding: 7bit",
        "",
        body_text,
    ]
    raw_bytes = "\r\n".join(lines).encode("utf-8")
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")
    body: Dict[str, Any] = {"raw": raw_b64}
    if thread_id:
        body["threadId"] = thread_id
    try:
        sent = service.users().messages().send(userId=mailbox, body=body).execute()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "sent", "id": sent.get("id"), "thread_id": sent.get("threadId")}


@app.post("/api/messages/{gmail_id}/archive")
async def archive_message(gmail_id: str, payload: MailboxPayload = Body(...), user=Depends(get_current_user)):
    mailbox = (payload.mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    service = gmail_service_factory(mailbox)
    try:
        service.users().messages().modify(
            userId=mailbox,
            id=gmail_id,
            body={"removeLabelIds": ["INBOX"], "addLabelIds": []},
        ).execute()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "archived", "gmail_id": gmail_id}


@app.post("/api/messages/{gmail_id}/delete")
async def delete_message(gmail_id: str, payload: MailboxPayload = Body(...), user=Depends(get_current_user)):
    mailbox = (payload.mailbox_email or user["email"]).strip()
    if not mailbox:
        raise HTTPException(status_code=400, detail="mailbox_email is required.")
    service = gmail_service_factory(mailbox)
    try:
        service.users().messages().delete(userId=mailbox, id=gmail_id).execute()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "deleted", "gmail_id": gmail_id}



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
