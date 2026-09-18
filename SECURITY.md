# Security policy

QRI can connect to external APIs and local databases. Never report or commit a real API key, password, private paper, or personal data in an issue or pull request.

## Reporting a vulnerability

For a security issue, use GitHub's private security reporting flow for the repository. If private reporting is unavailable, open a minimal issue without exploit details and ask a maintainer for a private channel.

Please include the affected version or commit, the route or component involved, reproduction steps that do not expose secrets, and the likely impact. We will acknowledge reports when we can and will coordinate a fix before publishing exploit details.

## Safe defaults

- Secrets belong in `.env`, which is ignored by Git along with every `.env.*`
  variant, key and certificate file.
- Local databases, logs, PDFs, and raw data stay outside the public repository.
- Secrets are held as `SecretStr` and unwrapped only where a request is made.
  They are never logged or passed into a template context.
- Funnel stage output is persisted and rendered on the dashboard, so it is
  scrubbed first by `app/core/redaction.py`. This matters because HTTP client
  errors quote the full request URL and some APIs take their key as a query
  parameter, which would otherwise write a live credential into the database.
- Community content is treated as untrusted input and is never executed.
- QRI is not a broker and does not place trades.

CI scans the full Git history for committed credentials on every change.

## If you have already committed a secret

Rotate it first: history rewriting does not help once a key has been pushed,
and anything public should be assumed captured. Then remove it from history and
force-push.
