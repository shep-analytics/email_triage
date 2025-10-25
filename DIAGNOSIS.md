# Gmail Metadata-Only Error - Root Cause Found

## What We've Confirmed

✅ **OAuth scopes are properly configured** (your screenshots show this)
✅ **Google OAuth recognizes all 3 scopes** (we just verified with tokeninfo API)
✅ **Token has gmail.modify, gmail.readonly, and gmail.metadata**
✅ **You're added as a test user**

## The Problem

Even though OAuth grants the token with all scopes, **Gmail API is still blocking it** with:

```
"Metadata scope doesn't allow format FULL"
```

## Root Cause

This is a **Gmail API-specific restriction** for apps with restricted scopes.

Google has two levels of scope authorization:
1. **OAuth level** - Grants the token (✓ Working - we confirmed this)
2. **API level** - Actually allows using the token (✗ Blocked - this is the problem)

Gmail API adds extra restrictions beyond OAuth for sensitive scopes like `gmail.modify` and `gmail.readonly`.

## The Fix

This is almost certainly due to your **OAuth Consent Screen Publishing Status**.

### Check Your Publishing Status

1. Go to: https://console.cloud.google.com/apis/credentials/consent?project=inboximp-email-triage

2. Look at the very top of the page - what does it say?

**If it says "Testing":**
   - This is your problem
   - Gmail API restricts apps in Testing mode even for test users
   - **Solution:** Click "PUBLISH APP" button
   - You may see a warning about verification - click "Publish" anyway
   - You can complete verification later if you want public access

**If it says "In production - Needs verification":**
   - Gmail API restricts unverified apps even when published
   - **Solution:** Either:
     - Option A: Complete Google's verification process (1-2 weeks)
     - Option B: Keep testing with limited functionality
     - Option C: Use Service Account with Domain-Wide Delegation (Workspace only)

**If it says "In production - Verified":**
   - This should work - the issue is something else
   - Try revoking access and re-authorizing
   - Wait 5-10 minutes for changes to propagate

### After Publishing/Changing Status

1. Revoke old access: https://myaccount.google.com/permissions
   - Find "Inboximp Email Triage"
   - Click "Remove access"

2. Go to http://localhost:8000

3. Click "Connect Gmail" and re-authorize

4. Try viewing an email

## Why This Happens

Gmail scopes (`gmail.modify`, `gmail.readonly`) are classified as **"restricted"** by Google.

For restricted scopes, Google enforces additional requirements:
- Apps must be Published (not just in Testing)
- OR apps must complete Google's verification process
- OR use Service Account with Domain-Wide Delegation

These requirements apply at the **API level**, not just the OAuth level. That's why:
- OAuth happily grants you a token with all scopes ✓
- But Gmail API refuses to honor those scopes ✗

## Quick Test

Tell me what your Publishing status shows, and I'll give you the exact next steps!
