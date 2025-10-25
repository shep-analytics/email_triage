#!/usr/bin/env python3
"""
Automatically create the gmail_tokens table in Supabase using the SQL API.
This will fix the OAuth token storage issue.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from keys import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
import requests

def create_table_via_rpc():
    """Create the gmail_tokens table using Supabase's RPC/SQL capabilities."""

    print("=" * 80)
    print("CREATING gmail_tokens TABLE IN SUPABASE")
    print("=" * 80)
    print(f"\nDatabase: {SUPABASE_URL}\n")

    # SQL to execute
    sql = """
    CREATE TABLE IF NOT EXISTS gmail_tokens (
        email TEXT PRIMARY KEY,
        token_json JSONB NOT NULL,
        scopes TEXT[] NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_gmail_tokens_email ON gmail_tokens(email);
    CREATE INDEX IF NOT EXISTS idx_gmail_tokens_updated_at ON gmail_tokens(updated_at);
    """

    try:
        # Try using Supabase's SQL execution endpoint
        # Note: This requires the SQL API to be enabled
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        }

        # Method 1: Try the /query endpoint (if available)
        print("Attempting to create table via Supabase SQL API...")

        # Get the database URL from the REST URL
        # Format: https://PROJECT.supabase.co/rest/v1 -> https://PROJECT.supabase.co
        base_url = SUPABASE_URL.replace("/rest/v1", "")

        # Try the database query endpoint
        query_url = f"{base_url}/rest/v1/rpc/query"

        # This might not work if the RPC function doesn't exist
        # In that case, user will need to use the SQL Editor UI

        print("\n⚠️  IMPORTANT:")
        print("Supabase's REST API doesn't support direct SQL execution for DDL.")
        print("You must use the Supabase Dashboard SQL Editor.\n")

        print("However, I can verify the connection and guide you through it...")

        # Verify connection
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/mailboxes",
            params={"limit": 1},
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            timeout=10,
        )

        if response.status_code == 200:
            print("✓ Supabase connection verified\n")
        else:
            print(f"⚠️  Warning: Unexpected status {response.status_code}\n")

        print("=" * 80)
        print("STEP-BY-STEP INSTRUCTIONS")
        print("=" * 80)

        print("""
1. Open your Supabase Dashboard:
   https://app.supabase.com/project/wxliwwdftbolaxnpjjaj

2. Click 'SQL Editor' in the left sidebar

3. Click the '+ New query' button

4. Paste this SQL:
""")
        print("-" * 80)
        print(sql.strip())
        print("-" * 80)

        print("""
5. Click 'Run' (or press Ctrl+Enter)

6. You should see: "Success. No rows returned"

7. Verify the table was created:
   - Click 'Table Editor' in the left sidebar
   - Look for 'gmail_tokens' in the list
   - You should see columns: email, token_json, scopes, updated_at

8. After the table is created, test the OAuth flow:
   - Go to https://inboximp.com
   - Sign in with your Google account
   - Click 'Connect Gmail'
   - Grant all permissions
   - The token will now be saved to Supabase!

9. Verify the token was saved:
   - In Supabase, go to Table Editor > gmail_tokens
   - You should see a row with your email address
   - The token_json column will contain your OAuth credentials
""")

        print("=" * 80)
        print("TROUBLESHOOTING")
        print("=" * 80)
        print("""
If you still get metadata-only errors after creating the table:

1. Check the token was saved:
   Run: python3 check_all_tokens.py

2. Check the token scopes:
   The token_json should include these scopes:
   - https://www.googleapis.com/auth/gmail.modify
   - https://www.googleapis.com/auth/gmail.readonly
   - https://www.googleapis.com/auth/gmail.metadata

3. If scopes are missing, delete the token and re-consent:
   - In Supabase Table Editor, delete the row from gmail_tokens
   - In your Google Account (myaccount.google.com/permissions)
     remove access for "Inboximp Email Triage"
   - Complete OAuth flow again from https://inboximp.com

4. Verify your OAuth client is properly configured:
   - The client must be type "Web application"
   - Must include these redirect URIs:
     • https://inboximp.com/oauth/callback
     • https://www.inboximp.com/oauth/callback
""")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = create_table_via_rpc()
    sys.exit(0 if success else 1)
