# OAuth Consent Screen Scope Issue - Fix Guide

## The Problem

Google is granting your token with all three scopes:
- ✓ `gmail.modify`
- ✓ `gmail.readonly`
- ✓ `gmail.metadata`

But when you try to use the token, **Google only recognizes `gmail.metadata`** and blocks the others.

**Error from Google:** `"Metadata scope doesn't allow format FULL"`

This means Google's OAuth system granted the scopes but their Gmail API is refusing to honor them.

## Root Cause

This happens when:
1. The OAuth Consent Screen doesn't have the scopes properly configured
2. The app is in "Testing" mode but the scopes aren't explicitly added
3. There's a mismatch between requested scopes and configured scopes

## The Fix

### Step 1: Check OAuth Consent Screen Scopes

1. Go to: https://console.cloud.google.com/apis/credentials/consent?project=inboximp-email-triage

2. Scroll down to **"Scopes"** section

3. Click **"Edit App"** or **"Add or Remove Scopes"**

4. **CRITICAL:** You MUST explicitly add these scopes:

   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.metadata`

5. Search for "Gmail API" in the scope picker

6. Check the boxes for:
   - **"View your email messages and settings"** (gmail.readonly)
   - **"Read, compose, and send emails from your Gmail account"** (gmail.modify)
   - **"View your email message metadata"** (gmail.metadata)

7. Click **"Update"** and **"Save and Continue"**

### Step 2: Verify Test Users

1. Still in OAuth Consent Screen page

2. Go to **"Test users"** section

3. Confirm `alexsheppert@gmail.com` is listed

4. If not, click **"Add Users"** and add it

### Step 3: Clear Old Authorizations

1. Go to: https://myaccount.google.com/permissions

2. Find **"Inboximp Email Triage"** or your app name

3. Click on it → **"Remove access"**

4. Confirm removal

### Step 4: Re-authorize with Fresh Consent

1. Go to http://localhost:8000

2. Sign in with your Google account

3. Click **"Connect Gmail"**

4. You should see the consent screen showing:
   - ✓ "View your email messages and settings"
   - ✓ "Read, compose, and send emails"
   - ✓ "View your email message metadata"

5. Click **"Continue"** and authorize

### Step 5: Test

1. Navigate to your inbox in the app

2. Click **"View"** on any email

3. You should now see the **full email content**!

## Alternative: Check Scope Configuration via gcloud

Run this command to see your OAuth consent screen configuration:

```bash
gcloud alpha iap oauth-brands list --project=inboximp-email-triage
```

## If Still Not Working

### Option A: Create a Fresh OAuth Client

Sometimes the OAuth client itself gets "stuck" with old scope permissions:

1. Go to: https://console.cloud.google.com/apis/credentials?project=inboximp-email-triage

2. Create a **NEW** OAuth 2.0 Client ID
   - Application type: **Web application**
   - Name: `gmail-web-client-v2`
   - Authorized redirect URIs:
     - `http://localhost:8000/oauth/callback`
     - `http://127.0.0.1:8000/oauth/callback`
     - `https://inboximp.com/oauth/callback`
     - `https://www.inboximp.com/oauth/callback`

3. Download the client secret JSON

4. Replace the file at: `json_keys/client_secret.json`

5. Restart your localhost server

6. Try the OAuth flow again

### Option B: Publish the OAuth Consent Screen

If you keep having issues in Testing mode:

1. Go to OAuth Consent Screen

2. Click **"Publish App"**

3. Note: For restricted scopes (Gmail), you may see a warning that verification is required

4. You can still use it with test users while verification is pending

5. For full public access, you'll need to complete Google's verification process

### Option C: Use Service Account (Workspace Only)

If you have Google Workspace and admin access:

1. Create a Service Account with Domain-Wide Delegation

2. In Workspace Admin, authorize these scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.readonly`

3. Set in config:
   ```python
   GMAIL_SERVICE_ACCOUNT_FILE = "path/to/service-account-key.json"
   GMAIL_DELEGATED_USER = "alexsheppert@gmail.com"
   ```

4. This bypasses OAuth consent entirely

## Debug: Check What Scopes Are Actually Configured

You can check what scopes your OAuth client is configured with:

1. Go to: https://console.cloud.google.com/apis/credentials?project=inboximp-email-triage

2. Click on your OAuth 2.0 Client ID

3. Check if it shows any scope restrictions

4. If there are restrictions, remove them

## Common Mistakes

❌ **Adding scopes to the OAuth client instead of the consent screen**
   → Scopes must be configured on the OAuth Consent Screen

❌ **Not clicking "Save and Continue" after adding scopes**
   → Changes aren't saved until you complete the wizard

❌ **Having the app in "Testing" mode but scopes not configured**
   → Testing mode still requires explicit scope configuration

❌ **Not revoking old permissions before re-authorizing**
   → Old cached authorizations can interfere

## Expected Behavior After Fix

When you check the logs after fixing, you should see:

```
INFO: DIAGNOSTIC: Fetching message XXX for alexsheppert@gmail.com with scopes: ['gmail.metadata', 'gmail.modify', 'gmail.readonly'] (valid=True, expired=False)
DEBUG: URL being requested: GET https://gmail.googleapis.com/gmail/v1/users/.../messages/XXX?format=full&alt=json
```

And **NO** error about "Metadata scope doesn't allow format FULL"

Instead, the message should load successfully!

---

**Priority:** Start with Step 1 - Check OAuth Consent Screen Scopes

This is the most common cause and the easiest to fix!
