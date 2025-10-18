# Cloud Run Deployment Guide

The FastAPI service ships with a `Dockerfile` so you can build and run it on Google Cloud Run. Follow the steps below to containerise the app, publish it, and connect Gmail push notifications.

## 1. Prerequisites
- Google Cloud project with billing enabled.
- Google Cloud SDK (`gcloud`) authenticated against the project.
- Pub/Sub and Cloud Run APIs enabled:
  ```bash
  gcloud services enable run.googleapis.com pubsub.googleapis.com
  ```
- `config.py` populated with:
  - `GMAIL_ACCOUNTS`
  - `GMAIL_TOPIC_NAME` (the Pub/Sub topic path)
  - Supabase URL + service-role key
  - Paths for Gmail OAuth client secret and token directory
- `classification_prompt.txt` reflecting your triage rules.
- OAuth refresh tokens generated with `python3 bootstrap_gmail_token.py <email>`.

## 2. (Optional) Manage secrets via Secret Manager
To avoid baking keys into the container:
1. Store secrets:
   ```bash
   gcloud secrets create openrouter-api-key --data-file=<(printf '%s' "$OPENROUTER_API_KEY")
   gcloud secrets create gmail-client-secret --data-file=client_secret_desktop.json
   gcloud secrets create gmail-token-alex --data-file=.gmail_tokens/token_alexsheppert_at_gmail_com.json
   gcloud secrets create supabase-service-role --data-file=<(printf '%s' "$SUPABASE_SERVICE_ROLE_KEY")
   ```
2. Grant the Cloud Run runtime service account access:
   ```bash
   gcloud secrets add-iam-policy-binding openrouter-api-key \
     --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   # repeat for each secret
   ```
3. During deployment (step 4) use `--update-secrets` to mount them as env vars.

If you skip this, make sure `config.py`, `keys.py`, and `.gmail_tokens/` are safe to package.

## 3. Build & deploy (scripted option)
Run the helper script with your service account key:
```bash
python3 deploy_cloud_run.py \
  --key-file email-assistant-service-key.json \
  --region us-central1 \
  --service email-triage \
  --allow-unauthenticated
```
It activates the service account, sets the project, submits the Cloud Build, and deploys to Cloud Run using the `Dockerfile`. Use `--skip-build` when you only want to redeploy the latest image.

## 4. Build & deploy (manual commands)
If you prefer explicit `gcloud` commands:
```bash
PROJECT_ID=$(gcloud config get-value project)
IMAGE="gcr.io/${PROJECT_ID}/email-triage"
gcloud builds submit --suppress-logs --tag "${IMAGE}"

REGION="us-central1"
SERVICE="email-triage"
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --allow-unauthenticated
```
Add `--update-env-vars` if you need runtime overrides or `--update-secrets` when reading from Secret Manager. Cloud Run will print the base URL (e.g. `https://email-triage-xyz-uc.a.run.app`).

Tip: If your organization uses VPC Service Controls or you see an error about streaming Cloud Build logs to the default logs bucket, include `--suppress-logs` (as shown) to avoid streaming logs while still waiting for the build to complete.

## 5. Pub/Sub push subscription
Create or update the push subscription to target the Cloud Run URL:
```bash
TOPIC="projects/<project-id>/topics/<topic-name>"
SUBSCRIPTION="email-triage-push"
ENDPOINT="https://email-triage-xyz-uc.a.run.app/gmail/push"

gcloud pubsub subscriptions create "${SUBSCRIPTION}" \
  --topic "${TOPIC}" \
  --push-endpoint="${ENDPOINT}"
```

If you want authenticated pushes, add:
```bash
  --push-auth-service-account=email-triage-pubsub@<project-id>.iam.gserviceaccount.com
```
and validate the `Authorization` header inside `app.py`.

Cloud Run provides HTTPS certificates automatically; no domain verification is required for the `*.run.app` domain.

## 6. Register Gmail watches
Once the service is deployed, call:
```bash
curl -X POST "${ENDPOINT%/gmail/push}/gmail/watch"
```
Supabase table `mailboxes` should now contain the Gmail address, current `history_id`, and expiration timestamp. Run this again whenever you add new mailboxes or need to refresh existing watches.

## 7. Validate end-to-end
1. Send a test email to one of the configured inboxes.
2. Check Cloud Run logs (`gcloud logs read --project $PROJECT_ID --service $SERVICE`) for processing traces.
3. Inspect Supabase tables:
   - `mailboxes`: updated `history_id`.
   - `messages`: `status="processed"` (or `error` if something failed).
   - `alerts`: records of Telegram notifications. `status` values include `sent` (alert_immediately) and `queued` (alert_today pending digest).
4. Confirm Gmail action (archive/delete/labels) and Telegram alert (if `action=="alert"`).

## 8. Maintenance tips
- Set up Cloud Scheduler to hit `/gmail/watch` every 12 hours so watches never expire.
- Monitor `/healthz` via Cloud Monitoring for quick diagnostics.
- `/alerts/digest`: sends a grouped Telegram message for all `alert_today` items and marks them as `sent`. Schedule once per day (e.g. 17:00 local).
- When adding new Gmail accounts:
  1. Run `bootstrap_gmail_token.py`.
  2. Update `config.py`.
  3. Redeploy (if config.py is baked into the image) or update Cloud Run env vars.
  4. Call `/gmail/watch`.
- Consider implementing the IMAP IDLE fallback worker once push is stable (see `docs/gmail_setup.md`).

## 9. CI/CD on push (GitHub Actions)
This repo includes `.github/workflows/deploy.yml` which:
- Auths to GCP using `GCP_SA_KEY` (JSON) and `GCP_PROJECT_ID` secrets
- Builds the image with Cloud Build
- Deploys to Cloud Run (`email-triage` in `us-central1` by default)

Setup steps:
1. Push the repo to GitHub.
2. Add repo secrets:
   - `GCP_SA_KEY`: contents of `email-assistant-service-key.json`
   - `GCP_PROJECT_ID`: e.g. `email-assistant-475201`
3. Push to `main`; GitHub Actions will build and deploy automatically.

## 10. One-command E2E verification
Use the included verifier to deploy, wire Pub/Sub, register watches, and run end-to-end checks:
```bash
python3 verify_e2e.py \
  --key-file email-assistant-service-key.json \
  --region us-central1 \
  --service email-triage \
  --subscription email-triage-push \
  --email alexsheppert@gmail.com
```
If Gmail message insertion isn’t permitted with the current OAuth scope, the script will prompt you to manually send a test email before it triggers processing.
