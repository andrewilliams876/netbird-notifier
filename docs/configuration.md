# Configuration reference

The Compose file supplies `STATE_DIR` and secret-file paths. `.env` supplies other settings. The application itself reads the process environment; it does not automatically parse `.env` when run directly with Python.

| Setting | Default / requirement |
| --- | --- |
| `NETBIRD_URL` | Required HTTPS origin, optionally ending in `/api`; no credentials, query, fragment, or other path |
| `NETBIRD_API_TOKEN_FILE` | Compose: `/run/secrets/netbird_api_token` |
| `NETBIRD_API_TOKEN` | Alternative to token file; do not supply both |
| `SMTP_HOST` | Required provider hostname |
| `SMTP_PORT` | 587; 465 when security is `ssl`; permitted 1–65535 |
| `SMTP_SECURITY` | `starttls`; alternatives `ssl`, `none` |
| `SMTP_AUTH` | `true`; only literal true/false accepted |
| `SMTP_USERNAME` | Required when authentication is enabled |
| `SMTP_PASSWORD_FILE` | Compose: `/run/secrets/smtp_password` |
| `SMTP_PASSWORD` | Alternative to password file; do not supply both |
| `SMTP_FROM` | Required bare ASCII email address, no display name |
| `SMTP_TO` | Required comma-separated bare ASCII addresses, at most 20; exact duplicates removed |
| `ALLOW_INSECURE_SMTP` | `false`; must explicitly be true for plaintext SMTP |
| `STATE_DIR` | `/data`; use persistent local storage |
| `STATE_NAMESPACE` | `default`; 1–64 letters, digits, underscores or hyphens |
| `POLL_INTERVAL_SECONDS` | 60; range 30–86400 |
| `NETWORK_TIMEOUT_SECONDS` | 20; range 1–120; socket operation timeout, not a total-cycle deadline |
| `MAX_ALERTS_PER_POLL` | 20; range 1–1000; counts delivery attempts across recipients |
| `NETBIRD_CA_FILE` | Optional path to trusted API CA bundle |
| `SMTP_CA_FILE` | Optional path to trusted SMTP CA bundle |

URLs normalize hostname case, default HTTPS port and trailing `/api`, so equivalent URL spellings share history. NetBird-owned `netbird.io` hosts are refused to keep this project scoped to self-hosting. This is not an authorization boundary: the operator must configure an endpoint they control.

For unauthenticated TLS relays, set `SMTP_AUTH=false`, empty `SMTP_USERNAME`, and provide an empty password file. For plaintext relays additionally set `SMTP_SECURITY=none` and `ALLOW_INSECURE_SMTP=true`. Plaintext exposes notification contents; restrict it to a deliberately trusted environment. Authentication over plaintext is prohibited even with the opt-in.

Custom CA files must also be mounted read-only into the container at the configured paths. A custom bundle replaces the default trust roots for that connection. Never disable certificate verification as a fix for a TLS error.

## API identity and compatibility

The documented API uses `GET /api/users` with `Authorization: Token ...`. All returned records must have a valid ID and a boolean `pending_approval`; malformed responses fail before sending alerts. Responses are capped at 5 MiB and must be JSON arrays. Pagination is not implemented because the reviewed users endpoint returns an array without documented pagination; verify this again on upgrades.

The deployment owner reports Management v0.78.1 and Dashboard v2.92.0. The v0.78.1 HTTP handler and public API contract have been reviewed; live compatibility and visibility remain acceptance checks.

Prefer a dedicated Auditor identity where available. Auditor is broadly read-only, not restricted to just pending users, and may expose sensitive configuration. A normal User role may not return the whole account. If the installed edition cannot grant the required read access without broader privilege, document and approve that tradeoff before deploying; do not silently upgrade the role. Token rotation and expiry are the operator's responsibility.

Use one state volume/namespace per account. Changing token within the same account preserves history. Changing to a different account at the same origin requires a distinct namespace or separate volume.

References: [API](https://docs.netbird.io/api), [users](https://docs.netbird.io/api/resources/users), [roles](https://docs.netbird.io/manage/team/user-roles), [Compose environment files](https://docs.docker.com/reference/compose-file/services/#env_file).
