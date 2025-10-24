"""
Helpers for registering Gmail push notifications and fetching history updates.

These utilities rely on google-auth and google-api-python-client. Install them with:
    pip install google-api-python-client google-auth google-auth-oauthlib
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Scope sets
# - Default read/modify set used for most operations (list, labels, archive/delete)
GMAIL_READ_SCOPES = [
    # Modify includes read access, but we also declare readonly explicitly
    # to avoid scope-mismatch surprises with previously-minted tokens.
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
    # Be explicit about metadata access to avoid any provider quirks
    "https://www.googleapis.com/auth/gmail.metadata",
]

# - Send scope is requested only where needed (reply endpoint)
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

# Convenience union for callers that need send + read/modify
GMAIL_SEND_SCOPES = [*GMAIL_READ_SCOPES, GMAIL_SEND_SCOPE]


@dataclass
class GmailAccount:
    """
    Represents a Gmail mailbox that will receive push notifications.
    """

    user_id: str  # "me" or the email address
    topic_name: str  # Pub/Sub topic in the form projects/<project>/topics/<topic>
    label_ids: Sequence[str] = ("INBOX",)  # monitored labels when using "include"
    label_filter_action: str = "include"  # "include" or "exclude"
    label_filter_exclude_ids: Sequence[str] = ()  # labels to suppress when using "exclude"


def build_gmail_service(
    *,
    service_account_file: Optional[str] = None,
    delegated_user: Optional[str] = None,
    oauth_client_secret: Optional[str] = None,
    oauth_token_file: Optional[str] = None,
    oauth_credentials_json: Optional[str] = None,
    scopes: Iterable[str] = GMAIL_READ_SCOPES,
    allow_oauth_flow: bool = True,
    oauth_flow_mode: Optional[str] = None,
    token_update_cb: Optional[Callable[[str], None]] = None,
):
    """
    Create a Gmail API service client.

    Options:
        - Domain-wide delegation: provide service_account_file and the delegated_user email address.
        - OAuth client flow: provide oauth_client_secret and oauth_token_file path for storing refresh tokens.
    """
    scopes = list(scopes)
    # Allow callers to append extra scopes via env for flexibility without code changes.
    extra = os.getenv("GMAIL_EXTRA_SCOPES", "").strip()
    if extra:
        for scope in (s.strip() for s in extra.split(",") if s.strip()):
            if scope not in scopes:
                scopes.append(scope)

    if service_account_file:
        credentials = ServiceAccountCredentials.from_service_account_file(
            service_account_file,
            scopes=scopes,
        )
        if delegated_user:
            credentials = credentials.with_subject(delegated_user)
    else:
        if not oauth_client_secret:
            raise ValueError("oauth_client_secret is required when service_account_file is not provided.")
        credentials = None
        if oauth_credentials_json:
            try:
                credentials = Credentials.from_authorized_user_info(json.loads(oauth_credentials_json), scopes=scopes)
            except Exception:
                credentials = None
        if not credentials and oauth_token_file and os.path.exists(oauth_token_file):
            credentials = Credentials.from_authorized_user_file(oauth_token_file, scopes=scopes)

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                try:
                    serialized = credentials.to_json()
                    if oauth_token_file:
                        with open(oauth_token_file, "w", encoding="utf-8") as token_handle:
                            token_handle.write(serialized)
                    if token_update_cb:
                        token_update_cb(serialized)
                except Exception:
                    pass
            else:
                if not allow_oauth_flow:
                    raise RuntimeError(
                        "Missing or invalid Gmail OAuth token and interactive OAuth is disabled. "
                        "Run bootstrap_gmail_token.py locally to generate a refresh token, commit the token file, and redeploy."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(oauth_client_secret, scopes=scopes)
                # Allow console-based device flow when running in headless terminals
                chosen_mode = (oauth_flow_mode or os.getenv("GMAIL_OAUTH_FLOW", "local_server")).strip().lower()
                if chosen_mode in {"console", "device", "device_code"}:
                    credentials = flow.run_console()
                else:
                    credentials = flow.run_local_server(port=0)
                try:
                    serialized = credentials.to_json()
                    if oauth_token_file:
                        with open(oauth_token_file, "w", encoding="utf-8") as token_handle:
                            token_handle.write(serialized)
                    if token_update_cb:
                        token_update_cb(serialized)
                except Exception:
                    pass

    return build("gmail", "v1", credentials=credentials)


def start_watch(service, account: GmailAccount) -> Dict[str, Any]:
    """
    Register Gmail push notifications for the mailbox.
    Returns the watch response containing historyId and expiration.
    """
    body: Dict[str, Any] = {
        "topicName": account.topic_name,
        "labelFilterAction": account.label_filter_action,
    }
    if account.label_filter_action == "include":
        body["labelIds"] = list(account.label_ids)
    elif account.label_filter_action == "exclude":
        body["labelIds"] = list(account.label_filter_exclude_ids)
    else:
        raise ValueError("label_filter_action must be 'include' or 'exclude'.")
    request = service.users().watch(userId=account.user_id, body=body)
    return request.execute()


def stop_watch(service, user_id: str = "me") -> None:
    """Cancel existing Gmail push notifications for the mailbox."""
    service.users().stop(userId=user_id).execute()


def fetch_history(
    service,
    *,
    user_id: str,
    start_history_id: Optional[str],
    history_types: Optional[Sequence[str]] = None,
    max_results: int = 500,
    page_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch Gmail history records since start_history_id.
    Returns the API response which includes messages added/labels applied, etc.
    """
    if not start_history_id:
        raise ValueError("start_history_id is required to fetch history.")

    kwargs: Dict[str, Any] = {
        "userId": user_id,
        "startHistoryId": start_history_id,
        "maxResults": max_results,
    }
    if history_types:
        kwargs["historyTypes"] = list(history_types)
    if page_token:
        kwargs["pageToken"] = page_token

    return service.users().history().list(**kwargs).execute()


def get_message_metadata(service, user_id: str, message_id: str, format_: str = "metadata") -> Dict[str, Any]:
    """
    Fetch a single Gmail message. Use format_ 'metadata' to avoid downloading bodies.
    """
    return (
        service.users()
        .messages()
        .get(
            userId=user_id,
            id=message_id,
            format=format_,
            metadataHeaders=["From", "To", "Subject", "Date", "Message-ID"],
        )
        .execute()
    )


def parse_gmail_push_data(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Decode Gmail push message payload from Pub/Sub.
    Returns the JSON decoded Gmail notification or None if the message is not for Gmail.
    """
    import base64

    data = message.get("data")
    if not data:
        return None
    if isinstance(data, bytes):
        decoded_bytes = base64.b64decode(data)
    else:
        decoded_bytes = base64.b64decode(data.encode("utf-8"))
    decoded_json = json.loads(decoded_bytes.decode("utf-8"))
    if "emailAddress" in decoded_json:
        return decoded_json
    return None


def safe_execute(callable_request, *, retry_codes: Optional[Sequence[int]] = None, max_attempts: int = 3):
    """
    Execute a Google API request with simple retry logic on selected HTTP status codes.
    """
    retry_codes = set(retry_codes or [500, 502, 503, 504])
    attempts = 0
    while True:
        attempts += 1
        try:
            return callable_request.execute()
        except HttpError as exc:  # pragma: no cover - depends on API responses
            status = getattr(exc.resp, "status", None)
            if status in retry_codes and attempts < max_attempts:
                continue
            raise
