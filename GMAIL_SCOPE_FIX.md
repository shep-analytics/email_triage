# Gmail Metadata-Only Scope Issue - Diagnosis and Fix

## Problem Summary

Your application is showing "Mailbox token only grants gmail.metadata" errors despite the OAuth consent screen showing full permissions granted. Users can see email headers but not full content.

## Root Cause

**The `gmail_tokens` table is missing from your Supabase database.**

### What's Happening:

1. **Local Development (works):**
   - Token stored in filesystem: `.gmail_tokens/token_alexsheppert_at_gmail_com.json`
   - Has all correct scopes: `gmail.modify`, `gmail.readonly`, `gmail.metadata`
   - App reads from filesystem successfully

2. **Production/Cloud Run (broken):**
   - Cloud Run containers are ephemeral - filesystem tokens don't persist
   - App tries to read token from Supabase first (priority)
   - `gmail_tokens` table doesn't exist → token retrieval fails
   - When you complete OAuth, token save to Supabase fails silently (table doesn't exist)
   - No valid token available → app falls back to limited access

### Evidence:

```bash
$ python3 check_all_tokens.py
# Shows: "table 'public.gmail_tokens' does not exist"
```

Your current Supabase tables:
- ✓ `messages`
- ✓ `mailboxes`
- ✓ `alerts`
- ✗ `gmail_tokens` (MISSING!)

## Solution

### Step 1: Create the Missing Table

1. Open your Supabase Dashboard:
   **https://app.supabase.com/project/wxliwwdftbolaxnpjjaj**

2. Click **SQL Editor** (left sidebar)

3. Click **+ New query**

4. Paste and run this SQL:

```sql
CREATE TABLE IF NOT EXISTS gmail_tokens (
    email TEXT PRIMARY KEY,
    token_json JSONB NOT NULL,
    scopes TEXT[] NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gmail_tokens_email ON gmail_tokens(email);
CREATE INDEX IF NOT EXISTS idx_gmail_tokens_updated_at ON gmail_tokens(updated_at);
```

5. Click **Run** (or Ctrl+Enter)

6. You should see: "Success. No rows returned"

7. Verify in **Table Editor** → you should now see `gmail_tokens` table

### Step 2: Re-Complete OAuth Flow

Now that the table exists, the token can be saved properly:

1. Go to **https://inboximp.com**
2. Sign in with your Google account (alexsheppert@gmail.com)
3. Click **"Connect Gmail"**
4. Grant all requested permissions (you should see the same consent screen as your screenshot)
5. Complete the flow

The token will now be **successfully saved** to Supabase!

### Step 3: Verify the Fix

Run the verification script:

```bash
python3 check_all_tokens.py
```

You should now see:
- ✓ Token found in Supabase
- ✓ Has gmail.modify scope
- ✓ Has gmail.readonly scope
- ✓ Has gmail.metadata scope

### Step 4: Test in Production

1. Go to https://inboximp.com
2. Navigate to your inbox
3. Click "View" on any email
4. You should now see **full email content** instead of the metadata-only warning!

## Why This Happened

According to `AGENTS.md` (lines 247-252), the `gmail_tokens` table was added on **2025-10-24** as part of the "Terminal OAuth + Supabase tokens" update. However, this was a code change only - the table itself was never created in your production Supabase database.

The documentation states:
> "Schema to create in Supabase once: `create table if not exists gmail_tokens...`"

This was a manual step that was missed during deployment.

## Architecture Details

### Token Storage Priority (from `app.py:192-233`):

1. **Supabase** (highest priority) - for production persistence
2. **Filesystem** (fallback) - for local development only

### OAuth Flow (from `app.py:844-912`):

1. User clicks "Connect Gmail"
2. App requests scopes: `gmail.modify`, `gmail.readonly`, `gmail.metadata`
3. User grants permissions
4. Token received from Google
5. App calls `state_store.upsert_gmail_token()` to save to Supabase
6. **This was failing silently because table didn't exist!**

### Metadata Fallback Logic (from `app.py:433-516`):

When the app can't get a valid token with full scopes:
1. Tries to fetch email with format="full"
2. Gets 403 error: "insufficient permissions" or "metadata scope"
3. Falls back to format="metadata" (headers only, no body)
4. Shows warning: "Mailbox token only grants gmail.metadata..."

## Verification Commands

After creating the table and re-consenting:

```bash
# Check token exists and has correct scopes
python3 check_all_tokens.py

# Detailed diagnostic
python3 diagnose_token_issue.py

# Test end-to-end (requires deployment)
python3 verify_e2e.py --key-file json_keys/owner_google_service_account_key.json \
    --region us-central1 --service email-triage \
    --subscription email-triage-push --email alexsheppert@gmail.com
```

## Additional Notes

### OAuth Client Configuration

Your OAuth client is correctly configured as **Web application**:
- Client ID: `561574736348-op1pild9jpibin19f1ct8pqpe05f3r0p.apps.googleusercontent.com`
- Redirect URIs include production URLs (`https://inboximp.com/oauth/callback`)
- ✓ Properly configured

### Google Workspace vs Consumer Gmail

From `AGENTS.md:259-260`:
> Gmail read/modify scopes are "restricted" by Google. To allow any external user to authorize, you must publish the OAuth consent screen and complete restricted-scope verification for Gmail.

If you're using **consumer Gmail** (not Workspace), make sure:
- Your OAuth consent screen is published (not in testing mode)
- OR add users as test users in Google Cloud Console

For **Google Workspace only**, you could alternatively use:
- Service Account with Domain-Wide Delegation
- Set `GMAIL_SERVICE_ACCOUNT_FILE` instead of OAuth tokens
- Requires Workspace admin approval

## Related Files

- [app.py:192-233](app.py#L192-L233) - Token factory and storage logic
- [app.py:433-516](app.py#L433-L516) - Metadata fallback detection
- [app.py:844-912](app.py#L844-L912) - OAuth endpoints
- [supabase_state.py:329-370](supabase_state.py#L329-L370) - Token storage implementation
- [gmail_watch.py:24-37](gmail_watch.py#L24-L37) - Scope definitions
- [AGENTS.md:247-252](AGENTS.md#L247-L252) - Table schema documentation

## Quick Reference

**Supabase Dashboard:** https://app.supabase.com/project/wxliwwdftbolaxnpjjaj
**Production Site:** https://inboximp.com
**Google Cloud Console:** https://console.cloud.google.com/apis/credentials?project=inboximp-email-triage

---

**Status:** Ready to fix - just create the table and re-consent!
