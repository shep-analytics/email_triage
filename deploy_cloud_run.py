#!/usr/bin/env python3
"""
Deploy the email triage service to Cloud Run using a service account key.

Usage:
    python3 deploy_cloud_run.py --key-file email-assistant-service-key.json
    # or use your active gcloud auth instead of a key file:
    python3 deploy_cloud_run.py --use-active-gcloud

Optional flags:
    --region us-central1
    --service email-triage
    --image-repo email-triage
    --skip-build    (only redeploy the latest image)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str], *, check: bool = True) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, check=check)


def load_project_id(key_path: Path) -> str:
    data = json.loads(key_path.read_text(encoding="utf-8"))
    return data["project_id"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and deploy the Cloud Run service.")
    parser.add_argument(
        "--key-file",
        help="Path to the service account key JSON. If omitted, use --use-active-gcloud.",
    )
    parser.add_argument(
        "--region",
        default="us-central1",
        help="Cloud Run region (default: us-central1).",
    )
    parser.add_argument(
        "--service",
        default="email-triage",
        help="Cloud Run service name (default: email-triage).",
    )
    parser.add_argument(
        "--image-repo",
        default="email-triage",
        help="Container image repository name (default: email-triage).",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip Cloud Build (use most recent image).",
    )
    parser.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="Permit unauthenticated HTTPS access (required for Pub/Sub push).",
    )
    parser.add_argument(
        "--use-active-gcloud",
        action="store_true",
        help="Use currently logged-in gcloud account (skip key auth).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_id: str
    key_path: Path | None = None
    if args.key_file:
        key_path = Path(args.key_file).expanduser().resolve()
        if not key_path.exists():
            print(f"Service account key not found: {key_path}", file=sys.stderr)
            return 1
        project_id = load_project_id(key_path)
    elif args.use_active_gcloud:
        try:
            cp = subprocess.run(["gcloud", "config", "get-value", "project"], check=True, capture_output=True, text=True)
            project_id = (cp.stdout or "").strip()
        except subprocess.CalledProcessError:
            project_id = ""
        if not project_id:
            print("No project configured. Run: gcloud config set project <PROJECT_ID> or provide --key-file.", file=sys.stderr)
            return 1
    else:
        print("Provide --key-file or use --use-active-gcloud.", file=sys.stderr)
        return 1
    image = f"gcr.io/{project_id}/{args.image_repo}"

    try:
        if key_path is not None:
            run_command(
                [
                    "gcloud",
                    "auth",
                    "activate-service-account",
                    f"--key-file={key_path}",
                ]
            )

        run_command(["gcloud", "config", "set", "project", project_id])

        if not args.skip_build:
            run_command(
                [
                    "gcloud",
                    "builds",
                    "submit",
                    "--tag",
                    image,
                ]
            )

        deploy_cmd = [
            "gcloud",
            "run",
            "deploy",
            args.service,
            "--image",
            image,
            "--region",
            args.region,
            "--platform",
            "managed",
        ]
        if args.allow_unauthenticated:
            deploy_cmd.append("--allow-unauthenticated")

        run_command(deploy_cmd)

    except subprocess.CalledProcessError as exc:
        return exc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
