# Cloud Deploy Workflow

This project still supports the zero-input Cloud Run deployment path. When you need
to ship a build to production, follow these steps:

1. Stage changes: `git add -A`
2. Commit: `git commit -m "agent: <brief summary of change>"`
3. Push: `git push origin main`
4. Verify end-to-end: `python3 verify_e2e.py --key-file json_keys/owner_google_service_account_key.json --region us-central1 --service email-triage --subscription email-triage-push --email <one_of_GMAIL_ACCOUNTS>`

If verification fails due to a transient issue, rerun once. Persistent failures
should be surfaced to the team and documented in `AGENTS.md` under Updates.

Notes:

- Do not delete committed keys or tokens.
- If GitHub blocks a push because of sensitive files, exclude those files from
  the commit but keep local copies for deployment.
- Cloud deploy prerequisites (GCP project ID, service account key, Supabase
  credentials) continue to live in `config.py`, `keys.py`, and `json_keys/`.

Refer to `docs/cloud_run.md` for additional deployment details and
`verify_e2e.py --help` for advanced options such as custom push endpoints.

