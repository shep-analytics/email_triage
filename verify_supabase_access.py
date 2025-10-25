#!/usr/bin/env python3
"""
Verify Supabase access to gmail_tokens table from production perspective.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from keys import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
import requests

def main():
    print("=" * 80)
    print("VERIFYING SUPABASE ACCESS TO gmail_tokens TABLE")
    print("=" * 80)
    print(f"\nDatabase: {SUPABASE_URL}")
    print(f"Using service role key: {SUPABASE_SERVICE_ROLE_KEY[:20]}...\n")

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    # Test 1: Check if table exists in schema
    print("=" * 80)
    print("TEST 1: Verify gmail_tokens table exists")
    print("=" * 80)

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/gmail_tokens",
            params={"select": "*", "limit": 1},
            headers=headers,
            timeout=10,
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Body: {response.text}\n")

        if response.status_code == 200:
            print("✓ Table EXISTS and is accessible")
        elif response.status_code == 404:
            print("✗ Table NOT FOUND or not accessible")
            print("  This is the same error production is seeing!")
        else:
            print(f"⚠ Unexpected status: {response.status_code}")

    except Exception as e:
        print(f"✗ Error: {e}")

    # Test 2: Query for specific email (same as production does)
    print("\n" + "=" * 80)
    print("TEST 2: Query for alexsheppert@gmail.com (same as production)")
    print("=" * 80)

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/gmail_tokens",
            params={
                "email": "eq.alexsheppert@gmail.com",
                "select": "token_json",
                "limit": 1
            },
            headers=headers,
            timeout=10,
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500] if len(response.text) > 500 else response.text}\n")

        if response.status_code == 200:
            data = response.json()
            if data:
                print(f"✓ Found {len(data)} record(s)")
                token_json = json.loads(data[0]["token_json"])
                scopes = token_json.get("scopes", [])
                print(f"  Scopes: {len(scopes)}")
                for scope in scopes:
                    print(f"    - {scope.replace('https://www.googleapis.com/auth/', '')}")
            else:
                print("⚠ Query succeeded but returned empty array")
                print("  Table exists but no matching record found")
        elif response.status_code == 404:
            print("✗ 404 ERROR - Same as production!")
            error = response.json() if response.text else {}
            print(f"  Error code: {error.get('code')}")
            print(f"  Message: {error.get('message')}")
            print(f"  Hint: {error.get('hint')}")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

    # Test 3: Check table schema/info
    print("\n" + "=" * 80)
    print("TEST 3: List all available tables")
    print("=" * 80)

    try:
        # Use OpenAPI endpoint to see available tables
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/",
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            swagger = response.json()
            tables = list(swagger.get("paths", {}).keys())
            print(f"Found {len(tables)} table(s):")
            for table in sorted(tables):
                if table != "/":
                    print(f"  - {table}")

            if "/gmail_tokens" in tables:
                print("\n✓ gmail_tokens IS in the schema!")
            else:
                print("\n✗ gmail_tokens NOT in the schema")
                print("  The table might not be created or cache needs refresh")

    except Exception as e:
        print(f"✗ Error: {e}")

    # Test 4: Check RLS policies
    print("\n" + "=" * 80)
    print("TEST 4: Row Level Security (RLS) Information")
    print("=" * 80)
    print("\nNote: Service role key should BYPASS all RLS policies.")
    print("If getting 404 with service role key, it's a schema/cache issue, not RLS.\n")

    # Test 5: Direct insert test
    print("=" * 80)
    print("TEST 5: Test write access (will cleanup after)")
    print("=" * 80)

    test_email = "test_diagnostic@example.com"
    test_token = json.dumps({"test": "data", "scopes": []})

    try:
        # Try to insert a test record
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/gmail_tokens",
            headers={**headers, "Prefer": "return=minimal,resolution=merge-duplicates"},
            json={"email": test_email, "token_json": test_token},
            timeout=10,
        )

        print(f"Insert Status: {response.status_code}")

        if response.status_code in [200, 201, 204]:
            print("✓ Write access works")

            # Cleanup - delete test record
            delete_response = requests.delete(
                f"{SUPABASE_URL}/rest/v1/gmail_tokens",
                params={"email": f"eq.{test_email}"},
                headers=headers,
                timeout=10,
            )
            print(f"Cleanup Status: {delete_response.status_code}")

        elif response.status_code == 404:
            print("✗ Write failed with 404 - table doesn't exist or is inaccessible")
        else:
            print(f"⚠ Unexpected status: {response.status_code}")
            print(f"Response: {response.text}")

    except Exception as e:
        print(f"✗ Error: {e}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("""
If all tests show 404:
  → The gmail_tokens table was not created successfully
  → Run the CREATE TABLE SQL in Supabase SQL Editor again
  → Make sure you're in the right project

If writes work but reads get 404:
  → RLS policy issue (unlikely with service role key)
  → Schema cache issue (restart Supabase or wait a few minutes)

If local works but production fails:
  → Production might be using different credentials
  → Check Cloud Run secret environment variables
""")

if __name__ == "__main__":
    main()
