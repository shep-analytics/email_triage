from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


LOG_ENV_VAR = "EMAIL_TRIAGE_ACTIVE_LOG"
LOG_DIR_ENV_VAR = "EMAIL_TRIAGE_LOG_DIR"
LOG_LEVEL_ENV_VAR = "EMAIL_TRIAGE_LOG_LEVEL"


def _running_in_cloud() -> bool:
    cloud_markers = (
        "K_SERVICE",
        "CLOUD_RUN_SERVICE",
        "CLOUD_RUN_JOB",
        "GAE_SERVICE",
    )
    return any(os.getenv(marker) for marker in cloud_markers)


def configure_logging() -> Optional[Path]:
    """
    Ensure logging is configured for the current process.

    Returns the active log file path when running locally, otherwise None.
    """
    if getattr(configure_logging, "_configured", False):
        return getattr(configure_logging, "_log_path", None)

    log_path: Optional[Path] = None
    handlers = []

    if _running_in_cloud():
        handlers.append(logging.StreamHandler())
    else:
        log_dir = Path(os.getenv(LOG_DIR_ENV_VAR, "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"email_triage_{timestamp}.log"
        handlers.extend(
            [
                logging.StreamHandler(),
                logging.FileHandler(log_path, mode="w", encoding="utf-8"),
            ]
        )

    log_level_name = os.getenv(LOG_LEVEL_ENV_VAR, "INFO").upper()
    try:
        log_level = getattr(logging, log_level_name)
    except AttributeError:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers or None,
        force=True,
    )

    if log_path:
        os.environ[LOG_ENV_VAR] = str(log_path)

    configure_logging._configured = True  # type: ignore[attr-defined]
    configure_logging._log_path = log_path  # type: ignore[attr-defined]
    return log_path

