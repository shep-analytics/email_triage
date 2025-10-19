Email Triage Service — Agent Guide and Repo Map

Overview
- Purpose: Classify and triage incoming Gmail messages using an LLM, apply Gmail actions (archive/delete/label), and notify via Telegram only when useful. Persists state to Supabase. Ships a small web console for batch cleanup and prompt tuning.
- Core flow: Gmail Push (Pub/Sub) -> FastAPI webhook -> GmailProcessor -> LLM (OpenRouter) -> Gmail API actions -> Telegram alerts -> State in Supabase.

Architecture
- Entrypoint `app.py`: FastAPI app exposing endpoints for Gmail push, watch registration, batch cleanup, prompt criteria CRUD, daily digest, and a health check. Serves a minimal web UI from `static/` secured by Google Identity ID tokens.
- Gmail API client `gmail_watch.py`: Builds service via OAuth token or service-account delegation; starts watches; fetches history; parses Pub/Sub payloads.
- Processor `gmail_processor.py`: Orchestrates history processing, calls the LLM, applies Gmail modifications, logs decisions to Supabase (or in-memory fallback), and sends Telegram alerts/digests.
- Prompting `classification_prompt.txt` + `prompt_manager.py`: Base system prompt plus persisted user “criteria” refinements editable via the web UI/API.
- State `supabase_state.py`: Writes/reads mailbox checkpoints, message decisions, and alert rows via Supabase REST; includes `NullStateStore` fallback if Supabase is not configured.
- Notifications `telegram_notify.py`: Thin Telegram Bot API wrapper with optional interactive callback support.
- LLM client `query_LLM.py`: Single-turn request to OpenRouter. Expects strict JSON from models. Requires OpenRouter API key. Default model: `openai/gpt-5` (override via `OPENROUTER_MODEL`).
- Web UI `static/`: Login (GIS), run batch cleanup, view summaries, and submit feedback that creates criteria.
- Web UI `static/`: Login (GIS), run batch cleanup, view summaries, browse messages (Inbox, Requires Response, Should Read), view full email text, reply, archive, and delete.

Configuration
- Preferred configuration lives in `config.py`. Environment variables of the same names always override. Optional `keys.py` can provide `telegram_token`, `telegram_chat_id`, and `OPENROUTER_API_Key`. It also supports `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (the app will read these if not set in env/config), plus optional `GOOGLE_OAUTH_CLIENT_ID` and deploy helpers like `GCP_PROJECT_ID` and `GCP_SERVICE_ACCOUNT_KEY_FILE`.
- Important settings (via `config.py` or env):
  - `GMAIL_ACCOUNTS`: Comma-separated list of mailboxes to watch/clean.
  - `GMAIL_CLIENT_SECRET_PATH`: OAuth client JSON (desktop/web). Env alias: `GMAIL_OAUTH_CLIENT_SECRET`.
  - `GMAIL_OAUTH_TOKEN_DIR`: Directory with per-account token JSON files (default: `.gmail_tokens`).
  - `GMAIL_SERVICE_ACCOUNT_FILE`/`GMAIL_DELEGATED_USER`: Alternative auth using domain-wide delegation.
  - `GMAIL_TOPIC_NAME`: Pub/Sub topic for Gmail push.
  - `CLASSIFICATION_PROMPT_PATH`: Path to base prompt.
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (required for real persistence; otherwise uses in-memory fallback).
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` for alerts and batch confirmations.
  - `ALLOWED_LOGIN_EMAILS`, `GOOGLE_OAUTH_CLIENT_ID` for the web console’s GIS login.
- Optional runtime toggles:
  - `GMAIL_ALLOW_OAUTH_FLOW=1`: Permit interactive OAuth token flow if token missing/invalid.
  - `GMAIL_AUTO_REAUTH=1`: Attempt one interactive reauth on insufficient-scope errors.
  - `GMAIL_EXTRA_SCOPES`: Comma-separated list appended to default scopes.
  - `DISABLE_TELEGRAM=1`: Global kill-switch to disable all Telegram sends.
  - `OPENROUTER_MODEL`: Override the default LLM model (default is `openai/gpt-5`).
  - Note: UI reply requires Gmail scope `gmail.send`. Tokens minted before this change may need re‑consent; set `GMAIL_AUTO_REAUTH=1` and temporarily `GMAIL_ALLOW_OAUTH_FLOW=1` to refresh locally.

**Hands-Off Deployment (Zero-Input)**
- Goal: allow the agent to build/deploy, wire Pub/Sub + Gmail watches, persist to Supabase, and run digests without human steps.
- Provide these items (commit to repo or pass via env/Secrets as you prefer):
  - `json_keys/owner_google_service_account_key.json` with project-level deploy rights (already added).
  - Supabase: configured via `keys.py`.
  - LLM: configured via `keys.py`.
  - Gmail auth path (choose one):
    - OAuth tokens per mailbox under `.gmail_tokens/` plus `json_keys/client_secret_desktop.json` (works for consumer Gmail), or
    - Service Account with Domain‑Wide Delegation + delegated user email(s) (Workspace only).
  - Telegram: configured via `keys.py` (optional).
  - Web UI auth: `GOOGLE_OAUTH_CLIENT_ID` in `keys.py`; allowed emails in `config.py` (`ALLOWED_LOGIN_EMAILS`).

**Secrets**
- All required secrets are already present in `keys.py` (Supabase, Telegram, OpenRouter, GCP project details, and Google OAuth Client ID). Update that file if values change.
- Gmail auth is configured via `config.py` and local tokens/service account. See `docs/gmail_setup.md` only if you are adding new mailboxes or changing auth mode.

**Zero-Input Deploy Steps**
- Ensure `config.py` has:
  - `GMAIL_ACCOUNTS` populated and `GMAIL_TOPIC_NAME` set (e.g., `projects/<project>/topics/email-triage`).
  - Supabase URL/key present (or environment variables configured at deploy).
  - Gmail auth method configured (OAuth tokens or DWD SA).
- Build + deploy to Cloud Run using the owner key:
  - `python3 deploy_cloud_run.py --key-file json_keys/owner_google_service_account_key.json --region us-central1 --service email-triage --allow-unauthenticated`
- Wire Pub/Sub and verify end‑to‑end automatically:
  - `python3 verify_e2e.py --key-file json_keys/owner_google_service_account_key.json --region us-central1 --service email-triage --subscription email-triage-push --email <one_of_GMAIL_ACCOUNTS>`
  - The script grants the Gmail publisher to the topic, (create|update)s the push subscription to `<RUN_URL>/gmail/push`, calls `/gmail/watch`, and runs a dry‑run classification.
- Scheduler jobs (auto‑created by the verifier if allowed):
  - Refresh watches: POST `/gmail/watch` every 12h.
  - Daily digest: POST `/alerts/digest` at your chosen time.
- if anything you change needs to be done

Notes
- It is acceptable in this project to commit keys and tokens to the repo for speed of iteration. Do not delete committed keys.
- If you prefer secret managers, use Cloud Run `--set-env-vars` or Secret Manager bindings; the deploy scripts already support that pattern.

Endpoints (FastAPI)
- `GET /` — Serves `static/index.html` UI.
- `GET /api/config` — Client config for UI (Google client id, allowed emails, criteria count).
- `POST /api/cleanup/run` — Runs one cleanup batch on the authenticated user’s mailbox (overridable in body). Requires GIS ID token in `Authorization: Bearer <token>`.
- `POST /api/cleanup/start` — Starts a live cleanup job (single batch, Telegram disabled). Returns `{ job_id }`.
- `GET /api/cleanup/events/{job_id}?token=<ID_TOKEN>` — Server‑Sent Events stream of progress logs and results for that job.
- `POST /api/cleanup/cancel` — Cancels a running cleanup job `{ job_id }`.
- `POST /api/cleanup/feedback` — Applies a manual cleanup decision to a Gmail message and appends a human-readable “criterion” to the prompt.
- `GET /api/criteria` — List prompt criteria.
- `POST /api/criteria` — Create criterion.
- `PATCH /api/criteria/{id}` — Update text and/or enabled flag.
- `DELETE /api/criteria/{id}` — Delete criterion.
- `POST /dry-run` — Non-auth test: classify a synthetic email via LLM; does not modify Gmail.
- `POST /gmail/push` — Pub/Sub push webhook for Gmail notifications (expects Pub/Sub envelope with base64 `data`).
- `POST /gmail/watch` — Registers or refreshes Gmail watches for all configured accounts (needs `GMAIL_TOPIC_NAME`).
- `POST /gmail/cleanup` — Programmatic cleanup (used by `run_cleanup.py`).
- `GET /health` or `GET /healthz` — Health information (mailbox watch/checkpoint state, telegram, and store mode).
- `POST /alerts/digest` — Sends grouped Telegram digests for queued “alert_today” items.
- `POST /cron/refresh`, `POST /cron/digest` — Unauthenticated cron-friendly aliases.
- `GET /api/messages?label=<inbox|requires_response|should_read|all>&max_results=<n>&page_token=<t>` — List recent messages for the logged-in mailbox.
- `GET /api/messages/{gmail_id}` — Fetch full message headers + text/html bodies.
- `POST /api/messages/{gmail_id}/reply` — Send a reply in the same thread. Body: `{ body_text, to?, subject?, mailbox_email? }`.
- `POST /api/messages/{gmail_id}/archive` — Remove `INBOX` label (archives). Body: `{ mailbox_email? }`.
- `POST /api/messages/{gmail_id}/delete` — Delete the message. Body: `{ mailbox_email? }`.

Data Model (Supabase tables)
- `mailboxes(email, history_id, watch_expiration)` — One row per mailbox.
- `messages(gmail_id, mailbox_email, decision_json, processed_at, state)` — Decision/audit log.
- `alerts(gmail_id, mailbox_email, summary, status, error_detail)` — Alert send/queue state.
- If Supabase isn’t configured, decisions/alerts are kept in-memory by `NullStateStore`.

Local Development — Quickstart
1) Python 3.11+, `pip install -r requirements.txt`.
2) LLM: export `OPENROUTER_API_KEY=...` or create `keys.py` with `OPENROUTER_API_Key = "..."`.
3) Telegram (optional but recommended): set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (or put in `keys.py`).
4) Gmail OAuth token(s):
   - Place a client secret JSON at repo root (e.g., `client_secret_desktop.json`).
   - For each mailbox: `python3 bootstrap_gmail_token.py you@example.com` → saves `.gmail_tokens/token_you_at_example_com.json`.
5) Supabase: set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` for persistence; otherwise fallback store is used.
6) Web console auth: set `GOOGLE_OAUTH_CLIENT_ID` and `ALLOWED_LOGIN_EMAILS` (or list in `config.py`).
7) Run locally: `uvicorn app:app --reload` and open `http://localhost:8000/`.

Operational Notes
- Watches expire ~24h; call `/gmail/watch` periodically (Cloud Scheduler or cron). `/cron/refresh` is provided.
- Pub/Sub topic must grant `serviceAccount:gmail-api-push@system.gserviceaccount.com` `roles/pubsub.publisher`.
- Gmail scopes used: `gmail.modify`, `gmail.readonly`, `gmail.metadata` (plus `GMAIL_EXTRA_SCOPES` if set). Token scope mismatches can require reauth.
- Telegram digests: `/alerts/digest` groups queued “alert_today” items per mailbox; schedule daily (e.g., 17:00 local).

LLM Prompting
- Classification prompt: `classification_prompt.txt` — used for general alert/archive/delete decisions.
- Cleanup prompt: generated in `gmail_processor.py` with strict JSON schema and guardrails; optionally appends user “criteria” from `prompt_manager.json` to steer outcomes.
- `query_LLM.query_llm(prompt)` sends the prompt verbatim; models must return JSON-only output. Parser tolerates accidental code fences for cleanup classification.

Security & Secrets
- It is okay to commit keys in this project. DO NOT DELETE KEYS. There is no problem with having keys in the github right now. The way this system is developing there is no risk. You should as the agent have full authority to edit and change supabase, deploy on google cloud, etc.

Deployment
- Docker: `Dockerfile` builds the app and launches `uvicorn` on port 8080.
- Cloud Run: See `docs/cloud_run.md` or use `deploy_cloud_run.py` for scripted deploys; `ship_and_deploy.py` can git add/commit/push then deploy.
- GitHub Actions: `.github/workflows/deploy.yml` builds with Cloud Build and deploys to Cloud Run on pushes to `main` (requires repo secrets `GCP_SA_KEY`, `GCP_PROJECT_ID`).
- End-to-end validator: `verify_e2e.py` can build/deploy, wire Pub/Sub, register watches, inject a test message (when permitted), trigger processing, query Supabase, and send a digest.

Batch Cleanup & Feedback Loop
- UI calls `POST /api/cleanup/run` to process the next batch (default 50). Processor classifies each message into one of:
  - `spam` → delete
  - `receipt` → archive + label “Receipts”
  - `useful_archive` → archive + inferred/provided label
  - `requires_response` → keep in inbox + label “Requiring Response”
  - `should_read` → keep in inbox + label “User Should Read”
- User feedback in UI calls `POST /api/cleanup/feedback` which both applies the requested action and adds a natural-language “criterion” to guide future classifications.

File-by-File Map
- `app.py` — FastAPI app: endpoints, GIS ID-token auth, static file serving, and shared singletons (processor, prompt manager, state store).
- `bootstrap_gmail_token.py` — CLI: interactive OAuth flow to write `.gmail_tokens/token_<email>.json` per mailbox.
- `classification_prompt.txt` — Base JSON-only classification prompt for the LLM.
- `config.py` — Central configuration (preferred over env). All values can be overridden via environment variables.
- `deploy_cloud_run.py` — Scripted Cloud Run build/deploy with async Cloud Build and env var support.
- `Dockerfile` — Container image for Cloud Run (ports 8080).
- `.dockerignore`, `.gcloudignore`, `.gitignore` — Ignore rules for builds/commits; ensure secrets and local envs aren’t uploaded.
- `docs/cloud_run.md` — Step-by-step Cloud Run deploy guide.
- `docs/gmail_setup.md` — Gmail push/IMAP fallback + Supabase schema notes and cookbook.
- `gmail_processor.py` — Core orchestration: history fetch, classification, Gmail actions, Telegram alerts, decision logging; manual override support.
- `gmail_watch.py` — Gmail client builder (OAuth or DWD), watch registration, history fetch, Pub/Sub decoding, and retry helper.
- `.gmail_tokens/` — Per-account OAuth token JSONs. Sensitive; excluded by `.gitignore`.
- `json_keys/` — Local client secret JSONs. Sensitive; do not commit publicly.
- `project_recs.txt` — Project goals and operational notes used to bootstrap the implementation.
- `prompt_manager.py` — Stores and renders user prompt criteria (`prompt_criteria.json` beside `classification_prompt.txt`).
- `query_LLM.py` — OpenRouter HTTP client; reads API key from `OPENROUTER_API_KEY` or `keys.py`.
- `requirements.txt` — Python dependencies.
- `run_cleanup.py` — One-shot CLI to process inbox batches with optional Telegram confirmations.
- `ship_and_deploy.py` — Git add/commit/push plus Cloud Run deploy in one command.
- `static/index.html`, `static/app.js`, `static/styles.css` — Web console for login, batch cleanup, and feedback/criteria management.
- `supabase_state.py` — Supabase REST store and in-memory fallback; logs messages, alerts, and mailbox checkpoints.
- `telegram_notify.py` — Telegram Bot API helpers: send message, get updates, handle callback queries, and wait for selection.
- `.github/workflows/deploy.yml` — CI/CD pipeline to Cloud Run on push to `main`.
- `verify_e2e.py` — End-to-end deploy + validation helper with Pub/Sub and Supabase checks.

What Future Agents Should Know
- Keep prompts JSON-only; parsers assume strict JSON (cleanup parser tolerates fenced blocks). Avoid adding extra prose around JSON in LLM outputs.
- Respect existing naming and file layout; avoid renames unless necessary. Be surgical with changes.
- Do not log secrets, tokens, or raw ID tokens. The UI sends Google ID tokens; server validates against `GOOGLE_OAUTH_CLIENT_ID`.
- Gmail scopes: Changing scopes requires a new consent/token; prefer adding via `GMAIL_EXTRA_SCOPES` when unavoidable.
- If adding features that persist data, extend Supabase tables and update both `SupabaseStateStore` and the docs.
- For tests and local validation, prefer using `verify_e2e.py` or dry runs. Avoid writing broad integration tests that call external APIs unless feature work requires it.
- please update this file AGENTS.md after all calls if anything has changed. This file AGENTS.md should remain up to date, anything changed should be reflected in this file and this file should remain up to date.

Commit/Push + Verify Policy
- After every change you make to files in this repo, you must: (1) commit, (2) push, and (3) run end-to-end verification.
- Steps to follow each time:
  - Stage changes: `git add -A` (do not delete committed keys; committing keys in this repo is acceptable per project policy).
  - Commit: `git commit -m "agent: <brief summary of change>"`.
  - Push: `git push origin main`.
- Verify: run `python3 verify_e2e.py --key-file json_keys/owner_google_service_account_key.json --region us-central1 --service email-triage --subscription email-triage-push --email <one_of_GMAIL_ACCOUNTS>`.
- If verification fails due to transient issues, rerun once. If it still fails, surface the error, do not roll back, and add a note to the Updates section.
- Always update this AGENTS.md if the workflow, commands, or assumptions change.
  - Note on push protection: if GitHub blocks the push due to detected secrets (e.g., Google service-account JSON), do not include that file in the commit. Keep it locally under `json_keys/` and pass it via `--key-file` or configure via CI secrets. Never delete already-committed keys from history in this project.

Common Pitfalls
- 403 insufficientPermissions from Gmail: scope mismatch with stored token; set `GMAIL_AUTO_REAUTH=1` and revisit consent locally with `GMAIL_ALLOW_OAUTH_FLOW=1`.
- Pub/Sub push rejected: Topic missing Gmail publisher role or webhook unauthenticated/incorrect URL.
- UI login blocked: `GOOGLE_OAUTH_CLIENT_ID` missing or `ALLOWED_LOGIN_EMAILS` not set to your account.
- Missing digests: No queued alerts (`alert_today`); or Telegram not configured.

Runbooks — Handy Commands
- Bootstrap OAuth token: `python3 bootstrap_gmail_token.py you@example.com`
- Local API: `uvicorn app:app --reload`
- Start/refresh watches: `curl -X POST http://localhost:8000/gmail/watch`
- Dry-run LLM: `curl -X POST http://localhost:8000/dry-run -H 'Content-Type: application/json' -d '{"sender":"x@y","to":"me@y","subject":"Hi","snippet":"..."}'`
- One-shot cleanup: `python3 run_cleanup.py you@example.com --batch-size 50`

Updates
- 2025-10-18: CI deploy via script. GitHub Actions now runs `verify_e2e.py` on every push to `main` using a service account key from repo secret `GCP_SA_KEY`. The previous workflow steps that directly invoked `gcloud builds submit` and `gcloud run deploy` were removed. The script performs build, deploy, Pub/Sub wiring, health checks, and scheduler setup. If you previously configured Cloud Build Triggers or Cloud Run continuous deployment, disable them to avoid duplicate build emails.
- 2025-10-18: Agent workflow — enforce commit/push/verify after every change. Added explicit steps and command line to AGENTS.md.
- 2025-10-18: Frontend error handling improved. The web console now normalizes FastAPI error payloads (including 422 validation arrays and nested objects) into readable messages, so users will no longer see "[object Object]" after pressing "Process next batch". No backend contract changes required.
- 2025-10-18: Batch cleanup safety + UX. The `/api/cleanup/run` endpoint now processes exactly one batch (one Gmail page) and suppresses Telegram notifications by default. This prevents long-running cleanups from the UI and avoids Telegram spam. The processor also fails fast if a batch is 100% errors (stops further batches), reducing API credit burn when misconfigured.
  - `DISABLE_TELEGRAM` env toggle added as a global kill-switch.
  - Default OpenRouter model set to `openai/gpt-5`. Override via env `OPENROUTER_MODEL` if needed.
- 2025-10-18: Live cleanup + cancel. Added streaming cleanup with SSE and a UI log:
  - New endpoints: `/api/cleanup/start`, `/api/cleanup/events/{job_id}`, `/api/cleanup/cancel`.
  - UI shows live per‑message updates and running counts, plus a Stop button.
  - Streaming uses a query param `token=<ID_TOKEN>` for GIS auth on EventSource.
  - UI cleanup still processes exactly one batch per run and suppresses Telegram.
  - Inlined SVG favicon to eliminate `/favicon.ico` 404.
- 2025-10-18: E2E verify/deploy. Ran `verify_e2e.py` which rebuilt/deployed to Cloud Run, ensured Pub/Sub topic + push subscription, refreshed Gmail watches, and installed Cloud Scheduler jobs. Current resolved service URL: `https://email-triage-rq4d232cbq-uc.a.run.app` (the previous regional URL also routes). Push subscription `email-triage-push` now targets `<RUN_URL>/gmail/push`.
- 2025-10-18: Email viewer + replies. Added UI to browse Inbox/Requires Response/Should Read, view full message text, reply inline, and archive/delete. New API endpoints under `/api/messages/*`. Gmail scope `gmail.send` added; tokens may need reauth if previously minted without it.
- 2025-10-18: Deployed viewer/reply changes to Cloud Run via verify script; push subscription updated to new service URL. E2E passed.
- 2025-10-19: Viewer UX unified + pagination. The email viewer now includes the same per‑email feedback controls as cleanup (Desired action, optional label, and comment) on every message card. Archive/Delete no longer prompt; actions apply immediately and remove the card. Viewer loads 10 messages at a time with a Load more button (prevents overload). Frontend always sends the Google ID token on these calls. Backend `/api/messages` adds clearer errors for Gmail scope/permission issues (403 with guidance) instead of opaque 500s.
- 2025-10-19: Gmail scopes — safer defaults. The default Gmail scope set no longer includes `gmail.send`. Read/list/modify paths (`/api/messages`, cleanup, watch, archive/delete) use `gmail.modify`, `gmail.readonly`, and `gmail.metadata` only. The reply endpoint (`/api/messages/{id}/reply`) now requests `gmail.send` explicitly. This avoids `invalid_scope` errors for service accounts that have not been authorized for send. If you use replies, ensure:
  - OAuth tokens are re-consented to include `gmail.send` (set `GMAIL_AUTO_REAUTH=1` and `GMAIL_ALLOW_OAUTH_FLOW=1` locally, then redeploy tokens), or
  - For Domain‑Wide Delegation, authorize the service account for `https://www.googleapis.com/auth/gmail.send` in Admin Console.
  - API now returns 403 with guidance for `invalid_scope`/`insufficientPermissions` instead of 500s across viewer/reply/archive/delete.
  - Files touched: `static/app.js`, `static/index.html`, `app.py`.
  - Deployed via `verify_e2e.py`; Cloud Run updated and Pub/Sub push verified.

Behavioral Notes
- UI batch runs: one batch only, no Telegram. Call again to process the next batch.
- Programmatic cleanup `/gmail/cleanup`: unchanged defaults. Use `await_user_confirmation=true` to require Telegram “Continue/Stop” between batches, or `false` to auto-continue. It still sends Telegram batch summaries unless you override by passing `telegram_token`/`telegram_chat_id` as null values and set `notify_via_telegram=False` in code usage.
- Fail-fast: If a batch has only errors, cleanup stops early and returns `stopped_early: true`.
