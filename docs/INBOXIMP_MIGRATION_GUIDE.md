# Migration Guide: Moving to inboximp.com GCP Organization

This guide walks you through migrating your email triage system from the `email-assistant-475201` GCP project to a new project under your `inboximp.com` cloud organization.

## Overview

You're migrating from:
- **Old Project**: `email-assistant-475201` (standalone project)
- **Old Domain**: `email-triage-*.run.app` (Cloud Run default domain)

To:
- **New Organization**: `inboximp.com`
- **New Project**: To be created (suggested: `inboximp-email-triage`)
- **New Domain**: `inboximp.com` (custom domain with HTTPS)

## Prerequisites

- [ ] Access to Google Cloud Console with Organization Admin role for `inboximp.com`
- [ ] Billing account linked to the `inboximp.com` organization
- [ ] Domain ownership verified for `inboximp.com` in Google Search Console
- [ ] Current working copy of this repository
- [ ] `gcloud` CLI installed and authenticated

---

## Phase 1: Create New GCP Project

### Step 1.1: Create the Project

```bash
# Set your organization ID (find it in Cloud Console > IAM & Admin > Settings)
ORG_ID="984386359065"  # e.g., 123456789012

# Create new project under the organization
gcloud projects create inboximp-email-triage \
  --organization="${ORG_ID}" \
  --name="Inboximp Email Triage"

# Set as active project
gcloud config set project inboximp-email-triage

# Link billing account (replace BILLING_ACCOUNT_ID)
BILLING_ACCOUNT="0194A2-E6CCA8-079AAD"
gcloud billing projects link inboximp-email-triage \
  --billing-account="${BILLING_ACCOUNT}"
```

### Step 1.2: Enable Required APIs

```bash
gcloud services enable \
  gmail.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  iam.googleapis.com
```

**Estimated time**: 5-10 minutes

---

## Phase 2: Configure Gmail API & OAuth

### Step 2.1: Configure OAuth Consent Screen

1. Go to [Google Cloud Console > APIs & Services > OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
2. Select **External** (for personal Gmail) or **Internal** (for Workspace)
3. Fill in the application details:
   - **App name**: Inboximp Email Triage
   - **User support email**: Your email
   - **Authorized domains**: `inboximp.com`
   - **Developer contact**: Your email
4. Click **Save and Continue**
5. Add scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.metadata`
   - `https://www.googleapis.com/auth/gmail.send` (for reply feature)
6. Click **Save and Continue**
7. If using External, add your test users (including all Gmail accounts you'll monitor)
8. Submit for verification if required (for production use)

### Step 2.2: Create OAuth 2.0 Web Client

1. Go to [Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **+ CREATE CREDENTIALS** > **OAuth client ID**
3. Select **Web application**
4. Configure:
   - **Name**: `Email Triage Web Client`
   - **Authorized JavaScript origins**:
     - `https://inboximp.com`
     - `https://www.inboximp.com`
     - `http://localhost:8000` (for local dev)
     - `http://127.0.0.1:8000` (for local dev)
   - **Authorized redirect URIs**:
     - `https://inboximp.com/oauth/callback`
     - `https://www.inboximp.com/oauth/callback`
     - `http://localhost:8000/oauth/callback`
     - `http://127.0.0.1:8000/oauth/callback`
5. Click **Create**
6. Download the JSON file and save it as `json_keys/client_secret_web_new.json`

### Step 2.3: Create OAuth 2.0 Desktop Client (Optional - for CLI)

1. Click **+ CREATE CREDENTIALS** > **OAuth client ID**
2. Select **Desktop app**
3. Name it `Email Triage Desktop Client`
4. Download and save as `json_keys/client_secret_desktop_new.json`

**Estimated time**: 15-20 minutes

---

## Phase 3: Create Service Account

### Step 3.1: Create Service Account for Cloud Run

```bash
# Create service account
gcloud iam service-accounts create email-triage-runner \
  --display-name="Email Triage Cloud Run Service" \
  --description="Service account for running the email triage application"

# Grant necessary roles
PROJECT_ID="inboximp-email-triage"
SA_EMAIL="email-triage-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant Pub/Sub Subscriber role (to receive push notifications)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/pubsub.subscriber"

# Grant Secret Manager Secret Accessor role
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

# Grant Cloud Run Invoker role (for authenticated endpoints)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"
```

### Step 3.2: Create Deployment Service Account

```bash
# Create service account for CI/CD deployments
gcloud iam service-accounts create github-deployer \
  --display-name="GitHub Actions Deployer" \
  --description="Service account for GitHub Actions to deploy Cloud Run"

DEPLOYER_EMAIL="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant deployment roles
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOYER_EMAIL}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOYER_EMAIL}" \
  --role="roles/cloudbuild.builds.editor"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOYER_EMAIL}" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOYER_EMAIL}" \
  --role="roles/storage.admin"

# Create and download key for GitHub Actions
gcloud iam service-accounts keys create github-deployer-key.json \
  --iam-account="${DEPLOYER_EMAIL}"

echo "Save github-deployer-key.json as GitHub Secret GCP_SA_KEY"
```

**Estimated time**: 5 minutes

---

## Phase 4: Set Up Pub/Sub

### Step 4.1: Create Pub/Sub Topic

```bash
PROJECT_ID="inboximp-email-triage"
TOPIC_NAME="email-triage"

# Create topic
gcloud pubsub topics create "${TOPIC_NAME}"

# Grant Gmail permission to publish to this topic
gcloud pubsub topics add-iam-policy-binding "${TOPIC_NAME}" \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Full topic path for config
echo "Topic path: projects/${PROJECT_ID}/topics/${TOPIC_NAME}"
```

### Step 4.2: Create Pub/Sub Subscription (will be updated after Cloud Run deployment)

```bash
# We'll create this after deploying Cloud Run to get the endpoint URL
# For now, just note the topic path above
```

**Estimated time**: 5 minutes

---

## Phase 5: Configure Secrets (Recommended)

### Step 5.1: Create Secrets in Secret Manager

```bash
# OpenRouter API Key
echo -n "YOUR_OPENROUTER_API_KEY" | gcloud secrets create openrouter-api-key --data-file=-

# Supabase credentials
echo -n "YOUR_SUPABASE_URL" | gcloud secrets create supabase-url --data-file=-
echo -n "YOUR_SUPABASE_SERVICE_ROLE_KEY" | gcloud secrets create supabase-service-role-key --data-file=-

# Telegram credentials (optional)
echo -n "YOUR_TELEGRAM_BOT_TOKEN" | gcloud secrets create telegram-bot-token --data-file=-
echo -n "YOUR_TELEGRAM_CHAT_ID" | gcloud secrets create telegram-chat-id --data-file=-

# Google OAuth Client ID (for web UI authentication)
echo -n "YOUR_GOOGLE_CLIENT_ID" | gcloud secrets create google-oauth-client-id --data-file=-

# Gmail OAuth client secret (web client JSON)
gcloud secrets create gmail-client-secret-web --data-file=json_keys/client_secret.json
```

### Step 5.2: Grant Secret Access to Cloud Run Service Account

```bash
PROJECT_ID="inboximp-email-triage"
SA_EMAIL="email-triage-runner@${PROJECT_ID}.iam.gserviceaccount.com"

for SECRET in openrouter-api-key supabase-url supabase-service-role-key \
              telegram-bot-token telegram-chat-id google-oauth-client-id \
              gmail-client-secret-web; do
  gcloud secrets add-iam-policy-binding "${SECRET}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"
done
```

**Estimated time**: 10 minutes

---

## Phase 6: Update Configuration Files

### Step 6.1: Update config.py

```bash
# Edit config.py
nano config.py
```

Update these values:

```python
# OLD:
GMAIL_TOPIC_NAME = "projects/email-assistant-475201/topics/email-triage"

# NEW:
GMAIL_TOPIC_NAME = "projects/inboximp-email-triage/topics/email-triage"

# Update the client secret path to use the new file
GMAIL_CLIENT_SECRET_PATH = "json_keys/client_secret_web_new.json"
```

### Step 6.2: Backup and Replace OAuth Credentials

```bash
# Backup old credentials
mkdir -p backups/old_credentials
cp json_keys/client_secret.json backups/old_credentials/
cp json_keys/client_secret_desktop.json backups/old_credentials/
cp -r .gmail_tokens backups/old_credentials/

# Replace with new credentials
mv json_keys/client_secret_web_new.json json_keys/client_secret.json
mv json_keys/client_secret_desktop_new.json json_keys/client_secret_desktop.json

# Clear old OAuth tokens (will need to re-authenticate)
rm -rf .gmail_tokens/*
```

### Step 6.3: Regenerate Gmail OAuth Tokens

```bash
# For each Gmail account you monitor, run:
python3 bootstrap_gmail_token.py alexsheppert@gmail.com
# Repeat for any other monitored accounts
```

**Estimated time**: 10 minutes

---

## Phase 7: Deploy to Cloud Run

### Step 7.0: Grant Cloud Build Permissions (IMPORTANT - Do This First!)

Before building, grant necessary permissions to avoid multiple build retries:

```bash
PROJECT_ID="inboximp-email-triage"
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")

echo "Project Number: ${PROJECT_NUMBER}"

# Grant all necessary Cloud Build permissions
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/logging.logWriter"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.createOnPushWriter"
```

### Step 7.1: Build and Deploy (Manual)

```bash
PROJECT_ID="inboximp-email-triage"
REGION="us-central1"
SERVICE_NAME="email-triage"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Build the image
gcloud builds submit --tag "${IMAGE}"

# Deploy to Cloud Run with secrets
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --service-account="email-triage-runner@${PROJECT_ID}.iam.gserviceaccount.com" \
  --update-secrets="OPENROUTER_API_KEY=openrouter-api-key:latest,SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest,TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,TELEGRAM_CHAT_ID=telegram-chat-id:latest,GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,/app/client_secret_from_secret.json=gmail-client-secret-web:latest" \
  --set-env-vars="GMAIL_CLIENT_SECRET_PATH=/app/client_secret_from_secret.json"

# Get the service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format="value(status.url)")

echo "Service deployed at: ${SERVICE_URL}"
```

### Step 7.2: Alternative - Deploy Using Script

```bash
python3 deploy_cloud_run.py \
  --key-file github-deployer-key.json \
  --region us-central1 \
  --service email-triage \
  --allow-unauthenticated
```

**Note**: If using secrets, you'll need to modify the deploy script or use the manual method above.

**Estimated time**: 10-15 minutes

---

## Phase 8: Configure Pub/Sub Push Subscription

### Step 8.1: Create Push Subscription

```bash
PROJECT_ID="inboximp-email-triage"
TOPIC_NAME="email-triage"
SUBSCRIPTION_NAME="email-triage-push"

# Get Cloud Run service URL
SERVICE_URL=$(gcloud run services describe email-triage \
  --region=us-central1 \
  --format="value(status.url)")

PUSH_ENDPOINT="${SERVICE_URL}/gmail/push"

# Create subscription
gcloud pubsub subscriptions create "${SUBSCRIPTION_NAME}" \
  --topic="${TOPIC_NAME}" \
  --push-endpoint="${PUSH_ENDPOINT}" \
  --ack-deadline=600

echo "Push subscription created for endpoint: ${PUSH_ENDPOINT}"
```

**Estimated time**: 5 minutes

---

## Phase 9: Set Up Custom Domain (Optional but Recommended)

### Step 9.1: Map Custom Domain to Cloud Run

```bash
# Map domain (this requires domain ownership verification)
gcloud run domain-mappings create \
  --service=email-triage \
  --region=us-central1 \
  --domain=inboximp.com

# For www subdomain
gcloud run domain-mappings create \
  --service=email-triage \
  --region=us-central1 \
  --domain=www.inboximp.com
```

### Step 9.2: Update DNS Records

Follow the instructions from the domain mapping command output to add DNS records to your domain registrar. Typically:

```
Type: CNAME
Name: www (or @)
Value: ghs.googlehosted.com
```

### Step 9.3: Verify Domain in Google Search Console

1. Go to [Google Search Console](https://search.google.com/search-console)
2. Add property for `inboximp.com`
3. Verify ownership using DNS TXT record or HTML file
4. This is **required** for Gmail Push notifications to work with custom domains

**Estimated time**: 20-30 minutes (including DNS propagation)

---

## Phase 10: Register Gmail Watches

### Step 10.1: Trigger Watch Registration

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe email-triage \
  --region=us-central1 \
  --format="value(status.url)")

# Or use custom domain if configured
# SERVICE_URL="https://inboximp.com"

# Register watches for all configured Gmail accounts
curl -X POST "${SERVICE_URL}/gmail/watch"
```

### Step 10.2: Verify in Supabase

Check your Supabase `mailboxes` table to confirm:
- Each Gmail account has a row
- `history_id` is populated
- `watch_expiration` is set (typically ~7 days in the future)

**Estimated time**: 5 minutes

---

## Phase 11: Update GitHub Actions

### Step 11.1: Update Repository Secrets

1. Go to your GitHub repository > Settings > Secrets and variables > Actions
2. Update or create these secrets:
   - **GCP_SA_KEY**: Contents of `github-deployer-key.json`
   - **GCP_PROJECT_ID**: `inboximp-email-triage`

### Step 11.2: Verify Deployment Workflow

```bash
# Commit and push changes to trigger deployment
git add config.py json_keys/
git commit -m "Migrate to inboximp.com GCP organization"
git push origin main

# Monitor GitHub Actions for successful deployment
```

**Estimated time**: 5 minutes

---

## Phase 12: Set Up Cloud Scheduler (Maintenance Jobs)

### Step 12.1: Create Watch Refresh Job

```bash
PROJECT_ID="inboximp-email-triage"
REGION="us-central1"

SERVICE_URL=$(gcloud run services describe email-triage \
  --region="${REGION}" \
  --format="value(status.url)")

# Create scheduler job to refresh watches every 12 hours
gcloud scheduler jobs create http refresh-gmail-watches \
  --location="${REGION}" \
  --schedule="0 */12 * * *" \
  --uri="${SERVICE_URL}/cron/refresh" \
  --http-method=POST \
  --oidc-service-account-email="email-triage-runner@${PROJECT_ID}.iam.gserviceaccount.com"
```

### Step 12.2: Create Daily Digest Job

```bash
# Send daily digest at 5 PM local time
gcloud scheduler jobs create http daily-digest \
  --location="${REGION}" \
  --schedule="0 17 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="${SERVICE_URL}/cron/digest" \
  --http-method=POST \
  --oidc-service-account-email="email-triage-runner@${PROJECT_ID}.iam.gserviceaccount.com"
```

**Estimated time**: 5 minutes

---

## Phase 13: Test End-to-End

### Step 13.1: Test Web UI

1. Open your service URL in a browser (e.g., `https://inboximp.com`)
2. Log in with Google
3. Click "Connect Gmail" to authorize the app
4. Grant all requested permissions
5. Verify you can see your inbox messages

### Step 13.2: Send Test Email

```bash
# Send a test email to one of your monitored Gmail accounts
# Check Cloud Run logs:
gcloud logs read \
  --service=email-triage \
  --region=us-central1 \
  --limit=50 \
  --format=json
```

### Step 13.3: Verify Processing

Check:
- [ ] Email appears in the web UI
- [ ] Cloud Run logs show processing activity
- [ ] Supabase `messages` table has new entry with `status="processed"`
- [ ] Gmail action was applied (archive, label, etc.)
- [ ] Telegram notification sent (if applicable)

### Step 13.4: Test Manual Classification

1. In web UI, view a message
2. Click "Override Classification"
3. Select a category and provide feedback
4. Verify the criterion is added to the prompt

**Estimated time**: 15-20 minutes

---

## Phase 14: Cleanup Old Resources (After Successful Migration)

### Step 14.1: Document Old Resources

```bash
# List old project resources before cleanup
gcloud config set project email-assistant-475201

# List Cloud Run services
gcloud run services list

# List Pub/Sub topics and subscriptions
gcloud pubsub topics list
gcloud pubsub subscriptions list

# Export old configuration (optional backup)
gcloud projects describe email-assistant-475201 > old_project_backup.json
```

### Step 14.2: Delete Old Cloud Run Service (Optional)

```bash
# Once you're confident the new deployment is working
gcloud config set project email-assistant-475201
gcloud run services delete email-triage --region=us-central1
```

### Step 14.3: Delete Old Pub/Sub Resources

```bash
# Delete subscription first
gcloud pubsub subscriptions delete email-triage-push

# Delete topic
gcloud pubsub topics delete email-triage
```

### Step 14.4: Revoke Old OAuth Credentials

1. Go to the old project's [Credentials page](https://console.cloud.google.com/apis/credentials?project=email-assistant-475201)
2. Delete the old OAuth 2.0 clients
3. Revoke any active tokens in your Google Account settings

### Step 14.5: Consider Project Retention

**Option A: Keep old project for reference**
- Disable billing to avoid charges
- Keep project for historical logs/debugging

**Option B: Delete old project entirely**
```bash
gcloud projects delete email-assistant-475201
```

**Estimated time**: 10 minutes (or defer cleanup)

---

## Troubleshooting

### Issue: "Insufficient permissions" errors

**Solution**: Ensure your OAuth consent screen includes all required scopes:
- `gmail.modify`
- `gmail.readonly`
- `gmail.metadata`
- `gmail.send` (if using reply feature)

Re-run `bootstrap_gmail_token.py` to get a fresh token with correct scopes.

### Issue: Push notifications not received

**Checklist**:
- [ ] Domain verified in Google Search Console
- [ ] Pub/Sub topic has `gmail-api-push@system.gserviceaccount.com` as publisher
- [ ] Subscription endpoint matches Cloud Run URL
- [ ] Gmail watch registered (check Supabase `mailboxes` table)
- [ ] Watch not expired (refresh if needed)

### Issue: Cloud Build permission errors (Phase 7)

When running `gcloud builds submit`, you may encounter several permission errors. Grant all necessary permissions upfront:

```bash
PROJECT_ID="inboximp-email-triage"
PROJECT_NUMBER="561574736348"  # Replace with your project number

# Grant Storage Admin (for Cloud Build artifacts)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.admin"

# Grant Logs Writer (for Cloud Build logs)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Grant Artifact Registry Writer (for pushing images)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Grant Create-on-Push Writer (for auto-creating repositories)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.createOnPushWriter"
```

**Common errors and what they mean**:
- `storage.objects.get access denied` → Need `storage.admin` role
- `Permission "artifactregistry.repositories.uploadArtifacts" denied` → Need `artifactregistry.writer` role
- `Creating on push requires the artifactregistry.repositories.createOnPush permission` → Need `artifactregistry.createOnPushWriter` role
- `does not have permission to write logs to Cloud Logging` → Need `logging.logWriter` role

**Pro tip**: Run all four permission commands before your first `gcloud builds submit` to avoid multiple retries.

### Issue: Cloud Run deployment fails

**Common causes**:
- Missing API enablement: Run Step 1.2 again
- Service account lacks permissions: Review Phase 3
- Secrets not accessible: Check Step 5.2
- Cloud Build permissions missing: See "Cloud Build permission errors" above

### Issue: OAuth consent screen verification required

If you see "This app isn't verified" during OAuth:
- For testing: Click "Advanced" > "Go to [app] (unsafe)"
- For production: Submit your app for Google verification (takes 1-2 weeks)

### Issue: Organization policy blocking Gmail push service account (Step 4.1)

**Error message**:
```
ERROR: (gcloud.pubsub.topics.add-iam-policy-binding) FAILED_PRECONDITION:
One or more users named in the policy do not belong to a permitted customer.
- description: User gmail-api-push@system.gserviceaccount.com is not in permitted organization.
  type: constraints/iam.allowedPolicyMemberDomains
```

**Root cause**: Your GCP organization has an `iam.allowedPolicyMemberDomains` constraint that restricts which service accounts can be granted IAM permissions. The Gmail API push service account (`gmail-api-push@system.gserviceaccount.com`) is a Google-owned system service account that's not in your organization's domain.

**Solution**: Delete the project-level policy override to allow the org-level policy to apply:

```bash
# Delete the restrictive project-level policy
gcloud org-policies delete constraints/iam.allowedPolicyMemberDomains \
  --project="${PROJECT_ID}"

# Retry the Pub/Sub IAM binding
gcloud pubsub topics add-iam-policy-binding "${TOPIC_NAME}" \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher" \
  --project="${PROJECT_ID}"
```

**Why this works**: Often, organization-level policies are more permissive for Google system accounts than project-level overrides. Removing the project-level policy allows the parent org policy to apply.

**Alternative (if above doesn't work)**: If you're an organization admin and the org-level policy is also blocking this, you'll need to modify the org-level policy to allow Google system service accounts. Contact your GCP org admin or modify it yourself:

```bash
# Get your organization ID
ORG_ID=$(gcloud projects describe ${PROJECT_ID} --format="value(parent.id)")

# Check current org-level policy
gcloud org-policies describe constraints/iam.allowedPolicyMemberDomains \
  --organization="${ORG_ID}"

# You may need to add an exception at the org level
```

---

## Migration Checklist Summary

### Pre-Migration
- [ ] Create new GCP project under inboximp.com organization
- [ ] Enable all required APIs
- [ ] Configure OAuth consent screen
- [ ] Create OAuth 2.0 credentials (web + desktop)
- [ ] Create service accounts
- [ ] Set up Pub/Sub topic

### Migration
- [ ] Create secrets in Secret Manager
- [ ] Update config.py with new project details
- [ ] Replace OAuth credential files
- [ ] Regenerate Gmail OAuth tokens
- [ ] Deploy to Cloud Run
- [ ] Create Pub/Sub push subscription
- [ ] Set up custom domain (optional)
- [ ] Register Gmail watches
- [ ] Update GitHub Actions secrets

### Post-Migration
- [ ] Set up Cloud Scheduler jobs
- [ ] Test web UI login and Gmail connection
- [ ] Send test email and verify processing
- [ ] Monitor Cloud Run logs for 24-48 hours
- [ ] Clean up old project resources (when confident)

### Validation
- [ ] Web UI accessible and functional
- [ ] OAuth flow works (Connect Gmail button)
- [ ] Push notifications received and processed
- [ ] Manual classification creates criteria
- [ ] Reply functionality works (if used)
- [ ] Telegram notifications sent (if configured)
- [ ] Cloud Scheduler jobs running

---

## Support & References

- **Cloud Run Documentation**: https://cloud.google.com/run/docs
- **Gmail API Push Notifications**: https://developers.google.com/gmail/api/guides/push
- **OAuth 2.0 Setup**: https://developers.google.com/identity/protocols/oauth2
- **Pub/Sub Documentation**: https://cloud.google.com/pubsub/docs

For issues specific to this application, refer to:
- [docs/gmail_setup.md](gmail_setup.md)
- [docs/cloud_run.md](cloud_run.md)
- [AGENTS.md](../AGENTS.md)

---

## Estimated Total Time

- **Hands-on work**: 2-3 hours
- **Waiting for DNS propagation**: 15-60 minutes
- **Testing and validation**: 30-60 minutes
- **Total**: 3-5 hours

## Notes

- The old project used `email-assistant-475201` - all references need to be updated
- Your current OAuth client already has some `inboximp.com` redirect URIs configured, which is good
- You'll need to re-authenticate all Gmail accounts after the migration
- Custom domain setup is optional but recommended for production use
- Consider running both environments in parallel for 1-2 days before decommissioning the old one

Good luck with your migration! 🚀
