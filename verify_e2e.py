#!/usr/bin/env python3
"""
End-to-end verification script for the email triage service.

This script:
 1) Builds and deploys to Cloud Run (via gcloud) using a service account key
 2) Ensures Pub/Sub topic + push subscription are configured
 3) Registers Gmail watches by calling the service /gmail/watch
 4) Exercises the /dry-run endpoint to validate LLM + plumbing
 5) Optionally injects a test email via Gmail API insert (if permitted)
 6) Triggers a fake Pub/Sub push to process new Gmail history
 7) Polls Supabase for the processed message decision
 8) Invokes /alerts/digest to flush queued alert_today items

Requirements:
 - gcloud CLI installed
 - Service account key JSON (default: email-assistant-service-key.json)
 - config.py populated (GMAIL_ACCOUNTS, GMAIL_TOPIC_NAME, SUPABASE creds)
 - OAuth token present for the test mailbox under .gmail_tokens/

Usage:
  python3 verify_e2e.py \
    --key-file email-assistant-service-key.json \
    --region us-central1 \
    --service email-triage \
    --subscription email-triage-push \
    --email alexsheppert@gmail.com \
    [--push-endpoint https://inboximp.com/gmail/push]

Notes:
 - If Gmail API insert lacks permission, the script will skip message injection
   and ask you to send a manual test email, then it will still trigger processing.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests

import config  # type: ignore
from gmail_watch import build_gmail_service


def run(cmd: list[str], check: bool = True, *, stream: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    if stream:
        return subprocess.run(cmd, check=check, text=False)
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
    return proc


_LOG_STREAMING_ERROR = "This tool can only stream logs"
_BUILD_REF_PATTERN = re.compile(r"/locations/([A-Za-z0-9_-]+)/builds/([A-Za-z0-9_-]+)")
_TERMINAL_BUILD_STATUSES = {"SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED", "EXPIRED"}


def _extract_build_ref(output: str) -> Optional[tuple[str, str]]:
    match = _BUILD_REF_PATTERN.search(output)
    if not match:
        return None
    return match.group(1), match.group(2)


def _wait_for_cloud_build(build_id: str, *, region: str = "global", poll_interval: float = 5.0, timeout: float = 900.0) -> None:
    """Poll Cloud Build status when streaming logs is disallowed."""
    print(f"Waiting for Cloud Build {build_id} to finish (log streaming unavailable).")
    deadline = time.time() + timeout
    last_status: Optional[str] = None
    log_url: Optional[str] = None

    while True:
        try:
            proc = subprocess.run(
                [
                    "gcloud",
                    "builds",
                    "describe",
                    build_id,
                    "--region",
                    region,
                    "--format=json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to poll Cloud Build {build_id} status") from exc

        raw = proc.stdout.strip()
        try:
            data: Dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}

        status = data.get("status")
        log_url = data.get("logUrl") or log_url

        if status and status != last_status:
            print(f"Cloud Build status: {status}")
            last_status = status

        if status == "SUCCESS":
            if log_url:
                print(f"Cloud Build logs: {log_url}")
            return

        if status in _TERMINAL_BUILD_STATUSES and status != "SUCCESS":
            if log_url:
                print(f"Cloud Build logs: {log_url}")
            raise RuntimeError(f"Cloud Build {build_id} finished with status {status}")

        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for Cloud Build {build_id}; last status: {status or 'UNKNOWN'}")

        time.sleep(poll_interval)


def gcloud_project_from_key(key_path: Path) -> str:
    data = json.loads(key_path.read_text(encoding="utf-8"))
    return data["project_id"]


def _active_gcloud_account() -> str:
    try:
        proc = subprocess.run(
            ["gcloud", "config", "get-value", "account"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return "(unknown)"
    return proc.stdout.strip() or "(unknown)"


def _is_permission_denied(exc: subprocess.CalledProcessError) -> bool:
    error_text = " ".join(
        part
        for part in (
            getattr(exc, "stderr", ""),
            getattr(exc, "output", ""),
            getattr(exc, "stdout", ""),
        )
        if part
    ).lower()
    if not error_text:
        return False
    return "permission denied" in error_text or "user not authorized" in error_text


def _report_pubsub_permission(action: str) -> None:
    account = _active_gcloud_account()
    print(
        f"Insufficient Pub/Sub permissions to {action}. "
        f"Active gcloud account: {account}. "
        "Grant Pub/Sub admin/editor rights to this service account or create the resources manually and rerun with --skip-deploy.",
        file=sys.stderr,
    )


def gcloud_setup(key_path: Path, project_id: str) -> None:
    run(["gcloud", "auth", "activate-service-account", f"--key-file={str(key_path)}"])  # login
    run(["gcloud", "config", "set", "project", project_id])
    # Ensure required services are enabled
    run(["gcloud", "services", "enable", "run.googleapis.com", "pubsub.googleapis.com"])  # gmail api not needed for Cloud Run


def gcloud_setup_active(project_id: str) -> None:
    """Setup gcloud using the currently active gcloud authentication."""
    run(["gcloud", "config", "set", "project", project_id])
    # Ensure required services are enabled
    run(["gcloud", "services", "enable", "run.googleapis.com", "pubsub.googleapis.com"])


def build_and_deploy(service: str, region: str, project_id: str) -> str:
    image = f"gcr.io/{project_id}/{service}"
    # Build with Cloud Build
    # Suppress log streaming to avoid permission/VPC-SC errors while still
    # waiting for the build to finish.
    build_cmd = ["gcloud", "builds", "submit", "--tag", image, "--suppress-logs"]
    print("+", " ".join(build_cmd))
    try:
        proc = subprocess.run(build_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        combined_output = (exc.stdout or "") + (exc.stderr or "")
        if exc.stdout:
            sys.stdout.write(exc.stdout)
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        if _LOG_STREAMING_ERROR in combined_output:
            ref = _extract_build_ref(combined_output)
            if not ref:
                raise
            build_region, build_id = ref
            _wait_for_cloud_build(build_id, region=build_region)
        else:
            raise
    else:
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
    # Deploy to Cloud Run
    run([
        "gcloud",
        "run",
        "deploy",
        service,
        "--image",
        image,
        "--region",
        region,
        "--platform",
        "managed",
        "--allow-unauthenticated",
    ])
    # Get service URL
    cp = subprocess.run(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service,
            "--region",
            region,
            "--format",
            "value(status.url)",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    url = cp.stdout.strip()
    print("Cloud Run URL:", url)
    return url


def ensure_pubsub(topic: str, subscription: str, push_endpoint: str) -> bool:
    # Create topic if missing
    try:
        run(["gcloud", "pubsub", "topics", "describe", topic], stream=False)
    except subprocess.CalledProcessError as exc:
        if _is_permission_denied(exc):
            _report_pubsub_permission(f"describe topic {topic}")
            return False
        try:
            run(["gcloud", "pubsub", "topics", "create", topic], stream=False)
        except subprocess.CalledProcessError as create_exc:
            if _is_permission_denied(create_exc):
                _report_pubsub_permission(f"create topic {topic}")
                return False
            raise

    # Grant gmail publisher to topic
    try:
        run(
            [
                "gcloud",
                "pubsub",
                "topics",
                "add-iam-policy-binding",
                topic,
                "--member=serviceAccount:gmail-api-push@system.gserviceaccount.com",
                "--role=roles/pubsub.publisher",
            ],
            stream=False,
        )
    except subprocess.CalledProcessError as exc:
        if _is_permission_denied(exc):
            _report_pubsub_permission(f"update IAM policy on topic {topic}")
            return False
        raise

    # Create or update push subscription
    # Try to create first; if exists, update push endpoint
    try:
        run(
            [
                "gcloud",
                "pubsub",
                "subscriptions",
                "create",
                subscription,
                "--topic",
                topic,
                "--push-endpoint",
                push_endpoint,
            ],
            stream=False,
        )
    except subprocess.CalledProcessError as exc:
        if _is_permission_denied(exc):
            _report_pubsub_permission(f"create subscription {subscription}")
            return False
        try:
            run(
                [
                    "gcloud",
                    "pubsub",
                    "subscriptions",
                    "update",
                    subscription,
                    "--push-endpoint",
                    push_endpoint,
                ],
                stream=False,
            )
        except subprocess.CalledProcessError as update_exc:
            if _is_permission_denied(update_exc):
                _report_pubsub_permission(f"update subscription {subscription}")
                return False
            raise

    return True


def ensure_scheduler_job(*, name: str, url: str, schedule: str, method: str = "POST", location: str = "us-central1", time_zone: str = "UTC") -> bool:
    """Create or update a Cloud Scheduler HTTP job pointing to the given URL."""
    # Enable API lazily here as well to be safe
    try:
        run(["gcloud", "services", "enable", "cloudscheduler.googleapis.com"], stream=False)
    except subprocess.CalledProcessError:
        # Non-fatal; continue and let job creation fail if truly disabled
        pass

    def _exists() -> bool:
        try:
            run(["gcloud", "scheduler", "jobs", "describe", name, "--location", location], stream=False)
            return True
        except subprocess.CalledProcessError:
            return False

    if not _exists():
        try:
            run([
                "gcloud", "scheduler", "jobs", "create", "http", name,
                "--location", location,
                "--schedule", schedule,
                "--time-zone", time_zone,
                "--uri", url,
                "--http-method", method,
            ], stream=False)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to create scheduler job {name}: {exc}", file=sys.stderr)
            return False
    else:
        try:
            run([
                "gcloud", "scheduler", "jobs", "update", "http", name,
                "--location", location,
                "--schedule", schedule,
                "--time-zone", time_zone,
                "--uri", url,
                "--http-method", method,
            ], stream=False)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to update scheduler job {name}: {exc}", file=sys.stderr)
            return False
    return True


def call_watch(base_url: str) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/gmail/watch"
    r = requests.post(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("/gmail/watch:", json.dumps(data, indent=2))
    return data


def call_healthz(base_url: str) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    # Prefer /health (Cloud Run may intercept /healthz at the edge)
    for path in ("/health", "/healthz"):
        url = base + path
        r = requests.get(url, timeout=30)
        if r.status_code == 404:
            # Try next path
            continue
        r.raise_for_status()
        data = r.json()
        print(f"{path}:", json.dumps(data, indent=2))
        return data
    # Last attempt raised 404; raise an explicit error
    raise requests.HTTPError(f"Health endpoint not found at {base}/health or {base}/healthz")


def call_dry_run(base_url: str) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/dry-run"
    payload = {
        "sender": "e2e-bot@example.com",
        "to": ",".join(getattr(config, "GMAIL_ACCOUNTS", [])),
        "subject": "[E2E] Non-urgent: confirm tomorrow",
        "snippet": "Hi Alex, could you review the doc by tomorrow?",
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("/dry-run:", json.dumps(data, indent=2))
    return data


def gmail_insert_message(email: str, subject: str, body: str) -> Optional[str]:
    """Attempt to insert a message into INBOX. Returns message id or None."""
    try:
        service = build_gmail_service(
            oauth_client_secret=str(Path(getattr(config, "GMAIL_CLIENT_SECRET_PATH", "json_keys/client_secret.json")).resolve()),
            oauth_token_file=str(Path(getattr(config, "GMAIL_OAUTH_TOKEN_DIR", ".gmail_tokens")).resolve() / f"token_{email.replace('@','_at_').replace('.','_')}.json"),
        )
    except Exception as exc:
        print("Failed to build Gmail service for insert:", exc)
        return None

    # Construct RFC822
    rfc822 = (
        f"From: e2e-bot@example.com\r\n"
        f"To: {email}\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        f"{body}\r\n"
    ).encode("utf-8")
    raw = base64.urlsafe_b64encode(rfc822).decode("ascii")

    try:
        msg = (
            service.users()
            .messages()
            .insert(userId=email, body={"labelIds": ["INBOX"], "raw": raw})
            .execute()
        )
        msg_id = msg.get("id")
        print("Inserted test message:", msg_id)
        return msg_id
    except Exception as exc:
        print("Gmail insert not permitted or failed:", exc)
        return None


def trigger_push(base_url: str, email: str) -> None:
    url = base_url.rstrip("/") + "/gmail/push"
    # Simulate Pub/Sub envelope with Gmail notification payload
    notif = {"emailAddress": email, "historyId": "0"}
    data_b64 = base64.b64encode(json.dumps(notif).encode("utf-8")).decode("ascii")
    envelope = {"message": {"data": data_b64}}
    r = requests.post(url, json=envelope, timeout=60)
    r.raise_for_status()
    print("Triggered /gmail/push (simulated)")


def supabase_query_messages(supabase_url: str, supabase_key: str, email: str, msg_id: Optional[str]) -> list[dict]:
    headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
    params: Dict[str, str] = {"select": "*", "mailbox_email": f"eq.{email}", "limit": "10"}
    if msg_id:
        params["gmail_id"] = f"eq.{msg_id}"
    r = requests.get(f"{supabase_url}/rest/v1/messages", headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def call_digest(base_url: str) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/alerts/digest"
    r = requests.post(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("/alerts/digest:", json.dumps(data, indent=2))
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify end-to-end triage deployment")
    parser.add_argument("--key-file", default="email-assistant-service-key.json", help="Path to service account key JSON (or use --use-active-gcloud)")
    parser.add_argument("--use-active-gcloud", action="store_true", help="Use currently logged-in gcloud account (skip key auth)")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--service", default="email-triage")
    parser.add_argument("--subscription", default="email-triage-push")
    parser.add_argument("--email", default=(getattr(config, "GMAIL_ACCOUNTS", [""])[0] or ""))
    parser.add_argument("--skip-deploy", action="store_true", help="Assume service already deployed")
    parser.add_argument("--scheduler-location", default="us-central1", help="Cloud Scheduler location")
    parser.add_argument("--scheduler-timezone", default="UTC", help="Cloud Scheduler time zone")
    parser.add_argument("--refresh-cron", default="every 12 hours", help="Watch refresh schedule")
    parser.add_argument("--digest-cron", default="0 17 * * *", help="Daily digest cron expression")
    parser.add_argument("--push-endpoint", default=None, help="Override Pub/Sub push endpoint (e.g., https://inboximp.com/gmail/push)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Determine project ID and setup gcloud
    if args.use_active_gcloud:
        # Use currently active gcloud authentication
        try:
            proc = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                check=True,
                capture_output=True,
                text=True,
            )
            project_id = proc.stdout.strip()
        except subprocess.CalledProcessError:
            project_id = ""
        if not project_id:
            print("No project configured. Run: gcloud config set project <PROJECT_ID> or provide --key-file.", file=sys.stderr)
            return 1
        gcloud_setup_active(project_id)
    else:
        # Use service account key file
        key_path = Path(args.key_file).expanduser().resolve()
        if not key_path.exists():
            print(f"Service account key not found: {key_path}", file=sys.stderr)
            return 1
        project_id = gcloud_project_from_key(key_path)
        gcloud_setup(key_path, project_id)

    if args.skip_deploy:
        # Read current URL
        cp = subprocess.run(
            [
                "gcloud",
                "run",
                "services",
                "describe",
                args.service,
                "--region",
                args.region,
                "--format",
                "value(status.url)",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        base_url = cp.stdout.strip()
    else:
        base_url = build_and_deploy(args.service, args.region, project_id)

    topic = getattr(config, "GMAIL_TOPIC_NAME", None)
    if not topic:
        print("GMAIL_TOPIC_NAME is not set in config.py", file=sys.stderr)
        return 1

    push_endpoint = args.push_endpoint or (base_url.rstrip("/") + "/gmail/push")
    if not ensure_pubsub(topic, args.subscription, push_endpoint):
        return 1

    # Health check and watch
    call_healthz(base_url)
    call_watch(base_url)

    # Ensure Cloud Scheduler jobs for periodic maintenance
    refresh_ok = ensure_scheduler_job(
        name=f"{args.service}-refresh",
        url=base_url.rstrip("/") + "/gmail/watch",
        schedule=args.refresh_cron,
        method="POST",
        location=args.scheduler_location,
        time_zone=args.scheduler_timezone,
    )
    digest_ok = ensure_scheduler_job(
        name=f"{args.service}-digest",
        url=base_url.rstrip("/") + "/alerts/digest",
        schedule=args.digest_cron,
        method="POST",
        location=args.scheduler_location,
        time_zone=args.scheduler_timezone,
    )
    if not (refresh_ok and digest_ok):
        print("Warning: One or more Cloud Scheduler jobs could not be created/updated.", file=sys.stderr)

    # Dry run classification
    call_dry_run(base_url)

    # Attempt to inject a test email (optional)
    unique = uuid.uuid4().hex[:8]
    subject = f"[E2E] Triage test {unique} — please archive"
    body = "This is a non-urgent automated test message to validate triage."
    inserted_id = None
    if args.email:
        inserted_id = gmail_insert_message(args.email, subject, body)
        if not inserted_id:
            print("Skipping injection; please send a manual test email now, then press Enter to continue...")
            try:
                input()
            except EOFError:
                pass

    # Trigger processing via simulated push
    if args.email:
        trigger_push(base_url, args.email)

    # Wait briefly for processing
    time.sleep(5)

    # Query Supabase for recent decisions
    supabase_url = getattr(config, "SUPABASE_URL", "")
    supabase_key = getattr(config, "SUPABASE_SERVICE_ROLE_KEY", "")
    if supabase_url and supabase_key and args.email:
        messages = supabase_query_messages(supabase_url, supabase_key, args.email, inserted_id)
        print("Recent decisions:", json.dumps(messages, indent=2)[:1200])
    else:
        print("Supabase not configured; skipping decision check.")

    # Digest run (will send Telegram if queued items exist)
    try:
        call_digest(base_url)
    except Exception as exc:  # pragma: no cover
        print("Digest call failed:", exc)

    print("E2E verification steps completed.")
    print("Cloud Run:", base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
