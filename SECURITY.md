# Security

## Reporting a vulnerability

Send security reports privately to admin@toonux.com. Include the affected
revision, impact and steps to reproduce. Do not put credentials, personal
data or an unremediated vulnerability in a public issue.

## Credentials and generated data

- API keys belong only in the server environment, outside the web root.
- `env.example` must contain empty credential values.
- Never commit environment files, private keys, logs, database dumps or
  generated market snapshots and downloaded logos.
- Do not include secrets in URLs, error output or screenshots.
- If a secret is exposed, revoke or rotate it first. Deleting the current
  file does not remove the credential from Git history.

## Contribution checks

Keep the same-origin browser policy, input validation, HTTPS verification,
provider allowlists and service sandbox intact. Missing market data must
remain unavailable; do not generate replacement prices or returns.

Run the frontend regression checks with `node --test tests/*.test.cjs` and
check syntax with `node --check web/app.js`. The snapshot validator is
`python3 scripts/validate_snapshot.py PATH_TO_SNAPSHOT`.

Before publishing a revision, scan both the working tree and complete Git
history with a maintained secret scanner. A scan with no findings is not a
guarantee that the application has no vulnerabilities.
