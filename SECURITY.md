# Security policy

QRI can connect to external APIs and local databases. Never report or commit a real API key, password, private paper, or personal data in an issue or pull request.

## Reporting a vulnerability

For a security issue, use GitHub's private security reporting flow for the repository. If private reporting is unavailable, open a minimal issue without exploit details and ask a maintainer for a private channel.

Please include the affected version or commit, the route or component involved, reproduction steps that do not expose secrets, and the likely impact. We will acknowledge reports when we can and will coordinate a fix before publishing exploit details.

## Safe defaults

- Secrets belong in `.env`, which is ignored by Git.
- Local databases, logs, PDFs, and raw data stay outside the public repository.
- Community content is treated as untrusted input and is never executed.
- QRI is not a broker and does not place trades.
