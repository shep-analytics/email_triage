#!/usr/bin/env python3
"""Check all Gmail tokens in Supabase database."""

import json
import os
import sys
import requests
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from keys import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

def main():
    print("Querying all Gmail tokens from Supabase...")
    print(f"Database: {SUPABASE_URL}")

    try:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/gmail_tokens",
            params={"select": "email,token_json"},
            headers=headers,
            timeout=30,
        )

        if response.status_code == 200:
            tokens = response.json()
            print(f"\nFound {len(tokens)} token(s) in database:\n")

            if not tokens:
                print("❌ NO TOKENS FOUND IN DATABASE!")
                print("\nThis explains why you're getting metadata-only errors.")
                print("The web OAuth flow should be saving tokens to Supabase, but it's not happening.")
                return

            for i, token_row in enumerate(tokens, 1):
                email = token_row.get("email", "Unknown")
                token_json_str = token_row.get("token_json", "{}")

                print(f"{'='*80}")
                print(f"Token #{i}: {email}")
                print(f"{'='*80}")

                try:
                    token_data = json.loads(token_json_str)
                    scopes = token_data.get("scopes", [])

                    print(f"Scopes ({len(scopes)}):")
                    for scope in scopes:
                        scope_short = scope.replace("https://www.googleapis.com/auth/", "")
                        print(f"  - {scope_short}")

                    # Check specific scopes
                    has_modify = any("gmail.modify" in s for s in scopes)
                    has_readonly = any("gmail.readonly" in s for s in scopes)
                    has_metadata = any("gmail.metadata" in s for s in scopes)

                    print(f"\nScope check:")
                    print(f"  gmail.modify:   {'✓' if has_modify else '✗'}")
                    print(f"  gmail.readonly: {'✓' if has_readonly else '✗'}")
                    print(f"  gmail.metadata: {'✓' if has_metadata else '✗'}")

                    if not has_modify and not has_readonly and has_metadata:
                        print("\n⚠️  THIS TOKEN IS METADATA-ONLY! This is causing your issue.")

                    expiry = token_data.get("expiry", "Unknown")
                    print(f"\nExpiry: {expiry}")

                except json.JSONDecodeError:
                    print("⚠️  ERROR: Invalid JSON in token_json field")

                print()
        else:
            print(f"❌ Error querying database: {response.status_code}")
            print(f"Response: {response.text}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
