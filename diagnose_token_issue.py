#!/usr/bin/env python3
"""
Diagnostic script to identify Gmail token scope issues.

This script will:
1. Check the filesystem token and its scopes
2. Check the Supabase-stored token and its scopes
3. Compare them to identify mismatches
4. Show you exactly which token is being used and why metadata-only access is occurring
"""

import json
import os
import sys
from pathlib import Path

# Add current directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent))

from supabase_state import get_state_store
from config import GMAIL_ACCOUNTS, GMAIL_OAUTH_TOKEN_DIR

def check_token_scopes(token_json_str: str, source: str) -> dict:
    """Parse token JSON and extract scope information."""
    try:
        token_data = json.loads(token_json_str)
        scopes = token_data.get("scopes", [])

        print(f"\n{'='*80}")
        print(f"TOKEN SOURCE: {source}")
        print(f"{'='*80}")

        print(f"Scopes present: {len(scopes)}")
        for scope in scopes:
            scope_short = scope.replace("https://www.googleapis.com/auth/", "")
            print(f"  - {scope_short}")

        # Check for specific scopes
        has_modify = any("gmail.modify" in s for s in scopes)
        has_readonly = any("gmail.readonly" in s for s in scopes)
        has_metadata = any("gmail.metadata" in s for s in scopes)

        print(f"\nScope Analysis:")
        print(f"  gmail.modify:   {'✓ YES' if has_modify else '✗ NO'}")
        print(f"  gmail.readonly: {'✓ YES' if has_readonly else '✗ NO'}")
        print(f"  gmail.metadata: {'✓ YES' if has_metadata else '✗ NO'}")

        # Token expiry
        expiry = token_data.get("expiry", "Unknown")
        print(f"\nToken expiry: {expiry}")

        return {
            "scopes": scopes,
            "has_modify": has_modify,
            "has_readonly": has_readonly,
            "has_metadata": has_metadata,
            "token_data": token_data,
        }
    except json.JSONDecodeError as e:
        print(f"\n⚠️  ERROR: Invalid JSON in {source}")
        print(f"   {e}")
        return None
    except Exception as e:
        print(f"\n⚠️  ERROR analyzing {source}: {e}")
        return None


def main():
    print("=" * 80)
    print("GMAIL TOKEN SCOPE DIAGNOSTIC TOOL")
    print("=" * 80)

    # Get the email to check (use first account from config)
    if not GMAIL_ACCOUNTS:
        print("\n❌ ERROR: No Gmail accounts configured in config.py")
        return 1

    email = GMAIL_ACCOUNTS[0]
    print(f"\nChecking tokens for: {email}")

    # Check 1: Filesystem token
    token_dir = Path(GMAIL_OAUTH_TOKEN_DIR)
    token_filename = f"token_{email.replace('@', '_at_').replace('.', '_')}.json"
    token_path = token_dir / token_filename

    print(f"\n{'─'*80}")
    print("STEP 1: Checking filesystem token")
    print(f"{'─'*80}")
    print(f"Token path: {token_path}")

    filesystem_result = None
    if token_path.exists():
        print("Status: ✓ File exists")
        try:
            token_json = token_path.read_text(encoding="utf-8")
            filesystem_result = check_token_scopes(token_json, "FILESYSTEM")
        except Exception as e:
            print(f"⚠️  ERROR reading file: {e}")
    else:
        print("Status: ✗ File does not exist")

    # Check 2: Supabase token
    print(f"\n{'─'*80}")
    print("STEP 2: Checking Supabase-stored token")
    print(f"{'─'*80}")

    supabase_result = None
    try:
        # Get Supabase credentials
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not supabase_url or not supabase_key:
            print("⚠️  WARNING: Supabase credentials not found in environment")
            print("   Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables")
            print("   Skipping Supabase check...")
        else:
            print(f"Supabase URL: {supabase_url}")

            # Initialize state store
            state_store = get_state_store(url=supabase_url, service_role_key=supabase_key)

            # Try to get token from Supabase
            token_json = state_store.get_gmail_token(email=email)

            if token_json:
                print("Status: ✓ Token found in Supabase")
                supabase_result = check_token_scopes(token_json, "SUPABASE DATABASE")
            else:
                print("Status: ✗ No token found in Supabase for this email")

    except Exception as e:
        print(f"⚠️  ERROR checking Supabase: {e}")
        import traceback
        traceback.print_exc()

    # Final Analysis
    print(f"\n{'='*80}")
    print("DIAGNOSIS")
    print(f"{'='*80}")

    if not filesystem_result and not supabase_result:
        print("\n❌ CRITICAL: No valid tokens found!")
        print("   Action: Run the OAuth flow to create a fresh token")
        return 1

    # Determine which token the app will use
    if supabase_result:
        print("\n⚠️  IMPORTANT: App will prioritize SUPABASE token over filesystem token")
        active_token = "SUPABASE"
        active_result = supabase_result
    elif filesystem_result:
        print("\n✓ App will use FILESYSTEM token (no Supabase token found)")
        active_token = "FILESYSTEM"
        active_result = filesystem_result

    # Check if active token has required scopes
    print(f"\nActive token source: {active_token}")

    if active_result["has_modify"] or active_result["has_readonly"]:
        print("✓ Active token HAS read/modify permissions - should work correctly!")

        if supabase_result and filesystem_result:
            print("\n📋 Note: Both tokens exist. Comparing...")
            if supabase_result["scopes"] != filesystem_result["scopes"]:
                print("⚠️  WARNING: Scope mismatch between filesystem and Supabase tokens!")
                print("   This might cause confusion during development.")
    else:
        print("❌ Active token ONLY has metadata scope - this is your problem!")
        print("\n🔧 SOLUTIONS:")
        print("   1. Delete the old Supabase token (see delete command below)")
        print("   2. Use the 'Connect Gmail' button in the web UI to re-consent")
        print("   3. The new token with full scopes will be stored in Supabase")

        if supabase_result and not supabase_result["has_modify"]:
            print("\n💡 Quick fix - Delete the Supabase token:")
            print(f'   Run this Python command:')
            print(f'   >>> from supabase_state import get_state_store')
            print(f'   >>> import os')
            print(f'   >>> store = get_state_store(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))')
            print(f'   >>> # Delete the old token')
            print(f'   >>> store.session.delete(store._rest("gmail_tokens"), params={{"email": "eq.{email}"}}, headers=store._headers)')
            print(f'   Then re-consent via the web UI.')

    return 0


if __name__ == "__main__":
    sys.exit(main())
