import argparse
import json
import os

# Ensure interactive OAuth is allowed for this one-shot CLI run
os.environ.setdefault("GMAIL_ALLOW_OAUTH_FLOW", "1")
os.environ.setdefault("GMAIL_AUTO_REAUTH", "1")

# Reuse the configured processor and Telegram defaults from the FastAPI app
from app import processor, telegram_chat_id, telegram_token  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot Gmail inbox cleanup (batched).")
    parser.add_argument("email", help="Target Gmail address")
    parser.add_argument("--batch-size", type=int, default=50, help="Messages per batch (default: 50)")
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Do not wait for Telegram confirmation between batches.",
    )
    parser.add_argument("--telegram-token", help="Override Telegram bot token")
    parser.add_argument("--telegram-chat-id", help="Override Telegram chat id")

    args = parser.parse_args()

    result = processor.clear_inbox(
        args.email,
        batch_size=args.batch_size,
        await_user_confirmation=not args.no_confirm,
        telegram_token=args.telegram_token or telegram_token,
        telegram_chat_id=args.telegram_chat_id or telegram_chat_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
