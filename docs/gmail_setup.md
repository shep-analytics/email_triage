# Gmail Push + IMAP Fallback Checklist

## Prerequisites
- Google Cloud project dedicated to this automation.
- Gmail account(s) the app will monitor (workspace or consumer).
- HTTPS endpoint you control (Cloud Run, FastAPI, etc.) for Pub/Sub push delivery.
- Update `config.py` with your Gmail accounts, Pub/Sub topic, Supabase URL/key, and token directory paths so the service can run without environment variables.

## Google Cloud Setup
1. **Enable APIs**: `gmail.googleapis.com`, `pubsub.googleapis.com`, optionally `cloudfunctions.googleapis.com` or `run.googleapis.com` for hosting the webhook.
2. **OAuth consent screen**: configure External (for personal Gmail) or Internal (workspace). Add Gmail scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.readonly` (optional but useful for dry-runs)
   - `https://www.googleapis.com/auth/gmail.metadata`
   - Optional (only if you plan to use the Reply feature): `https://www.googleapis.com/auth/gmail.send`
3. **Credentials**:
   - For personal accounts, create an OAuth client (`Desktop` or `Web` app). Save `client_secret.json`.
   - For Google Workspace, you may instead create a service account and enable domain-wide delegation. Remember to authorize the Gmail scopes in the Admin console and specify the user email when calling `build_gmail_service(..., delegated_user="user@domain.com")`. If using the Reply feature, also authorize `gmail.send` for the service account.
4. **Pub/Sub topic**: `projects/<project-id>/topics/email-triage`. Grant `serviceAccount:gmail-api-push@system.gserviceaccount.com` the `Pub/Sub Publisher` role on the topic.
5. **Pub/Sub subscription**:
   - Use push delivery to your webhook (`https://your-domain.example.com/gmail/push`).
   - Include an auth header (OIDC or custom) that your app can validate.
   - Record the subscription name; you will acknowledge messages there after successful processing.
6. **Verify domain (required for push)**: add a DNS TXT record for your webhook domain in Google Search Console so Gmail accepts the HTTPS endpoint.

## Local Token Bootstrap (OAuth path)
Run once per mailbox to capture a long-lived refresh token:
```bash
pip install -r requirements.txt
python3 bootstrap_gmail_token.py you@example.com
```
The script auto-detects `client_secret.json`, `client_secret_desktop.json`, or `client_secret_web.json`, opens a browser for consent, and saves the token under `.gmail_tokens/token_you_at_example_com.json`. Use `--token-dir` or `--client-secret` to override paths.
Store the resulting JSON securely (Supabase, vaulted secret). You can reuse it on servers to build the Gmail client without repeating the browser consent step.

## Registering the Watch
```python
from gmail_watch import build_gmail_service, GmailAccount, start_watch

service = build_gmail_service(
    oauth_client_secret="client_secret.json",
    oauth_token_file="token_me.json",
)
account = GmailAccount(
    user_id="me",
    topic_name="projects/<project-id>/topics/email-triage",
    label_ids=["INBOX"],
)
watch = start_watch(service, account)
print("History ID:", watch["historyId"])
print("Expires:", watch["expiration"])
```
Persist `historyId` per mailbox (Supabase table `mailboxes.history_id`). Gmail expects you to replay history from that value after every push.

## Pub/Sub Push Handler Skeleton
```python
# pseudo FastAPI route
from fastapi import APIRouter, Request, Response
from gmail_watch import parse_gmail_push_data, fetch_history, get_message_metadata, build_gmail_service

router = APIRouter()

@router.post("/gmail/push")
async def gmail_push(request: Request):
    envelope = await request.json()
    notification = parse_gmail_push_data(envelope.get("message", {}))
    if not notification:
        return Response(status_code=204)

    email_address = notification["emailAddress"]
    history_id = notification["historyId"]

    # Load per-mailbox history checkpoint from Supabase
    last_history_id = await load_history_id(email_address)
    service = build_gmail_service( ... )  # reuse cached credentials
    history = fetch_history(
        service,
        user_id=email_address,
        start_history_id=last_history_id or history_id,
        history_types=["messageAdded"],
    )

    for record in history.get("history", []):
        for message in record.get("messagesAdded", []):
            msg = message["message"]
            metadata = get_message_metadata(service, email_address, msg["id"])
            # feed into OpenRouter classifier + Gmail action pipeline

    await store_history_id(email_address, history["historyId"])
    return Response(status_code=204)
```
Remember to ack the Pub/Sub delivery once processing succeeds (`subscriber.acknowledge` if you pull; for push, Pub/Sub auto-acks on 2xx responses).

## Renewal Policy
- Watches expire in ~24 hours; keep a cron/Cloud Scheduler job that calls `start_watch` again before expiration.
- After renewals, update `historyId` only if the API response gives a newer one.

## IMAP IDLE Fallback
- Use `imapclient` or `imaplib` with OAuth 2.0 SASL tokens.
- Maintain a lightweight worker per mailbox:
  1. Connect via IMAP over SSL (`imap.gmail.com:993`).
  2. Authenticate with `XOAUTH2`.
  3. Issue `IDLE` and wait for mailbox change events.
  4. When notified, run the same classifier pipeline against the new Gmail message IDs (you can fetch via REST to stay consistent).
- Reconnect at least every 15 minutes, handle `BYE` gracefully, and backoff on rate limits.

## Supabase Storage Checklist
- Table `mailboxes`: `email`, `history_id`, `watch_expiration`, `token_secret_path`.
- Table `messages`: `gmail_id`, `mailbox_email`, `decision_json`, `processed_at`, `state`.
- Table `alerts`: `message_id`, `sent_to_telegram_at`, `status`, `error_detail`.
- Use a service role key for backend writes; RLS off by default unless you expose dashboards.

## Operational Endpoints
- `/healthz`: include Gmail watch age, Pub/Sub subscription ack backlog, IMAP connection state, Telegram notifier status.
- `/dry-run`: accept an RFC 822 message source or Gmail message ID, run classification, and return the proposed action without modifying Gmail.

With these components in place you can feed Gmail updates into the triage classifier, guarantee reliability with IMAP fallback, and maintain state in Supabase for auditing and retries.

## Repository Components
- `app.py`: FastAPI service exposing `/gmail/push`, `/gmail/watch`, `/dry-run`, and `/healthz`. Configure with `GMAIL_ACCOUNTS`, `GMAIL_TOPIC_NAME`, Gmail credentials, Supabase URL/key, and Telegram secrets (already in `keys.py`).
- `gmail_processor.py`: Processes Pub/Sub notifications, classifies new mail with OpenRouter, applies Gmail actions, and triggers Telegram alerts.
- `gmail_watch.py`: Utilities for building Gmail API clients, starting watches, fetching history, and parsing Pub/Sub payloads.
- `supabase_state.py`: Supabase REST helper plus an in-memory fallback (`NullStateStore`) if Supabase isn’t ready yet.
- `classification_prompt.txt`: Prompt template that forces JSON decisions from the LLM; adjust the criteria here.
- `telegram_notify.py`: Bot sender used by the processor for alert-worthy emails.
- `config.py`: Central place to list Gmail accounts, Supabase credentials, and other settings (preferred over environment variables).

Install dependencies with `pip install -r requirements.txt`, then launch the API (`uvicorn app:app --reload`) once environment variables and tokens are in place.
