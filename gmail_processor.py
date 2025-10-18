import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Literal, Optional, Sequence

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource  # pragma: no cover

from gmail_watch import fetch_history, get_message_metadata, parse_gmail_push_data
from query_LLM import query_llm
from supabase_state import BaseStateStore, MailboxState
from telegram_notify import send_telegram_message, wait_for_callback_selection

try:
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:  # pragma: no cover
    HttpError = Exception  # type: ignore


@dataclass
class ClassificationDecision:
    action: str  # one of: alert_immediately, alert_today, archive, delete
    summary: str
    confidence: float
    reason: str
    labels: Sequence[str]


CleanupCategory = Literal["spam", "receipt", "useful_archive", "requires_response", "should_read"]

_CLEANUP_CATEGORY_ORDER: Sequence[CleanupCategory] = (
    "spam",
    "receipt",
    "useful_archive",
    "requires_response",
    "should_read",
)

_CLEANUP_CATEGORY_LABELS: Dict[CleanupCategory, str] = {
    "spam": "Deleted as spam",
    "receipt": "Receipts archived",
    "useful_archive": "Archived with labels",
    "requires_response": "Requires response (left in inbox)",
    "should_read": "Should read (left in inbox)",
}

_DEFAULT_RECEIPT_LABEL = "Receipts"
_DEFAULT_REQUIRES_RESPONSE_LABEL = "Requiring Response"
_DEFAULT_SHOULD_READ_LABEL = "User Should Read"

_CLEANUP_PROMPT_TEMPLATE = (
    "You are triaging a busy founder's Gmail inbox so that only items requiring attention remain.\n"
    "Classify the email described below and respond with a single JSON object containing:\n"
    '- "category": one of ["spam", "receipt", "useful_archive", "requires_response", "should_read"]\n'
    '- "label": label to use when category is "receipt" or "useful_archive"; otherwise use null or ""\n'
    '- "confidence": number between 0 and 1\n'
    '- "reason": brief justification\n'
    '- "summary": concise (<160 chars) synopsis for the user\n'
    "\n"
    "Guidelines:\n"
    '- Use "spam" only for clear spam/phishing. These will be deleted.\n'
    f'- Use "receipt" for purchase confirmations or invoices. Always set "label" to "{_DEFAULT_RECEIPT_LABEL}".\n'
    '- Use "useful_archive" for reference info worth keeping. Prefer an existing label from this list: {existing_labels}. '
    "If none apply, suggest a concise new label name in Title Case.\n"
    '- Use "requires_response" when the founder needs to reply. Leave the email in the inbox; do not suggest additional labels.\n'
    '- Use "should_read" for items to read soon without responding. Leave in inbox without new labels.\n'
    "Always return valid JSON and nothing else.\n"
    "\n"
    "Email metadata:\n"
    "From: {sender}\n"
    "To: {to}\n"
    "Date: {date}\n"
    "Subject: {subject}\n"
    "Snippet: {snippet}\n"
)


@dataclass
class InboxCleanupDecision:
    category: CleanupCategory
    confidence: float
    reason: str
    summary: str
    label: Optional[str] = None


class _LabelCache:
    """
    Minimal label cache to reuse IDs and create labels on demand.
    """

    def __init__(self, service: "Resource", user_id: str) -> None:
        self.service = service
        self.user_id = user_id
        self._labels_by_name: Dict[str, Dict[str, Any]] = {}
        self._labels_by_id: Dict[str, Dict[str, Any]] = {}
        self._refresh()

    def _refresh(self) -> None:
        response = self.service.users().labels().list(userId=self.user_id).execute()
        labels = response.get("labels", [])
        self._labels_by_name = {item["name"].lower(): item for item in labels}
        self._labels_by_id = {item["id"]: item for item in labels}

    def ensure(self, name: str, *, create: bool = False) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Label name must be a non-empty string.")
        existing = self._labels_by_name.get(normalized.lower())
        if existing:
            return existing["id"]
        if not create:
            raise KeyError(f"Label '{normalized}' does not exist.")
        body = {
            "name": normalized,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = self.service.users().labels().create(userId=self.user_id, body=body).execute()
        self._labels_by_name[created["name"].lower()] = created
        self._labels_by_id[created["id"]] = created
        return created["id"]

    def user_label_names(self) -> List[str]:
        return [
            details["name"]
            for details in self._labels_by_id.values()
            if details.get("type") == "user" and details.get("name")
        ]


class GmailProcessor:
    """
    Coordinates Gmail history fetching, classification, Gmail actions, telemetry, and alerts.
    """

    def __init__(
        self,
        *,
        gmail_service_factory,
        state_store: BaseStateStore,
        classification_prompt_path: Path,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ) -> None:
        self.gmail_service_factory = gmail_service_factory
        self.state_store = state_store
        self.classification_prompt = classification_prompt_path.read_text(encoding="utf-8").strip()
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id

    def handle_pubsub_envelope(self, envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        notification = parse_gmail_push_data(envelope.get("message", {}))
        if not notification:
            return None
        self.process_notification(notification)
        return notification

    def process_notification(self, notification: Dict[str, Any]) -> None:
        email_address = notification["emailAddress"]
        history_id = notification["historyId"]

        mailbox_state = self._get_mailbox_state(email_address)

        start_history_id = mailbox_state.history_id or history_id
        service = self.gmail_service_factory(email_address)
        # Optional preflight: verify scopes and auto-reauth if permitted
        auto_reauth = str(os.getenv("GMAIL_AUTO_REAUTH", "")).lower() in {"1", "true", "yes", "on"}
        reauth_attempted = False
        try:
            service.users().labels().list(userId=email_address).execute()
        except HttpError as he:  # pragma: no cover - depends on external services
            detail = str(getattr(he, "content", b""))
            if ("insufficient" in detail.lower() or "permission" in detail.lower()) and auto_reauth:
                os.environ["GMAIL_ALLOW_OAUTH_FLOW"] = "1"
                service = self.gmail_service_factory(email_address)
                reauth_attempted = True
                # Try again; if it fails again, let it raise
                service.users().labels().list(userId=email_address).execute()

        history_records = []
        page_token: Optional[str] = None
        new_history_id = start_history_id
        while True:
            history_response = fetch_history(
                service,
                user_id=email_address,
                start_history_id=start_history_id,
                history_types=["messageAdded"],
                page_token=page_token,
            )
            history_records.extend(history_response.get("history", []))
            new_history_id = history_response.get("historyId", new_history_id)
            page_token = history_response.get("nextPageToken")
            if not page_token:
                break

        for history_record in history_records:
            for message in history_record.get("messagesAdded", []):
                message_id = message["message"]["id"]
                try:
                    # Prefer metadata; fall back to full if API reports scope issues
                    try:
                        metadata = get_message_metadata(service, email_address, message_id, format_="metadata")
                    except HttpError as he:
                        detail_bytes = getattr(he, "content", b"")
                        try:
                            detail = detail_bytes.decode("utf-8") if isinstance(detail_bytes, (bytes, bytearray)) else str(detail_bytes)
                        except Exception:
                            detail = str(he)
                        if "insufficient" in detail.lower() or "permission" in detail.lower():
                            metadata = get_message_metadata(service, email_address, message_id, format_="full")
                        else:
                            raise
                    headers = self._extract_headers(metadata)
                    log_payload: Dict[str, Any] = {
                        "metadata": {
                            "snippet": metadata.get("snippet"),
                            "headers": headers,
                        }
                    }
                    decision = self._classify_message(metadata, headers)
                    log_payload["decision"] = {
                        "action": decision.action,
                        "summary": decision.summary,
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                        "labels": list(decision.labels),
                    }
                    self._apply_gmail_action(service, email_address, message_id, decision)
                    if decision.action == "alert_immediately":
                        alert_sent = self._send_telegram_alert(
                            decision,
                            gmail_id=message_id,
                            mailbox_email=email_address,
                        )
                        log_payload["alert_status"] = "sent" if alert_sent else "error"
                    elif decision.action == "alert_today":
                        # Defer alert into the daily digest queue
                        self.state_store.log_alert(
                            gmail_id=message_id,
                            mailbox_email=email_address,
                            summary=decision.summary,
                            status="queued",
                        )
                        log_payload["alert_status"] = "queued"
                    log_payload["status"] = "processed"
                except HttpError as he:  # pragma: no cover - depends on external services
                    # Record the actual Gmail error; do not label as restricted
                    detail_bytes = getattr(he, "content", b"")
                    try:
                        detail = detail_bytes.decode("utf-8") if isinstance(detail_bytes, (bytes, bytearray)) else str(detail_bytes)
                    except Exception:
                        detail = str(he)
                    log_payload = {"status": "error", "error": detail}
                except Exception as exc:  # pragma: no cover - depends on external services
                    log_payload["status"] = "error"
                    log_payload["error"] = str(exc)
                finally:
                    self.state_store.log_message_decision(
                        gmail_id=message_id,
                        mailbox_email=email_address,
                        decision_json=log_payload,
                    )

        self.state_store.upsert_mailbox(
            MailboxState(
                email=email_address,
                history_id=new_history_id,
                watch_expiration=notification.get("expiration"),
            )
        )

    def clear_inbox(
        self,
        email_address: str,
        *,
        batch_size: int = 50,
        await_user_confirmation: bool = True,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer.")

        service = self.gmail_service_factory(email_address)
        label_cache = _LabelCache(service, email_address)

        token = telegram_token or self.telegram_token
        chat_id = telegram_chat_id or self.telegram_chat_id

        total_counts: Counter[str] = Counter()
        total_processed = 0
        batches_processed = 0
        total_estimate: Optional[int] = None
        requiring_response_items: List[Dict[str, Any]] = []
        should_read_items: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        page_token: Optional[str] = None
        stopped_early = False

        # Auto-reauth support if scopes are insufficient
        auto_reauth = str(os.getenv("GMAIL_AUTO_REAUTH", "")).lower() in {"1", "true", "yes", "on"}
        reauth_attempted = False

        while True:
            if stopped_early:
                break

            try:
                response = service.users().messages().list(
                    userId=email_address,
                    labelIds=["INBOX"],
                    maxResults=batch_size,
                    pageToken=page_token,
                ).execute()
            except HttpError as he:  # pragma: no cover - depends on external services
                detail = str(getattr(he, "content", b""))
                if ("insufficient" in detail.lower() or "permission" in detail.lower()) and not reauth_attempted and auto_reauth:
                    os.environ["GMAIL_ALLOW_OAUTH_FLOW"] = "1"
                    service = self.gmail_service_factory(email_address)
                    reauth_attempted = True
                    response = service.users().messages().list(
                        userId=email_address,
                        labelIds=["INBOX"],
                        maxResults=batch_size,
                        pageToken=page_token,
                    ).execute()
                else:
                    raise
            if total_estimate is None:
                try:
                    total_estimate = int(response.get("resultSizeEstimate", 0))
                except (TypeError, ValueError):
                    total_estimate = None

            messages = response.get("messages", [])
            if not messages:
                break

            batches_processed += 1
            batch_counts: Counter[str] = Counter()
            batch_error_count = 0
            batch_requiring: List[Dict[str, Any]] = []
            batch_should_read: List[Dict[str, Any]] = []

            for message_meta in messages:
                message_id = message_meta.get("id")
                if not message_id:
                    continue
                try:
                    # Try to fetch message metadata; fall back to full if scope error appears
                    try:
                        metadata = get_message_metadata(service, email_address, message_id, format_="metadata")
                    except HttpError as he:
                        detail_bytes = getattr(he, "content", b"")
                        try:
                            detail = detail_bytes.decode("utf-8") if isinstance(detail_bytes, (bytes, bytearray)) else str(detail_bytes)
                        except Exception:
                            detail = str(he)
                        if "insufficient" in detail.lower() or "permission" in detail.lower():
                            metadata = get_message_metadata(service, email_address, message_id, format_="full")
                        else:
                            raise
                    headers = self._extract_headers(metadata)
                    log_payload: Dict[str, Any] = {
                        "mode": "cleanup",
                        "metadata": {
                            "snippet": metadata.get("snippet"),
                            "headers": headers,
                        },
                    }
                    decision = self._classify_cleanup_message(
                        metadata,
                        headers,
                        label_cache.user_label_names(),
                    )
                    log_payload["decision"] = {
                        "category": decision.category,
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                        "summary": decision.summary,
                        "label": decision.label,
                    }
                    action_detail = self._apply_cleanup_decision(
                        service,
                        email_address,
                        message_id,
                        decision,
                        label_cache,
                    )
                    log_payload["status"] = "processed"
                    log_payload["action_detail"] = action_detail
                    batch_counts[decision.category] += 1
                    total_counts[decision.category] += 1

                    message_record = {
                        "gmail_id": message_id,
                        "subject": headers.get("subject", "(no subject)"),
                        "from": headers.get("from", ""),
                        "summary": decision.summary or metadata.get("snippet", ""),
                        "reason": decision.reason,
                    }
                    if decision.category == "requires_response":
                        batch_requiring.append(message_record)
                        requiring_response_items.append(message_record)
                    elif decision.category == "should_read":
                        batch_should_read.append(message_record)
                        should_read_items.append(message_record)
                except HttpError as he:  # pragma: no cover - depends on external services
                    # Handle insufficient permissions by optional reauth (and try a full fetch once)
                    detail_bytes = getattr(he, "content", b"")
                    try:
                        detail = detail_bytes.decode("utf-8") if isinstance(detail_bytes, (bytes, bytearray)) else str(detail_bytes)
                    except Exception:
                        detail = str(he)

                    insufficient = "insufficient" in detail.lower() or "permission" in detail.lower()

                    if insufficient and auto_reauth and not reauth_attempted:
                        # Try one interactive reauth, then retry fetch once (metadata -> full)
                        os.environ["GMAIL_ALLOW_OAUTH_FLOW"] = "1"
                        service = self.gmail_service_factory(email_address)
                        reauth_attempted = True
                        try:
                            try:
                                metadata = get_message_metadata(service, email_address, message_id, format_="metadata")
                            except HttpError:
                                metadata = get_message_metadata(service, email_address, message_id, format_="full")
                            headers = self._extract_headers(metadata)
                            log_payload = {
                                "mode": "cleanup",
                                "metadata": {
                                    "snippet": metadata.get("snippet"),
                                    "headers": headers,
                                },
                            }
                            decision = self._classify_cleanup_message(
                                metadata,
                                headers,
                                label_cache.user_label_names(),
                            )
                            log_payload["decision"] = {
                                "category": decision.category,
                                "confidence": decision.confidence,
                                "reason": decision.reason,
                                "summary": decision.summary,
                                "label": decision.label,
                            }
                            action_detail = self._apply_cleanup_decision(
                                service,
                                email_address,
                                message_id,
                                decision,
                                label_cache,
                            )
                            log_payload["status"] = "processed"
                            log_payload["action_detail"] = action_detail
                            batch_counts[decision.category] += 1
                            total_counts[decision.category] += 1
                            # Summaries for Telegram list
                            message_record = {
                                "gmail_id": message_id,
                                "subject": headers.get("subject", "(no subject)"),
                                "from": headers.get("from", ""),
                                "summary": decision.summary or metadata.get("snippet", ""),
                                "reason": decision.reason,
                            }
                            if decision.category == "requires_response":
                                batch_requiring.append(message_record)
                                requiring_response_items.append(message_record)
                            elif decision.category == "should_read":
                                batch_should_read.append(message_record)
                                should_read_items.append(message_record)
                            # Continue to next message; finalizer will persist log_payload
                            continue
                        except HttpError:
                            # Fall through to error recording below
                            pass
                    else:
                        error_to_record = he

                    # If we reach here, we couldn't recover; record error
                    log_payload = {"status": "error", "error": str(error_to_record if 'error_to_record' in locals() else str(he))}
                    errors.append({"gmail_id": message_id, "error": str(error_to_record if 'error_to_record' in locals() else he)})
                    batch_error_count += 1
                except Exception as exc:  # pragma: no cover - depends on external services
                    log_payload["status"] = "error"
                    log_payload["error"] = str(exc)
                    errors.append({"gmail_id": message_id, "error": str(exc)})
                    batch_error_count += 1
                finally:
                    if message_id:
                        self.state_store.log_message_decision(
                            gmail_id=message_id,
                            mailbox_email=email_address,
                            decision_json=log_payload,
                        )

            processed_in_batch = len(messages)
            total_processed += processed_in_batch
            page_token = response.get("nextPageToken")
            has_more = bool(page_token)

            if token and chat_id:
                decision_outcome = self._send_cleanup_batch_report(
                    email_address=email_address,
                    batch_number=batches_processed,
                    processed_in_batch=processed_in_batch,
                    batch_counts=batch_counts,
                    total_counts=total_counts,
                    batch_requiring=batch_requiring,
                    batch_should_read=batch_should_read,
                    errors_in_batch=batch_error_count,
                    total_errors=len(errors),
                    total_processed=total_processed,
                    total_estimate=total_estimate,
                    has_more=has_more,
                    await_user_confirmation=await_user_confirmation,
                    telegram_token=token,
                    telegram_chat_id=chat_id,
                )
                if decision_outcome == "stop":
                    stopped_early = True

            if not has_more:
                break

        return {
            "email": email_address,
            "processed_messages": total_processed,
            "batches_processed": batches_processed,
            "counts": {category: int(total_counts.get(category, 0)) for category in _CLEANUP_CATEGORY_ORDER},
            "requires_response": requiring_response_items,
            "should_read": should_read_items,
            "errors": errors,
            "error_count": len(errors),
            "stopped_early": stopped_early,
        }

    def _classify_message(self, metadata: Dict[str, Any], headers: Dict[str, str]) -> ClassificationDecision:
        prompt_body = self._format_prompt(
            sender=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", ""),
            date=headers.get("date", ""),
            snippet=metadata.get("snippet", ""),
        )
        response = query_llm(prompt_body)
        parsed = self._parse_decision(response)
        return parsed

    def _classify_cleanup_message(
        self,
        metadata: Dict[str, Any],
        headers: Dict[str, str],
        existing_labels: Sequence[str],
    ) -> InboxCleanupDecision:
        prompt_body = self._format_cleanup_prompt(
            sender=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", ""),
            date=headers.get("date", ""),
            snippet=metadata.get("snippet", ""),
            existing_labels=existing_labels,
        )
        response = query_llm(prompt_body)
        return self._parse_cleanup_decision(response)

    def _format_prompt(
        self,
        *,
        sender: str,
        to: str,
        subject: str,
        date: str,
        snippet: str,
    ) -> str:
        return (
            f"{self.classification_prompt}\n"
            "\n"
            "Email metadata:\n"
            f"From: {sender}\n"
            f"To: {to}\n"
            f"Date: {date}\n"
            f"Subject: {subject}\n"
            f"Snippet: {snippet}\n"
        )

    def _format_cleanup_prompt(
        self,
        *,
        sender: str,
        to: str,
        subject: str,
        date: str,
        snippet: str,
        existing_labels: Sequence[str],
    ) -> str:
        unique_labels = sorted({label for label in existing_labels if label})
        labels_text = ", ".join(unique_labels[:100]) if unique_labels else "None"
        rendered_snippet = (snippet or "").replace("\r\n", " ").replace("\n", " ").strip()
        if len(rendered_snippet) > 400:
            rendered_snippet = f"{rendered_snippet[:400]}..."
        return _CLEANUP_PROMPT_TEMPLATE.format(
            existing_labels=labels_text,
            sender=sender,
            to=to,
            date=date,
            subject=subject,
            snippet=rendered_snippet,
        )

    def _parse_decision(self, response: str) -> ClassificationDecision:
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned non-JSON response: {exc}") from exc

        action = data.get("action")
        if action not in {"alert_immediately", "alert_today", "archive", "delete"}:
            raise RuntimeError(f"LLM returned invalid action: {action}")

        summary = data.get("summary", "")
        if action in {"alert_immediately", "alert_today"} and not summary:
            raise RuntimeError("LLM must supply a summary when action starts with 'alert'.")

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        reason = data.get("reason", "")
        labels = data.get("labels") or []
        if not isinstance(labels, Iterable) or isinstance(labels, str):
            raise RuntimeError("LLM returned invalid labels list.")

        return ClassificationDecision(
            action=action,
            summary=summary,
            confidence=confidence,
            reason=reason,
            labels=[str(label) for label in labels],
        )

    def _parse_cleanup_decision(self, response: str) -> InboxCleanupDecision:
        def _strip_fences(text: str) -> str:
            t = text.strip()
            if t.startswith("```") and t.endswith("```"):
                # Remove leading and trailing code fences, optionally with a language tag
                t = t[3:]
                t = t.split("\n", 1)[-1] if "\n" in t else t
                t = t[:-3] if t.endswith("```") else t
            return t.strip()

        def _extract_json(text: str) -> Optional[dict]:
            # Quick and pragmatic extraction: take the first {...} block
            s = _strip_fences(text)
            start = s.find("{")
            end = s.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            candidate = s[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                return None

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = _extract_json(response)
            if data is None:
                raise RuntimeError("LLM returned non-JSON cleanup response: unable to parse JSON object")

        category = data.get("category")
        if category not in _CLEANUP_CATEGORY_ORDER:
            raise RuntimeError(f"LLM returned invalid cleanup category: {category}")

        label_value = data.get("label")
        if isinstance(label_value, str):
            label_value = label_value.strip() or None
        elif label_value is None:
            label_value = None
        else:
            raise RuntimeError("LLM returned invalid label field; expected string or null.")

        summary = str(data.get("summary", "")).strip()
        reason = str(data.get("reason", "")).strip()
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return InboxCleanupDecision(
            category=category,  # type: ignore[arg-type]
            confidence=confidence,
            reason=reason,
            summary=summary,
            label=label_value,
        )

    @staticmethod
    def _extract_headers(metadata: Dict[str, Any]) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        for header in metadata.get("payload", {}).get("headers", []):
            name = header.get("name")
            value = header.get("value")
            if name and value:
                headers[name.lower()] = value
        return headers

    def _apply_gmail_action(
        self,
        service: "Resource",
        user_id: str,
        message_id: str,
        decision: ClassificationDecision,
    ) -> None:
        if decision.action == "delete":
            service.users().messages().delete(userId=user_id, id=message_id).execute()
            return

        labels_body: Dict[str, Any] = {"removeLabelIds": [], "addLabelIds": []}

        if decision.action == "archive":
            labels_body["removeLabelIds"].append("INBOX")

        if decision.labels:
            labels_body["addLabelIds"] = list(decision.labels)

        if labels_body["removeLabelIds"] or labels_body["addLabelIds"]:
            service.users().messages().modify(
                userId=user_id,
                id=message_id,
                body=labels_body,
            ).execute()

    def _apply_cleanup_decision(
        self,
        service: "Resource",
        user_id: str,
        message_id: str,
        decision: InboxCleanupDecision,
        label_cache: _LabelCache,
    ) -> Dict[str, Any]:
        if decision.category == "spam":
            service.users().messages().delete(userId=user_id, id=message_id).execute()
            return {"action": "delete"}
        if decision.category == "receipt":
            label_id = label_cache.ensure(_DEFAULT_RECEIPT_LABEL, create=True)
            self._modify_message_labels(
                service,
                user_id,
                message_id,
                add_label_ids=[label_id],
                remove_label_ids=["INBOX"],
            )
            return {"action": "archive", "label": _DEFAULT_RECEIPT_LABEL}
        if decision.category == "useful_archive":
            label_name = decision.label or "Filed"
            label_id = label_cache.ensure(label_name, create=True)
            self._modify_message_labels(
                service,
                user_id,
                message_id,
                add_label_ids=[label_id],
                remove_label_ids=["INBOX"],
            )
            return {"action": "archive", "label": label_name}
        if decision.category == "requires_response":
            label_id = label_cache.ensure(_DEFAULT_REQUIRES_RESPONSE_LABEL, create=True)
            self._modify_message_labels(
                service,
                user_id,
                message_id,
                add_label_ids=[label_id],
                remove_label_ids=[],
            )
            return {"action": "label", "label": _DEFAULT_REQUIRES_RESPONSE_LABEL}
        if decision.category == "should_read":
            label_id = label_cache.ensure(_DEFAULT_SHOULD_READ_LABEL, create=True)
            self._modify_message_labels(
                service,
                user_id,
                message_id,
                add_label_ids=[label_id],
                remove_label_ids=[],
            )
            return {"action": "label", "label": _DEFAULT_SHOULD_READ_LABEL}
        raise RuntimeError(f"Unsupported cleanup category: {decision.category}")

    @staticmethod
    def _modify_message_labels(
        service: "Resource",
        user_id: str,
        message_id: str,
        *,
        add_label_ids: Sequence[str],
        remove_label_ids: Sequence[str],
    ) -> None:
        add_ids = [label for label in add_label_ids if label]
        remove_ids = [label for label in remove_label_ids if label]
        if not add_ids and not remove_ids:
            return
        service.users().messages().modify(
            userId=user_id,
            id=message_id,
            body={
                "addLabelIds": add_ids,
                "removeLabelIds": remove_ids,
            },
        ).execute()

    def _send_cleanup_batch_report(
        self,
        *,
        email_address: str,
        batch_number: int,
        processed_in_batch: int,
        batch_counts: Counter[str],
        total_counts: Counter[str],
        batch_requiring: Sequence[Dict[str, Any]],
        batch_should_read: Sequence[Dict[str, Any]],
        errors_in_batch: int,
        total_errors: int,
        total_processed: int,
        total_estimate: Optional[int],
        has_more: bool,
        await_user_confirmation: bool,
        telegram_token: str,
        telegram_chat_id: str,
    ) -> str:
        counts_display = {category: int(batch_counts.get(category, 0)) for category in _CLEANUP_CATEGORY_ORDER}
        total_display = {category: int(total_counts.get(category, 0)) for category in _CLEANUP_CATEGORY_ORDER}

        lines = [
            f"Inbox cleanup for {email_address}",
            f"Batch {batch_number}: processed {processed_in_batch} messages.",
        ]
        if total_estimate:
            lines.append(f"Processed so far: {total_processed} of ~{total_estimate}")
        else:
            lines.append(f"Processed so far: {total_processed}")

        lines.append("")
        lines.append("This batch:")
        for category in _CLEANUP_CATEGORY_ORDER:
            label = _CLEANUP_CATEGORY_LABELS[category]
            lines.append(f"- {label}: {counts_display.get(category, 0)}")
        if errors_in_batch:
            lines.append(f"- Errors: {errors_in_batch}")

        lines.append("")
        lines.append("Cumulative:")
        for category in _CLEANUP_CATEGORY_ORDER:
            label = _CLEANUP_CATEGORY_LABELS[category]
            lines.append(f"- {label}: {total_display.get(category, 0)}")
        if total_errors:
            lines.append(f"- Errors: {total_errors}")

        if batch_requiring:
            lines.append("")
            lines.append("Requires response:")
            for item in batch_requiring[:5]:
                subject = item.get("subject") or "(no subject)"
                sender = item.get("from") or ""
                lines.append(f"- {subject} {f'({sender})' if sender else ''}".rstrip())

        if batch_should_read:
            lines.append("")
            lines.append("Should read:")
            for item in batch_should_read[:5]:
                subject = item.get("subject") or "(no subject)"
                sender = item.get("from") or ""
                lines.append(f"- {subject} {f'({sender})' if sender else ''}".rstrip())

        reply_markup = None
        continue_data = None
        stop_data = None
        if has_more:
            batch_token = uuid.uuid4().hex
            continue_data = f"inbox-cleanup:{batch_token}:continue"
            stop_data = f"inbox-cleanup:{batch_token}:stop"
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "Continue to next 50", "callback_data": continue_data},
                        {"text": "Stop cleanup", "callback_data": stop_data},
                    ]
                ]
            }

        message = "\n".join(lines)
        try:
            send_telegram_message(
                message,
                token=telegram_token,
                chat_id=telegram_chat_id,
                disable_notification=False,
                reply_markup=reply_markup,
            )
        except Exception:
            return "continue"

        if not has_more or not await_user_confirmation or not continue_data or not stop_data:
            return "continue"

        try:
            selection = wait_for_callback_selection(
                [continue_data, stop_data],
                token=telegram_token,
            )
        except Exception:
            selection = None

        if selection == stop_data:
            send_telegram_message(
                "Stopping inbox cleanup at your request.",
                token=telegram_token,
                chat_id=telegram_chat_id,
                disable_notification=False,
            )
            return "stop"
        if selection == continue_data:
            return "continue"

        send_telegram_message(
            "No response received. Inbox cleanup paused.",
            token=telegram_token,
            chat_id=telegram_chat_id,
            disable_notification=False,
        )
        return "stop"

    def _send_telegram_alert(
        self,
        decision: ClassificationDecision,
        *,
        gmail_id: str,
        mailbox_email: str,
    ) -> bool:
        if not (self.telegram_token and self.telegram_chat_id):
            return False
        try:
            send_telegram_message(
                decision.summary,
                token=self.telegram_token,
                chat_id=self.telegram_chat_id,
            )
            self.state_store.log_alert(
                gmail_id=gmail_id,
                mailbox_email=mailbox_email,
                summary=decision.summary,
                status="sent",
            )
            return True
        except Exception as exc:  # pragma: no cover - network interactions
            self.state_store.log_alert(
                gmail_id=gmail_id,
                mailbox_email=mailbox_email,
                summary=decision.summary,
                status="error",
                error_detail=str(exc),
            )
            return False

    def _get_mailbox_state(self, email: str) -> MailboxState:
        existing = self.state_store.get_mailbox(email)
        if existing:
            return existing
        return self.state_store.upsert_mailbox(MailboxState(email=email))
