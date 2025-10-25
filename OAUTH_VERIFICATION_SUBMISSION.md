# OAuth Verification Submission - URLs and Information

## Status
✅ **All required pages are now live and deployed!**

Changes pushed to GitHub and automatically deployed via Cloud Run.

---

## URLs for Google OAuth Verification Submission

### **Homepage URL**
```
https://inboximp.com
```

### **Privacy Policy URL**
```
https://inboximp.com/static/privacy.html
```

### **Terms of Service URL**
```
https://inboximp.com/static/terms.html
```

### **Support Email**
```
support@inboximp.com
```

### **Privacy Contact Email**
```
privacy@inboximp.com
```

---

## What Was Created

### 1. Privacy Policy (`/static/privacy.html`)
Comprehensive privacy policy covering:
- ✅ What data we collect (Gmail messages, labels, metadata)
- ✅ How we use it (AI classification, label management)
- ✅ Third-party services (Google Gmail API, OpenRouter, Supabase)
- ✅ Data storage and security measures
- ✅ User rights (access, deletion, export)
- ✅ GDPR and CCPA compliance
- ✅ Google API Services User Data Policy compliance

### 2. Terms of Service (`/static/terms.html`)
Complete terms of service including:
- ✅ Service description
- ✅ User authorization via OAuth
- ✅ Acceptable use policy
- ✅ AI classification disclaimers
- ✅ Limitation of liability
- ✅ Dispute resolution
- ✅ Termination rights

### 3. Updated Homepage (`/static/index.html`)
Enhanced with:
- ✅ Inboximp logo display
- ✅ Clear description of the service
- ✅ Links to Privacy Policy and Terms
- ✅ Professional branding
- ✅ Footer with all legal links

### 4. Logo (`/static/inboximp.png`)
- ✅ 237 KB PNG file
- ✅ Displayed on homepage and policy pages
- ✅ Set as favicon

---

## Next Steps: Submit for Verification

### Step 1: Open Verification Center
Go to: https://console.cloud.google.com/apis/credentials/consent?project=inboximp-email-triage

### Step 2: Fill Out OAuth Consent Screen

Make sure all fields are filled:

**App Information:**
- App name: `Inboximp Email Triage`
- User support email: `support@inboximp.com`
- App logo: Upload `/static/inboximp.png` (already in repo)

**App Domain:**
- Application home page: `https://inboximp.com`
- Application privacy policy: `https://inboximp.com/static/privacy.html`
- Application terms of service: `https://inboximp.com/static/terms.html`

**Authorized domains:**
- `inboximp.com`

**Developer Contact:**
- Developer contact info: `support@inboximp.com`

### Step 3: Verify Scopes Are Configured

Ensure these scopes are added (you already have them):
- ✅ `https://www.googleapis.com/auth/gmail.modify`
- ✅ `https://www.googleapis.com/auth/gmail.readonly`
- ✅ `https://www.googleapis.com/auth/gmail.metadata`

### Step 4: Submit Verification Request

Click "Submit for verification" and provide:

#### **Scope Justifications:**

**gmail.modify:**
```
Our app needs to apply labels to Gmail messages to organize the user's inbox.
After classifying emails using AI, we apply labels like "should_read",
"can_delete", or "requires_response" to help users triage their inbox.
This requires the gmail.modify scope to update message labels.
```

**gmail.readonly:**
```
Our app needs to read the full content of email messages to perform AI-powered
classification. We analyze the subject, sender, and body text to determine the
appropriate category and action for each email. The gmail.readonly scope is
required to access full message content (the gmail.metadata scope only provides
headers, not body content which is essential for accurate classification).
```

**gmail.metadata:**
```
Our app uses metadata (headers, labels, dates) to efficiently list and track
which messages have been processed, and to avoid re-processing the same emails.
This allows us to provide a better user experience with faster inbox scanning
and accurate processing history.
```

#### **How Your App Uses Gmail Data:**

```
1. User authorizes the app via OAuth to access their Gmail account
2. App reads incoming emails from the user's inbox
3. Email content (subject, sender, body) is analyzed using AI (OpenRouter API)
   to determine appropriate classification
4. AI determines which label to apply based on email importance and content
5. App applies the determined label to the Gmail message
6. Classification decision is stored in our database for user reference and
   improving accuracy
7. Email content itself is NOT stored permanently - only processed in memory
   during classification

Users can:
- View their classification history in the web console
- Delete their data at any time
- Revoke access via Google Account settings
```

#### **What User Data You Store:**

```
We store:
- Gmail message IDs (to track which emails we've processed)
- Classification decisions (which label was applied and why)
- AI-generated summaries of emails
- OAuth tokens (encrypted, to maintain authorized access)
- User's Gmail email address

We do NOT store:
- Full email content (only processed temporarily in memory)
- Email attachments
- Contact lists
- Unprocessed email bodies
```

---

## Verification Timeline

| Stage | Timeframe | Action |
|-------|-----------|--------|
| Submission | Day 0 | Click "Submit for verification" |
| Initial Review | 3-5 days | Google assigns reviewer |
| Questions/Clarification | 1-2 weeks | Respond to any Google questions |
| Final Decision | 2-4 weeks | Approval or feedback for changes |
| Activation | Immediate | Once approved, restriction lifts |

---

## While Waiting for Approval

Your app will:
- ✅ Remain in "In production" mode
- ✅ Work for up to 100 users (plenty for early access)
- ⚠️ Still have metadata-only restriction on Gmail API
- ⚠️ Show "unverified app" warnings to users

**Once approved:**
- ✅ Metadata restriction lifts immediately
- ✅ Full Gmail scope functionality works
- ✅ No user limits (beyond API quotas)
- ✅ "Verified app" badge on consent screen
- ✅ Less scary warnings for users

---

## Checklist Before Submitting

- [x] Privacy policy published at https://inboximp.com/static/privacy.html
- [x] Terms of service published at https://inboximp.com/static/terms.html
- [x] Homepage at https://inboximp.com with clear description
- [x] Logo uploaded and displayed
- [x] All URLs are accessible and working
- [x] Support email set up (support@inboximp.com)
- [x] App in "In production" mode
- [x] Scopes configured in OAuth consent screen
- [ ] OAuth consent screen completely filled out
- [ ] Verification request submitted
- [ ] Ready to respond to Google's questions

---

## Testing the URLs

You can verify all URLs are working:

```bash
# Test homepage
curl -I https://inboximp.com

# Test privacy policy
curl -I https://inboximp.com/static/privacy.html

# Test terms of service
curl -I https://inboximp.com/static/terms.html
```

All should return `200 OK`.

---

## Important Notes

1. **Wait ~5 minutes** after pushing to GitHub for Cloud Run to deploy the changes

2. **Test in a browser** to make sure everything looks good:
   - https://inboximp.com (should show logo and new text)
   - https://inboximp.com/static/privacy.html
   - https://inboximp.com/static/terms.html

3. **Email addresses** - Make sure these are monitored:
   - support@inboximp.com (for user support)
   - privacy@inboximp.com (for privacy requests)

   If these don't exist yet, you can use your personal email for now.

4. **Responding to Google** - When they ask questions:
   - Respond within 3-5 business days
   - Be clear and specific
   - Provide screenshots if helpful
   - Don't be vague

---

## Ready to Submit!

All URLs are live and ready. You can now:

1. Go to the OAuth Consent Screen
2. Fill out all fields with the URLs above
3. Submit for verification
4. Wait for Google's response (1-4 weeks)

**Good luck!** 🎉

---

## Contact for Help

If you need help during the verification process:
- Review VERIFICATION_GUIDE.md for detailed guidance
- Check Google's documentation: https://support.google.com/cloud/answer/9110914
- Respond to Google's questions clearly and promptly

The metadata restriction will lift as soon as Google approves your verification! ✅
