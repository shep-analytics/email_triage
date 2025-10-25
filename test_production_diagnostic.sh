#!/usr/bin/env bash
# Test the production Supabase diagnostic endpoint
# This will show you exactly what the production environment sees

set -euo pipefail

echo "====================================================================="
echo "PRODUCTION SUPABASE DIAGNOSTIC TEST"
echo "====================================================================="
echo ""
echo "This script will:"
echo "1. Wait for the latest deployment to complete"
echo "2. Open your browser to sign in to https://inboximp.com"
echo "3. Call the diagnostic endpoint"
echo ""
echo "Instructions:"
echo "1. Open https://inboximp.com in your browser"
echo "2. Sign in with your Google account (alexsheppert@gmail.com)"
echo "3. Open browser console (F12)"
echo "4. Run this command in the console:"
echo ""
echo "-------------------------------------------------------------------"
echo "fetch('/api/diagnostic/supabase')"
echo "  .then(r => r.json())"
echo "  .then(d => console.log(JSON.stringify(d, null, 2)))"
echo "-------------------------------------------------------------------"
echo ""
echo "OR use this one-liner curl command (you'll need to get your session cookie):"
echo ""
echo "curl -H \"Cookie: session=YOUR_SESSION_COOKIE\" \\"
echo "     https://inboximp.com/api/diagnostic/supabase | jq"
echo ""
echo "====================================================================="
echo ""

# Check if deployment is in progress
echo "Checking deployment status..."
PROJECT_ID=inboximp-email-triage
REGION=us-central1
SERVICE=email-triage

# Get latest revision
REV=$(gcloud run services describe "${SERVICE}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format='value(status.latestCreatedRevisionName)' 2>/dev/null || echo "unknown")

echo "Latest revision: ${REV}"

if [[ "${REV}" != "unknown" ]]; then
    echo ""
    echo "Checking if revision is ready..."
    STATUS=$(gcloud run revisions describe "${REV}" \
        --region "${REGION}" \
        --project "${PROJECT_ID}" \
        --format='value(status.conditions[0].status)' 2>/dev/null || echo "unknown")

    echo "Revision status: ${STATUS}"

    if [[ "${STATUS}" == "True" ]]; then
        echo ""
        echo "✓ Service is ready!"
        echo ""
        echo "You can now access the diagnostic endpoint at:"
        echo "https://inboximp.com/api/diagnostic/supabase"
        echo ""
        echo "Remember: You must be signed in first!"
    else
        echo ""
        echo "⚠ Revision may still be deploying. Wait a minute and try again."
    fi
fi

echo ""
echo "====================================================================="
