#!/usr/bin/env python3
"""
Check what Google OAuth actually thinks about your access token.
This will tell us if Google recognizes the full scopes or is restricting them.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from keys import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
import requests

def main():
    print("=" * 80)
    print("GOOGLE TOKEN INTROSPECTION TEST")
    print("=" * 80)
    print()

    # Get the token from Supabase
    email = "alexsheppert@gmail.com"

    print(f"1. Fetching token for {email} from Supabase...")

    try:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/gmail_tokens",
            params={"email": f"eq.{email}", "select": "token_json", "limit": 1},
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            print(f"✗ Failed to fetch token from Supabase: {response.status_code}")
            return 1

        data = response.json()
        if not data:
            print("✗ No token found for this email")
            return 1

        token_data = json.loads(data[0]["token_json"])
        access_token = token_data.get("token") or token_data.get("access_token")

        if not access_token:
            print("✗ Token data doesn't contain access_token")
            return 1

        print(f"✓ Got access token: {access_token[:30]}...")
        print()

        # Show what the token claims to have
        claimed_scopes = token_data.get("scopes", [])
        print("2. Scopes claimed by token:")
        for scope in claimed_scopes:
            print(f"   - {scope.replace('https://www.googleapis.com/auth/', '')}")
        print()

        # Ask Google what it thinks about this token
        print("3. Asking Google OAuth to introspect this token...")
        print("   (This shows what Google ACTUALLY allows with this token)")
        print()

        introspect_response = requests.post(
            "https://oauth2.googleapis.com/tokeninfo",
            data={"access_token": access_token},
            timeout=10,
        )

        if introspect_response.status_code != 200:
            print(f"✗ Token introspection failed: {introspect_response.status_code}")
            print(f"Response: {introspect_response.text}")
            return 1

        introspect_data = introspect_response.json()

        print("=" * 80)
        print("GOOGLE'S VIEW OF YOUR TOKEN")
        print("=" * 80)
        print()
        print(json.dumps(introspect_data, indent=2))
        print()

        # Parse the scope field
        google_scopes = introspect_data.get("scope", "").split()

        print("=" * 80)
        print("ANALYSIS")
        print("=" * 80)
        print()
        print(f"Scopes Google recognizes for this token: {len(google_scopes)}")
        for scope in google_scopes:
            print(f"   ✓ {scope.replace('https://www.googleapis.com/auth/', '')}")
        print()

        # Check for specific Gmail scopes
        has_modify = any("gmail.modify" in s for s in google_scopes)
        has_readonly = any("gmail.readonly" in s for s in google_scopes)
        has_metadata = any("gmail.metadata" in s for s in google_scopes)

        print("Gmail scope status:")
        print(f"   gmail.modify:   {'✓ RECOGNIZED' if has_modify else '✗ NOT RECOGNIZED'}")
        print(f"   gmail.readonly: {'✓ RECOGNIZED' if has_readonly else '✗ NOT RECOGNIZED'}")
        print(f"   gmail.metadata: {'✓ RECOGNIZED' if has_metadata else '✗ NOT RECOGNIZED'}")
        print()

        # Check expiration
        expires_in = introspect_data.get("expires_in")
        if expires_in:
            print(f"Token expires in: {expires_in} seconds ({expires_in // 60} minutes)")
        print()

        # Diagnosis
        print("=" * 80)
        print("DIAGNOSIS")
        print("=" * 80)
        print()

        if has_modify and has_readonly:
            print("✓ Google RECOGNIZES full Gmail scopes!")
            print()
            print("This means:")
            print("  - The token should work for reading full emails")
            print("  - The OAuth consent screen is properly configured")
            print("  - The issue must be something else")
            print()
            print("Possible causes:")
            print("  1. Token needs to be refreshed (try re-authorizing)")
            print("  2. There's a timing/cache issue with Gmail API")
            print("  3. There's an account-level restriction")
            print()
            print("Next steps:")
            print("  - Try clearing your token and re-authorizing completely")
            print("  - Check if your Google account has 2FA or advanced protection")

        elif has_metadata and not has_modify and not has_readonly:
            print("✗ Google ONLY recognizes gmail.metadata scope!")
            print()
            print("This means:")
            print("  - OAuth granted the token with all scopes")
            print("  - But Google backend is restricting it to metadata only")
            print("  - This is a verification/restriction issue")
            print()
            print("Likely causes:")
            print("  1. App not verified for restricted scopes")
            print("  2. OAuth consent screen in Testing mode with restrictions")
            print("  3. Google account has security policies blocking")
            print()
            print("Next steps:")
            print("  - Check OAuth Consent Screen 'Publishing status'")
            print("  - Check if app needs verification for restricted scopes")
            print("  - Try publishing the app (may require verification)")
        else:
            print("⚠ Partial scope recognition")
            print("Some scopes are recognized but not all. This is unusual.")

        print()
        print("=" * 80)

        return 0

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
