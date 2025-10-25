# Gmail Metadata-Only Issue - Final Diagnosis

## Current Status

✅ App is **Published** ("In production")
⚠️ App **Requires Verification** for restricted scopes
✅ OAuth grants all 3 scopes
✅ Google OAuth recognizes all 3 scopes
✗ Gmail API **rejects** the scopes and only allows metadata

## The Problem

Google has a **two-tier authorization system** for restricted scopes like Gmail:

### Tier 1: OAuth Authorization (Working ✓)
- Your OAuth consent screen is configured correctly
- App requests the right scopes
- Google issues tokens with all 3 scopes
- Token introspection shows all scopes present

### Tier 2: API-Level Enforcement (Blocked ✗)
- Gmail API has **additional verification requirements**
- For **unverified apps**, Gmail API restricts usage even if OAuth granted the scopes
- This is why you see: `"Metadata scope doesn't allow format FULL"`

## Why Publishing Didn't Fix It

Publishing moved you from "Testing" to "In production", but you still have the warning:
> "Your app requires verification"

For **restricted scopes** (like gmail.modify and gmail.readonly), Google enforces verification at the **API level**, not just the OAuth level.

## Your Options

### Option 1: Complete OAuth Verification (Recommended for Production)

**Pros:**
- Allows unlimited users
- Fully functional app
- No restrictions

**Cons:**
- Takes 1-4 weeks for Google to review
- Requires detailed privacy policy
- May require security assessment

**Steps:**
1. Go to: https://console.cloud.google.com/apis/credentials/consent?project=inboximp-email-triage
2. Click "Go to verification center" or "Prepare for verification"
3. Fill out the verification form:
   - App description
   - Privacy policy URL
   - Homepage URL
   - Justification for why you need Gmail scopes
4. Submit for review
5. Wait for Google's approval (1-4 weeks typically)

**Documentation:** https://support.google.com/cloud/answer/9110914

### Option 2: Use Service Account with Domain-Wide Delegation (Workspace Only)

**Only works if you have Google Workspace** (not consumer Gmail).

**Pros:**
- Bypasses OAuth consent entirely
- No verification needed
- Works immediately

**Cons:**
- **Requires Google Workspace** (not free Gmail)
- Requires Workspace admin access
- Different authentication setup

**Steps:**
1. Create a Service Account in Google Cloud Console
2. Enable Domain-Wide Delegation for the service account
3. In Google Workspace Admin, authorize the service account with Gmail scopes
4. Update config:
   ```python
   GMAIL_SERVICE_ACCOUNT_FILE = "path/to/service-account-key.json"
   GMAIL_DELEGATED_USER = "alexsheppert@gmail.com"
   ```
5. Restart app

**Documentation:** https://developers.google.com/identity/protocols/oauth2/service-account

### Option 3: Back to Testing Mode (Temporary Workaround)

Try switching **back to Testing mode** to see if that works differently:

**Steps:**
1. Go to OAuth Consent Screen
2. Click "Back to Testing"
3. Make sure alexsheppert@gmail.com is a test user
4. Revoke access and re-authorize

**Note:** I'm not confident this will work, but worth trying since published mode with unverified app has the same restriction.

### Option 4: Use a Different Google Cloud Project (Last Resort)

Sometimes Google's restrictions get "stuck" on a project. Creating a fresh project might help:

1. Create new Google Cloud Project
2. Enable Gmail API
3. Create new OAuth client (Web application)
4. Create new OAuth consent screen with scopes
5. Keep in "Testing" mode
6. Add yourself as test user
7. Update your `json_keys/client_secret.json` with new client
8. Restart and re-authorize

## Verification Process Details

If you choose Option 1 (verification), you'll need:

1. **Privacy Policy** - Must be publicly accessible URL explaining:
   - What data you collect
   - How you use Gmail data
   - How you store/protect data
   - User's rights (delete data, revoke access, etc.)

2. **Homepage** - Public URL explaining your app

3. **Justification** - Clear explanation of why you need Gmail scopes:
   > "This app automatically triages and organizes Gmail inbox by reading email content,
   > applying AI-powered classification, and managing labels. It requires gmail.modify
   > to apply labels and gmail.readonly to access full email content for classification."

4. **OAuth Client Configuration** - Must use Web application client (you have this ✓)

5. **App Functionality** - Must actually use the scopes you're requesting (you do ✓)

## What I Recommend

**If this is just for personal use:**
- Try Option 3 (back to Testing mode) first
- If that doesn't work, consider Option 4 (new project)
- Last resort: Use read-only browser extension instead

**If you want to share with others:**
- Go with Option 1 (verification)
- Start the process now (takes weeks)
- Keep using metadata-only mode until verified

**If you have Google Workspace:**
- Definitely use Option 2 (Service Account)
- Much simpler and works immediately

## Why This Is So Complicated

Google introduced these restrictions after the Cambridge Analytica scandal and other privacy incidents. Apps requesting sensitive scopes (like full Gmail access) face extra scrutiny:

1. **OAuth grants scopes** - Basic permission layer
2. **API enforces verification** - Additional security layer
3. **Unverified apps get limited** - Even if OAuth says yes, API says no

This is intentional on Google's part to protect user data.

## Next Steps

Tell me which option you want to pursue and I'll help you with the specific steps!
