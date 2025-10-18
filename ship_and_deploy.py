#!/usr/bin/env python3
"""
One-step helper to:
  1) git add/commit/push the current repo
  2) build + deploy to Cloud Run (via deploy_cloud_run.py)

Usage:
  python3 ship_and_deploy.py \
    --key-file email-assistant-service-key.json \
    --region us-central1 \
    --service email-triage \
    --message "Fix triage restricted fallback"
  # or use your active gcloud session (no key file)
  python3 ship_and_deploy.py \
    --use-active-gcloud \
    --region us-central1 \
    --service email-triage

Notes:
  - If there are no staged changes after add, commit is skipped.
  - Pass --skip-build to reuse the latest image.
  - Use --skip-git to only deploy without pushing code.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Git add/commit/push and deploy to Cloud Run")
    parser.add_argument("--key-file", help="Service account key JSON for gcloud auth (optional if --use-active-gcloud)")
    parser.add_argument("--region", default="us-central1", help="Cloud Run region")
    parser.add_argument("--service", default="email-triage", help="Cloud Run service name")
    parser.add_argument("--message", default="chore: ship and deploy", help="Git commit message")
    parser.add_argument("--skip-build", action="store_true", help="Skip Cloud Build; redeploy latest image")
    parser.add_argument("--skip-git", action="store_true", help="Skip git add/commit/push")
    parser.add_argument("--use-active-gcloud", action="store_true", help="Use current gcloud auth (skip key file)")
    return parser.parse_args()


def current_branch() -> str:
    cp = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True)
    return cp.stdout.strip()


def git_ship(message: str) -> None:
    # Add everything, commit if there are changes, then push current branch
    run(["git", "add", "-A"])  # stage all changes
    # If nothing staged, commit will fail; check first
    has_staged = subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0
    if has_staged:
        run(["git", "commit", "-m", message])
    else:
        print("No staged changes; skipping commit")
    branch = current_branch()
    run(["git", "push", "origin", branch])


def deploy(key_file: str | None, region: str, service: str, skip_build: bool, use_active_gcloud: bool) -> None:
    args = [
        sys.executable,
        "deploy_cloud_run.py",
        "--region",
        region,
        "--service",
        service,
        "--allow-unauthenticated",
    ]
    if use_active_gcloud:
        args.append("--use-active-gcloud")
    elif key_file:
        args.extend(["--key-file", key_file])
    else:
        raise SystemExit("Provide --key-file or --use-active-gcloud")
    if skip_build:
        args.append("--skip-build")
    run(args)


def main() -> int:
    args = parse_args()
    key_path: Path | None = None
    if args.key_file:
        key_path = Path(args.key_file).expanduser()
        if not key_path.exists():
            print(f"Service account key not found: {key_path}", file=sys.stderr)
            return 1

    try:
        if not args.skip_git:
            git_ship(args.message)
        deploy(str(key_path) if key_path else None, args.region, args.service, args.skip_build, args.use_active_gcloud)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
