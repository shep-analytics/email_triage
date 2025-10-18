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
import re
import time


def run_command(command: list[str], *, check: bool = True) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, check=check)


def run_capture(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print(f"+ {' '.join(command)}")
    return subprocess.run(command, check=check, capture_output=True, text=True)


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
            # Submit build without streaming logs to avoid VPC-SC/log bucket restrictions.
            # Use --async and poll build status via 'gcloud builds describe'.
            submit_cmd = [
                "gcloud",
                "builds",
                "submit",
                "--async",
                "--format=json",
                "--tag",
                image,
            ]
            try:
                cp = run_capture(submit_cmd)
            except subprocess.CalledProcessError as exc:
                # Even with --async, gcloud may print helpful context; include it.
                sys.stderr.write(exc.stderr or "")
                sys.stderr.write(exc.stdout or "")
                return exc.returncode

            # Try to extract build ID from JSON output; fallback to regex if needed.
            build_id: str | None = None
            try:
                op = json.loads(cp.stdout.strip() or "{}")
                # Expected path for async submit: metadata.build.id
                metadata = op.get("metadata") or {}
                build = metadata.get("build") or {}
                build_id = build.get("id")
            except json.JSONDecodeError:
                build_id = None

            if not build_id:
                # Fallback: parse from any '/builds/<id>' occurrence in stdout/stderr
                combined = f"{cp.stdout}\n{cp.stderr}"
                m = re.search(r"/builds/([a-f0-9\-]+)", combined)
                if m:
                    build_id = m.group(1)

            if not build_id:
                print("Unable to determine Cloud Build ID from submission output.", file=sys.stderr)
                # Provide the console link if present in output for manual tracking
                for line in (cp.stdout or "").splitlines():
                    if "cloudbuild.googleapis.com" in line:
                        print(line)
                return 1

            print(f"Submitted build ID: {build_id}")
            print(
                f"Track: https://console.cloud.google.com/cloud-build/builds/{build_id}?project={project_id}"
            )

            # Poll build status without streaming logs
            status = "UNKNOWN"
            describe_cmd_base = [
                "gcloud",
                "builds",
                "describe",
                build_id,
                "--format=value(status)",
            ]
            while True:
                try:
                    cp2 = run_capture(describe_cmd_base)
                except subprocess.CalledProcessError as exc:
                    sys.stderr.write(exc.stderr or "")
                    sys.stderr.write(exc.stdout or "")
                    return exc.returncode
                status = (cp2.stdout or "").strip().upper()
                if status in {"SUCCESS", "FAILURE", "CANCELLED", "TIMEOUT", "INTERNAL_ERROR"}:
                    print(f"Build completed with status: {status}")
                    if status != "SUCCESS":
                        return 2
                    break
                # Still building
                time.sleep(2)

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
