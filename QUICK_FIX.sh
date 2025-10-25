#!/usr/bin/env bash
# Quick fix checklist for OAuth scope issue

cat << 'EOF'
╔═══════════════════════════════════════════════════════════════════════════╗
║                    GMAIL SCOPE ISSUE - QUICK FIX                          ║
╚═══════════════════════════════════════════════════════════════════════════╝

The logs show Google is ONLY recognizing gmail.metadata scope, even though
your token has all three scopes. This is an OAuth Consent Screen config issue.

╔═══════════════════════════════════════════════════════════════════════════╗
║ STEP 1: Fix OAuth Consent Screen Scopes                                  ║
╚═══════════════════════════════════════════════════════════════════════════╝

1. Open this URL:
   👉 https://console.cloud.google.com/apis/credentials/consent?project=inboximp-email-triage

2. Click "EDIT APP" button

3. Click through to the "Scopes" section (might be step 2 or 3)

4. Click "ADD OR REMOVE SCOPES"

5. In the filter box, type: "Gmail API"

6. ✓ CHECK these three boxes:
   ☐ Read, compose, and send emails from your Gmail account
     └─ Scope: .../auth/gmail.modify

   ☐ View your email messages and settings
     └─ Scope: .../auth/gmail.readonly

   ☐ View your email message metadata
     └─ Scope: .../auth/gmail.metadata

7. Click "UPDATE" at the bottom

8. Click "SAVE AND CONTINUE" through all steps

9. Click "BACK TO DASHBOARD"

╔═══════════════════════════════════════════════════════════════════════════╗
║ STEP 2: Revoke Old Authorization                                         ║
╚═══════════════════════════════════════════════════════════════════════════╝

1. Open this URL:
   👉 https://myaccount.google.com/permissions

2. Find "Inboximp Email Triage" (or your app name)

3. Click on it

4. Click "Remove access"

5. Confirm removal

╔═══════════════════════════════════════════════════════════════════════════╗
║ STEP 3: Re-authorize                                                     ║
╚═══════════════════════════════════════════════════════════════════════════╝

1. Go to: http://localhost:8000

2. Sign in with your Google account

3. Click "Connect Gmail"

4. You should see consent screen with ALL permissions listed

5. Click "Continue" and authorize

╔═══════════════════════════════════════════════════════════════════════════╗
║ STEP 4: Test                                                             ║
╚═══════════════════════════════════════════════════════════════════════════╝

1. Click on any email in your inbox

2. Click "View"

3. ✓ You should now see FULL EMAIL CONTENT!

╔═══════════════════════════════════════════════════════════════════════════╗
║ What Was Wrong?                                                          ║
╚═══════════════════════════════════════════════════════════════════════════╝

Your OAuth Consent Screen wasn't explicitly configured with the Gmail scopes.

When scopes aren't explicitly added to the OAuth Consent Screen:
  ✗ Google grants tokens with the scopes
  ✗ BUT restricts what those tokens can actually do
  ✗ Only the least privileged scope (metadata) works

After explicitly adding scopes to OAuth Consent Screen:
  ✓ Google properly authorizes the full scope capabilities
  ✓ Your token can access full email content
  ✓ Everything works as expected!

╔═══════════════════════════════════════════════════════════════════════════╗
║ Need More Details?                                                       ║
╚═══════════════════════════════════════════════════════════════════════════╝

Read: fix_oauth_consent_scopes.md

That file has:
  • Detailed step-by-step instructions with screenshots
  • Alternative solutions if this doesn't work
  • Troubleshooting for common issues
  • Explanation of why this happens

╔═══════════════════════════════════════════════════════════════════════════╗

EOF
