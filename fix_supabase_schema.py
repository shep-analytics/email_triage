#!/usr/bin/env python3
"""
Create the missing gmail_tokens table in Supabase.
This table is required for storing OAuth tokens from the web "Connect Gmail" flow.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from keys import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
import requests

def create_gmail_tokens_table():
    """Create the gmail_tokens table via Supabase SQL API."""

    print("Creating gmail_tokens table in Supabase...")
    print(f"Database: {SUPABASE_URL}\n")

    # SQL to create the table
    sql = """
    CREATE TABLE IF NOT EXISTS gmail_tokens (
        email TEXT PRIMARY KEY,
        token_json JSONB NOT NULL,
        scopes TEXT[] NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Create an index on email for faster lookups
    CREATE INDEX IF NOT EXISTS idx_gmail_tokens_email ON gmail_tokens(email);

    -- Create an index on updated_at for monitoring token freshness
    CREATE INDEX IF NOT EXISTS idx_gmail_tokens_updated_at ON gmail_tokens(updated_at);
    """

    # Note: Supabase doesn't expose a direct SQL endpoint via REST API
    # We need to use the Database UI or connect via PostgreSQL directly

    print("=" * 80)
    print("MANUAL ACTION REQUIRED")
    print("=" * 80)
    print("\nThe gmail_tokens table must be created via Supabase SQL Editor.\n")
    print("Steps:")
    print("1. Go to your Supabase project dashboard:")
    print(f"   {SUPABASE_URL.replace('/rest/v1', '')}")
    print("\n2. Navigate to: SQL Editor (left sidebar)")
    print("\n3. Click 'New query' and paste this SQL:\n")
    print("-" * 80)
    print(sql)
    print("-" * 80)
    print("\n4. Click 'Run' to execute the SQL")
    print("\n5. Verify the table was created:")
    print("   - Go to 'Table Editor' (left sidebar)")
    print("   - You should see 'gmail_tokens' in the list")
    print("\n6. After creating the table, complete OAuth again:")
    print("   - Go to https://inboximp.com or your production site")
    print("   - Log in with your Google account")
    print("   - Click 'Connect Gmail'")
    print("   - Grant all requested permissions")
    print("   - The token will now be saved successfully!")
    print("\n" + "=" * 80)

    # Verify we can access Supabase
    print("\nVerifying Supabase connection...")
    try:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/mailboxes",
            params={"limit": 1},
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            print("✓ Supabase connection successful")
        else:
            print(f"⚠ Supabase returned status {response.status_code}")
    except Exception as e:
        print(f"⚠ Error connecting to Supabase: {e}")

    print("\n" + "=" * 80)
    print("ALTERNATIVE: Use psql command line")
    print("=" * 80)
    print("\nIf you have PostgreSQL client installed, you can also run:")
    print(f"\npsql '{SUPABASE_URL.replace('/rest/v1', '')}' -c \"{sql.strip()}\"")
    print("\n(You'll need the connection string from Supabase Settings > Database)")

if __name__ == "__main__":
    create_gmail_tokens_table()
