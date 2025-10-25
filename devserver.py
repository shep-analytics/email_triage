from __future__ import annotations

import os
import uvicorn

from logging_utils import configure_logging


def _env_flag(name: str, default: str = "1") -> bool:
    value = os.getenv(name, default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    log_path = configure_logging()
    if log_path:
        print(f"Logging to {log_path}")

    # Use localhost by default to match common Google OAuth JS origin allowlists
    host = os.getenv("EMAIL_TRIAGE_DEV_HOST", "localhost")
    port = int(os.getenv("EMAIL_TRIAGE_DEV_PORT", "8000"))
    reload = _env_flag("EMAIL_TRIAGE_DEV_RELOAD", "1")
    log_level = os.getenv("EMAIL_TRIAGE_DEV_LOG_LEVEL", "info")

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
