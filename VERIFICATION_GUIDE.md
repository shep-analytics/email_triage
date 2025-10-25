# OAuth Verification Guide for Gmail Scopes

## Overview

To use Gmail's restricted scopes (`gmail.modify`, `gmail.readonly`) with external users, you need to complete Google's OAuth verification process.

**Timeline:** 1-4 weeks typically, sometimes faster for clear use cases
**Cost:** Free
**Difficulty:** Moderate - mostly documentation and waiting

## What You Need Before Starting

### 1. Privacy Policy (Required)

A publicly accessible webpage explaining your data practices.

**Minimum requirements:**
- What data you collect from Gmail
- How you use that data
- How you store and protect it
- How long you retain it
- How users can delete their data
- How users can revoke access

**Simple template for your use case:**

```markdown
# Privacy Policy for Inboximp Email Triage

Last Updated: [Date]

## What We Do
Inboximp Email Triage helps you automatically organize your Gmail inbox using AI-powered classification.

## Data We Access
- Email messages (subject, sender, content, metadata)
- Gmail labels and settings
- Your Google Account email address

## How We Use Your Data
- Read your emails to classify them using AI
- Apply labels to organize your inbox
- Store classification decisions to improve accuracy
- We do NOT:
  - Share your emails with third parties
  - Use your data for advertising
  - Sell your data
  - Read emails outside our classification purpose

## Data Storage
- Classification results are stored in our secure database (Supabase)
- Email content is NOT stored permanently
- Only processed temporarily for classification
- All data is encrypted in transit and at rest

## Data Retention
- Classification decisions: Kept until you delete them
- Email content: Not stored (only processed in memory)
- OAuth tokens: Stored securely, deleted when you revoke access

## Your Rights
You can:
- Revoke access at any time: https://myaccount.google.com/permissions
- Request deletion of all your data: [your support email]
- Review what data we have: [contact method]

## Data Protection
- OAuth tokens encrypted in database
- All connections use HTTPS/TLS
- Access logs maintained for security
- Regular security updates

## Third-Party Services
We use:
- Google Gmail API (to access your emails)
- OpenRouter API (to classify emails - email content sent for AI processing)
- Supabase (to store classification results)

## Contact
For privacy questions: [your email]
To delete your data: [your email]

## Changes to This Policy
We'll notify users of significant changes via email.
```

**Where to host it:**
- GitHub Pages (free): Create a `docs/` folder in your repo, add `privacy.md`
- Your website if you have one
- Google Sites (free)
- Netlify/Vercel (free)

### 2. Homepage/App Description (Required)

A public URL explaining what your app does.

**Options:**
- Your GitHub README (simplest)
- A simple landing page
- Documentation site

**Should include:**
- What the app does
- How it helps users
- Why it needs Gmail access
- How to get started
- Link to privacy policy

### 3. YouTube Video (Recommended but not required)

A short demo showing:
- How users authorize the app
- What the app does with Gmail data
- How users can revoke access

**Tips:**
- Can be unlisted (not public)
- 1-2 minutes is enough
- Screen recording with narration
- Use OBS Studio or QuickTime (free)

### 4. App Logo (Recommended)

- 120x120 pixels minimum
- Clear branding
- Will appear on consent screen

## Verification Process Steps

### Step 1: Prepare Required URLs

Before starting verification, have these ready:

1. **Privacy Policy URL:** https://yoursite.com/privacy
2. **Homepage URL:** https://github.com/yourusername/email_triage (or custom site)
3. **Support Email:** your-email@domain.com
4. **Terms of Service URL:** (optional but recommended)

### Step 2: Access Verification Center

1. Go to: https://console.cloud.google.com/apis/credentials/consent?project=inboximp-email-triage

2. You should see a warning: "Your app requires verification"

3. Click **"Go to verification center"** or **"Prepare for verification"**

### Step 3: Complete Brand Information

Fill out the OAuth consent screen completely:

**App Information:**
- App name: Inboximp Email Triage
- User support email: [your email]
- App logo: [upload 120x120 image]

**App Domain:**
- Application home page: [your homepage URL]
- Application privacy policy link: [your privacy policy URL]
- Application terms of service link: [optional]

**Authorized domains:**
- Add: `inboximp.com` (your production domain)
- Add: `github.io` (if using GitHub Pages)

**Developer Contact:**
- Email addresses: [your email(s) for Google to contact you]

### Step 4: Configure Scopes

Make sure these scopes are added (you already have them):
- ✅ `https://www.googleapis.com/auth/gmail.modify`
- ✅ `https://www.googleapis.com/auth/gmail.readonly`
- ✅ `https://www.googleapis.com/auth/gmail.metadata`

### Step 5: Submit Verification Request

1. Click **"Submit for verification"** or **"Prepare for verification"**

2. You'll see a form asking:

**"Why does your app need this scope?"**

Write a clear justification for **each scope**:

```
gmail.modify:
Our app needs to apply labels to Gmail messages to organize the user's inbox.
After classifying emails using AI, we apply labels like "should_read" or
"can_delete" to help users triage their inbox. This requires the gmail.modify
scope to update message labels.

gmail.readonly:
Our app needs to read the full content of email messages to perform AI-powered
classification. We analyze the subject, sender, and body text to determine the
appropriate category and action for each email. The gmail.readonly scope is
required to access full message content (the gmail.metadata scope only provides
headers, not body content).

gmail.metadata:
Our app uses metadata (headers, labels, dates) to efficiently list and track
which messages have been processed, and to avoid re-processing the same emails.
```

**"How does your app use this data?"**

```
1. User authorizes app via OAuth to access their Gmail
2. App reads incoming emails from their inbox
3. Email content is sent to OpenRouter API for AI classification
4. AI determines appropriate labels based on content
5. App applies labels to organize user's inbox
6. Classification decisions are stored in our database for user reference
7. Email content itself is NOT stored permanently - only processed in-memory

Users can view their classification history and delete their data at any time.
```

**"What user data do you store?"**

```
- Gmail message IDs (to track which emails we've processed)
- Classification decisions (which label was applied and why)
- OAuth tokens (encrypted, to maintain authorized access)
- User's Gmail email address

We do NOT store:
- Full email content
- Email attachments
- Contact lists
```

3. **Upload supporting documentation:**

**IMPORTANT:** Google may ask for:
- Privacy policy (link)
- Homepage (link)
- Video demonstration (optional but helpful)
- Screenshots of the app in action

### Step 6: Wait for Review

**Timeline:**
- Initial review: 3-5 business days
- Follow-up questions: 1-2 weeks
- Total time: 1-4 weeks typically

**What happens:**
1. Google reviews your submission
2. They may ask clarifying questions via email
3. They may request additional documentation
4. Eventually: Approved or Rejected (with reasons)

**During the wait:**
- Your app stays in "In production - Unverified" mode
- Limited to 100 users (plenty for testing)
- Metadata-only restriction remains

**After approval:**
- Restriction lifted immediately
- All scopes work fully
- No user limits

## Common Rejection Reasons (and How to Avoid)

### 1. Privacy Policy Issues
❌ **Problem:** Generic privacy policy not specific to Gmail usage
✅ **Solution:** Clearly explain what Gmail data you access and why

### 2. Unclear Use Case
❌ **Problem:** Vague explanation like "we need to read emails"
✅ **Solution:** Specific justification with exact feature descriptions

### 3. Overly Broad Scopes
❌ **Problem:** Requesting scopes you don't actually use
✅ **Solution:** Only request scopes you actively use in the app

### 4. Missing Documentation
❌ **Problem:** Broken links, no privacy policy
✅ **Solution:** Test all URLs before submitting

### 5. Security Concerns
❌ **Problem:** Unclear how data is protected
✅ **Solution:** Explain encryption, access controls, security measures

## What to Do While Waiting

### Option 1: Work in Limited Mode
- Keep the app in "Testing" mode
- Use it yourself (as a test user)
- Keep developing features
- Accept the 100-user limit for now

### Option 2: Alternative Approach for Development
- Use metadata-only mode for non-critical features
- Build UI and other functionality
- Leave email reading as "coming soon"
- Activate once verified

### Option 3: Consider Paid Workspace for Testing
- Buy one Workspace license ($6-12/month)
- Use Service Account for development
- Switch to OAuth when verified for production

## Quick Start: Privacy Policy Template

Here's a minimal privacy policy you can deploy right now:

```bash
# Create a docs folder in your repo
mkdir -p docs

# Create privacy policy
cat > docs/privacy.md << 'EOF'
# Privacy Policy

[Use the template above]
EOF

# Create a simple index
cat > docs/index.md << 'EOF'
# Inboximp Email Triage

AI-powered email organization for Gmail.

[Link to privacy policy](privacy.md)
EOF

# Enable GitHub Pages
git add docs/
git commit -m "Add privacy policy and homepage for OAuth verification"
git push

# Then go to GitHub repo Settings > Pages > Source: main branch /docs folder
```

Your privacy policy will be at: `https://yourusername.github.io/email_triage/privacy`

## Checklist Before Submitting

- [ ] Privacy policy published and accessible
- [ ] Homepage/description published
- [ ] All OAuth consent screen fields filled out
- [ ] Scopes accurately reflect app functionality
- [ ] Support email is valid and monitored
- [ ] Justification clearly explains why each scope is needed
- [ ] Screenshot/video showing the app in action (optional but helpful)
- [ ] Tested all links work

## Timeline Expectations

| Stage | Time | What Happens |
|-------|------|--------------|
| Submit | Day 0 | Application sent to Google |
| Initial Review | 3-5 days | Google assigns reviewer |
| Questions | 1-2 weeks | Back-and-forth if needed |
| Final Decision | 2-4 weeks | Approved or rejected |
| Activation | Immediate | Once approved, works instantly |

## After Approval

Once verified:
1. ✅ Metadata-only restriction lifted
2. ✅ All Gmail scopes work fully
3. ✅ No user limits (beyond standard API quotas)
4. ✅ Badge showing "Verified" on consent screen
5. ✅ Users see less scary warnings when authorizing

## Questions?

Let me know if you need help with:
- Writing the privacy policy
- Creating a homepage
- Recording a demo video
- Responding to Google's questions
- Understanding rejection reasons

I can help you prepare everything before submitting!
