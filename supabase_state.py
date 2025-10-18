import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


class SupabaseConfigurationError(RuntimeError):
    """Raised when Supabase credentials are missing."""


@dataclass
class MailboxState:
    email: str
    history_id: Optional[str] = None
    watch_expiration: Optional[int] = None


class BaseStateStore:
    def get_mailbox(self, email: str) -> Optional[MailboxState]:
        raise NotImplementedError

    def upsert_mailbox(self, state: MailboxState) -> MailboxState:
        raise NotImplementedError

    def log_message_decision(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        decision_json: Dict[str, Any],
    ) -> None:
        raise NotImplementedError

    def log_alert(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        summary: str,
        status: str,
        error_detail: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    def list_queued_alerts(self) -> list[Dict[str, Any]]:
        """Return alerts queued for the daily digest."""
        raise NotImplementedError

    def mark_alerts_sent(self, alerts: list[Dict[str, Any]]) -> None:
        """Mark a batch of queued alerts as sent."""
        raise NotImplementedError


class SupabaseStateStore(BaseStateStore):
    """
    Minimal Supabase REST client for storing Gmail mailbox + message metadata.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        *,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.url = url or os.getenv("SUPABASE_URL")
        self.key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not self.url or not self.key:
            raise SupabaseConfigurationError("Supabase URL and service role key must be configured.")
        self.session = session or requests.Session()
        self._headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _rest(self, path: str) -> str:
        return f"{self.url}/rest/v1/{path.lstrip('/')}"

    def get_mailbox(self, email: str) -> Optional[MailboxState]:
        response = self.session.get(
            self._rest("mailboxes"),
            params={"email": f"eq.{email}", "select": "*", "limit": 1},
            headers=self._headers,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        record = data[0]
        return MailboxState(
            email=record["email"],
            history_id=record.get("history_id"),
            watch_expiration=record.get("watch_expiration"),
        )

    def upsert_mailbox(self, state: MailboxState) -> MailboxState:
        payload = {
            "email": state.email,
            "history_id": state.history_id,
            "watch_expiration": state.watch_expiration,
        }
        response = self.session.post(
            self._rest("mailboxes"),
            headers={**self._headers, "Prefer": "return=representation,resolution=merge-duplicates"},
            data=json.dumps(payload),
        )
        response.raise_for_status()
        # Some Supabase configurations may still return 204 No Content. In that case,
        # fall back to returning the requested state.
        if not response.content:
            return state
        saved = response.json()[0]
        return MailboxState(
            email=saved["email"],
            history_id=saved.get("history_id"),
            watch_expiration=saved.get("watch_expiration"),
        )

    def log_message_decision(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        decision_json: Dict[str, Any],
    ) -> None:
        payload = {
            "gmail_id": gmail_id,
            "mailbox_email": mailbox_email,
            "decision_json": decision_json,
        }
        response = self.session.post(
            self._rest("messages"),
            headers=self._headers,
            data=json.dumps(payload),
        )
        response.raise_for_status()

    def log_alert(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        summary: str,
        status: str,
        error_detail: Optional[str] = None,
    ) -> None:
        payload = {
            "gmail_id": gmail_id,
            "mailbox_email": mailbox_email,
            "summary": summary,
            "status": status,
            "error_detail": error_detail,
        }
        response = self.session.post(
            self._rest("alerts"),
            headers=self._headers,
            data=json.dumps(payload),
        )
        response.raise_for_status()

    def list_queued_alerts(self) -> list[Dict[str, Any]]:
        response = self.session.get(
            self._rest("alerts"),
            params={
                "select": "gmail_id,mailbox_email,summary,status",
                "status": "eq.queued",
            },
            headers=self._headers,
        )
        response.raise_for_status()
        return response.json()

    def mark_alerts_sent(self, alerts: list[Dict[str, Any]]) -> None:
        # Update each alert row by matching gmail_id + mailbox_email
        for item in alerts:
            gmail_id = item.get("gmail_id")
            mailbox_email = item.get("mailbox_email")
            if not gmail_id or not mailbox_email:
                continue
            response = self.session.patch(
                self._rest("alerts"),
                params={
                    "gmail_id": f"eq.{gmail_id}",
                    "mailbox_email": f"eq.{mailbox_email}",
                },
                headers=self._headers,
                data=json.dumps({"status": "sent"}),
            )
            response.raise_for_status()


class NullStateStore(BaseStateStore):
    """
    In-memory fallback when Supabase is not yet configured.
    """

    def __init__(self) -> None:
        self.mailboxes: Dict[str, MailboxState] = {}
        self.decisions: Dict[str, Dict[str, Any]] = {}
        self.alerts: Dict[str, Dict[str, Any]] = {}

    def get_mailbox(self, email: str) -> Optional[MailboxState]:
        return self.mailboxes.get(email)

    def upsert_mailbox(self, state: MailboxState) -> MailboxState:
        self.mailboxes[state.email] = state
        return state

    def log_message_decision(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        decision_json: Dict[str, Any],
    ) -> None:
        # In lieu of Supabase, we just store the latest decision in memory.
        key = f"{mailbox_email}:{gmail_id}"
        self.mailboxes.setdefault(mailbox_email, MailboxState(email=mailbox_email))
        self.decisions[key] = decision_json

    def log_alert(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        summary: str,
        status: str,
        error_detail: Optional[str] = None,
    ) -> None:
        key = f"{mailbox_email}:{gmail_id}"
        self.alerts[key] = {"gmail_id": gmail_id, "mailbox_email": mailbox_email, "summary": summary, "status": status, "error": error_detail}

    def list_queued_alerts(self) -> list[Dict[str, Any]]:
        return [
            {"gmail_id": v.get("gmail_id"), "mailbox_email": k.split(":")[0], "summary": v.get("summary"), "status": v.get("status")}
            for k, v in self.alerts.items()
            if v.get("status") == "queued"
        ]

    def mark_alerts_sent(self, alerts: list[Dict[str, Any]]) -> None:
        for item in alerts:
            mailbox_email = item.get("mailbox_email")
            gmail_id = item.get("gmail_id")
            if not mailbox_email or not gmail_id:
                continue
            key = f"{mailbox_email}:{gmail_id}"
            if key in self.alerts:
                self.alerts[key]["status"] = "sent"


def get_state_store(url: Optional[str] = None, service_role_key: Optional[str] = None) -> BaseStateStore:
    try:
        return SupabaseStateStore(url=url, service_role_key=service_role_key)
    except SupabaseConfigurationError:
        return NullStateStore()
