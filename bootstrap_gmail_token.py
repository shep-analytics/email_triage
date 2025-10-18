"""
Bootstrap OAuth tokens for Gmail accounts.

Usage:
    python3 bootstrap_gmail_token.py you@example.com
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gmail_watch import build_gmail_service

# Will pick the first existing file from this list unless --client-secret is provided.
PREFERRED_CLIENT_SECRETS = [
    Path("client_secret.json"),
    Path("client_secret_desktop.json"),
    Path("client_secret_web.json"),
]
DEFAULT_TOKEN_DIR = Path(".gmail_tokens")


def sanitize_email(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Gmail OAuth flow and save a refresh token for an account.",
    )
    parser.add_argument("email", help="Gmail address to authorise.")
    parser.add_argument(
        "--client-secret",
        default="auto",
        help="Path to the OAuth client secret JSON (default: auto-detect).",
    )
    parser.add_argument(
        "--token-dir",
        default=str(DEFAULT_TOKEN_DIR),
        help=f"Directory to store generated token files (default: {DEFAULT_TOKEN_DIR}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the existing token file if present.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.client_secret == "auto":
        candidate = next((cand for cand in PREFERRED_CLIENT_SECRETS if cand.exists()), None)
        if not candidate:
            print(
                "No client secret found. Provide --client-secret or place a file named "
                f"one of {[p.name for p in PREFERRED_CLIENT_SECRETS]} in the project root.",
                file=sys.stderr,
            )
            return 1
        client_secret_path = candidate.expanduser().resolve()
    else:
        client_secret_path = Path(args.client_secret).expanduser().resolve()
    if not client_secret_path.exists():
        print(f"Client secret JSON not found at {client_secret_path}", file=sys.stderr)
        return 1

    token_dir = Path(args.token_dir).expanduser().resolve()
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / f"token_{sanitize_email(args.email)}.json"

    if token_path.exists() and not args.force:
        print(f"Token already exists at {token_path}. Use --force to regenerate.", file=sys.stderr)
        return 1

    build_gmail_service(
        oauth_client_secret=str(client_secret_path),
        oauth_token_file=str(token_path),
    )
    print(f"Saved token for {args.email} to {token_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
