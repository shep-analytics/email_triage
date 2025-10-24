import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests


class SupabaseConfigurationError(RuntimeError):
    """Raised when Supabase credentials are missing."""


@dataclass
class MailboxState:
    email: str
    history_id: Optional[str] = None
    watch_expiration: Optional[int] = None


@dataclass
class MessageSummary:
    gmail_id: str
    mailbox_email: str
    summary: str
    model: Optional[str] = None
    generated_at: Optional[str] = None


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

    # --- Message summaries -------------------------------------------------

    def get_message_summary(self, *, gmail_id: str, mailbox_email: str) -> Optional[MessageSummary]:
        raise NotImplementedError

    def get_message_summaries(self, *, mailbox_email: str, gmail_ids: Iterable[str]) -> Dict[str, MessageSummary]:
        raise NotImplementedError

    def upsert_message_summary(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        summary: str,
        model: Optional[str] = None,
    ) -> MessageSummary:
        raise NotImplementedError

    def delete_message_summary(self, *, gmail_id: str, mailbox_email: str) -> None:
        raise NotImplementedError

    # --- OAuth token storage (optional) -----------------------------------

    def get_gmail_token(self, *, email: str) -> Optional[str]:
        """Return serialized OAuth credential JSON for the mailbox, if stored."""
        return None

    def upsert_gmail_token(self, *, email: str, token_json: str) -> None:
        """Persist or replace serialized OAuth credential JSON for the mailbox."""
        return None


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

    @staticmethod
    def _summary_source() -> str:
        return "viewer_summary"

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

    # --- Message summaries -------------------------------------------------

    def get_message_summary(self, *, gmail_id: str, mailbox_email: str) -> Optional[MessageSummary]:
        items = self.get_message_summaries(mailbox_email=mailbox_email, gmail_ids=[gmail_id])
        return items.get(gmail_id)

    def get_message_summaries(self, *, mailbox_email: str, gmail_ids: Iterable[str]) -> Dict[str, MessageSummary]:
        ids = [gid for gid in gmail_ids if gid]
        if not ids:
            return {}
        results: Dict[str, MessageSummary] = {}
        chunk_size = 20
        for start in range(0, len(ids), chunk_size):
            batch = ids[start : start + chunk_size]
            or_filter = ",".join(f"gmail_id.eq.{gid}" for gid in batch)
            params = {
                "select": "gmail_id,mailbox_email,decision_json,processed_at",
                "mailbox_email": f"eq.{mailbox_email}",
                "decision_json->>source": f"eq.{self._summary_source()}",
                "or": f"({or_filter})",
                "order": "processed_at.desc",
            }
            response = self.session.get(self._rest("messages"), params=params, headers=self._headers)
            response.raise_for_status()
            for row in response.json() or []:
                decision = row.get("decision_json") or {}
                summary_text = decision.get("summary") or decision.get("summary_text")
                if not summary_text:
                    continue
                gmail_id = row.get("gmail_id")
                if not gmail_id or gmail_id in results:
                    continue
                results[gmail_id] = MessageSummary(
                    gmail_id=gmail_id,
                    mailbox_email=row.get("mailbox_email", mailbox_email),
                    summary=summary_text,
                    model=decision.get("model"),
                    generated_at=row.get("processed_at"),
                )
        return results

    def upsert_message_summary(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        summary: str,
        model: Optional[str] = None,
    ) -> MessageSummary:
        # Remove any prior cached summary to avoid duplicates.
        self.delete_message_summary(gmail_id=gmail_id, mailbox_email=mailbox_email)
        payload = {
            "gmail_id": gmail_id,
            "mailbox_email": mailbox_email,
            "decision_json": {
                "summary": summary,
                "model": model,
                "source": self._summary_source(),
            },
        }
        response = self.session.post(
            self._rest("messages"),
            headers={**self._headers, "Prefer": "return=representation"},
            data=json.dumps(payload),
        )
        response.raise_for_status()
        body = response.json()[0]
        decision = body.get("decision_json") or {}
        return MessageSummary(
            gmail_id=body.get("gmail_id", gmail_id),
            mailbox_email=body.get("mailbox_email", mailbox_email),
            summary=decision.get("summary", summary),
            model=decision.get("model", model),
            generated_at=body.get("processed_at"),
        )

    def delete_message_summary(self, *, gmail_id: str, mailbox_email: str) -> None:
        response = self.session.delete(
            self._rest("messages"),
            params={
                "gmail_id": f"eq.{gmail_id}",
                "mailbox_email": f"eq.{mailbox_email}",
                "decision_json->>source": f"eq.{self._summary_source()}",
            },
            headers=self._headers,
        )
        response.raise_for_status()

    # --- OAuth token storage ----------------------------------------------

    def get_gmail_token(self, *, email: str) -> Optional[str]:
        try:
            response = self.session.get(
                self._rest("gmail_tokens"),
                params={"email": f"eq.{email}", "select": "token_json", "limit": 1},
                headers=self._headers,
                timeout=30,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            items = response.json() or []
            if not items:
                return None
            token_json = items[0].get("token_json")
            # token_json might already be a string or a dict depending on PostgREST settings
            if isinstance(token_json, str):
                return token_json
            if isinstance(token_json, dict):
                import json as _json

                return _json.dumps(token_json)
            return None
        except requests.RequestException:
            # Table may not exist or Supabase unreachable; degrade gracefully
            return None

    def upsert_gmail_token(self, *, email: str, token_json: str) -> None:
        try:
            payload = {"email": email, "token_json": token_json}
            response = self.session.post(
                self._rest("gmail_tokens"),
                headers={**self._headers, "Prefer": "return=minimal,resolution=merge-duplicates"},
                data=json.dumps(payload),
                timeout=30,
            )
            # Some configurations return 201, some 204
            if response.status_code not in (200, 201, 204):
                response.raise_for_status()
        except requests.RequestException:
            # Non-critical; ignore if the table is missing
            return


class NullStateStore(BaseStateStore):
    """
    In-memory fallback when Supabase is not yet configured.
    """

    def __init__(self) -> None:
        self.mailboxes: Dict[str, MailboxState] = {}
        self.decisions: Dict[str, Dict[str, Any]] = {}
        self.alerts: Dict[str, Dict[str, Any]] = {}
        self.summaries: Dict[str, MessageSummary] = {}
        self.tokens: Dict[str, str] = {}

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

    # --- Message summaries -------------------------------------------------

    def get_message_summary(self, *, gmail_id: str, mailbox_email: str) -> Optional[MessageSummary]:
        return self.summaries.get(f"{mailbox_email}:{gmail_id}")

    def get_message_summaries(self, *, mailbox_email: str, gmail_ids: Iterable[str]) -> Dict[str, MessageSummary]:
        results: Dict[str, MessageSummary] = {}
        for gid in gmail_ids:
            if not gid:
                continue
            summary = self.get_message_summary(gmail_id=gid, mailbox_email=mailbox_email)
            if summary:
                results[gid] = summary
        return results

    def upsert_message_summary(
        self,
        *,
        gmail_id: str,
        mailbox_email: str,
        summary: str,
        model: Optional[str] = None,
    ) -> MessageSummary:
        record = MessageSummary(
            gmail_id=gmail_id,
            mailbox_email=mailbox_email,
            summary=summary,
            model=model,
        )
        self.summaries[f"{mailbox_email}:{gmail_id}"] = record
        return record

    def delete_message_summary(self, *, gmail_id: str, mailbox_email: str) -> None:
        self.summaries.pop(f"{mailbox_email}:{gmail_id}", None)

    # --- OAuth token storage ----------------------------------------------
    def get_gmail_token(self, *, email: str) -> Optional[str]:
        return self.tokens.get(email)

    def upsert_gmail_token(self, *, email: str, token_json: str) -> None:
        self.tokens[email] = token_json


def get_state_store(url: Optional[str] = None, service_role_key: Optional[str] = None) -> BaseStateStore:
    try:
        return SupabaseStateStore(url=url, service_role_key=service_role_key)
    except SupabaseConfigurationError:
        return NullStateStore()
