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
| `SMTP_FROM` | Required bare ASCII envelope/header email address, no display name |
| `SMTP_FROM_NAME` | Optional display name shown by mail clients, for example `NetBird`; maximum 128 characters and no control characters |
| `SMTP_TO` | Required comma-separated bare ASCII addresses, at most 20; exact duplicates removed |
| `ALERT_USER_PENDING_APPROVAL` | `true`; alert for pending regular users |
| `ALERT_USER_JOINED` | `false`; alert for active regular users first observed after a silent baseline |
| `ALERT_SERVICE_USER_CREATED` | `false`; alert for service users first observed after a silent baseline |
| `ALERT_PEER_ADDED` | `false`; alert for peers first observed after a silent baseline |
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

The notifier uses `GET /api/users` for user event types and `GET /api/peers` only when peer-added alerts are enabled, with `Authorization: Token ...`. It never makes a write request. User records require a valid unique ID and boolean `pending_approval`; joined-user detection also requires a string status and selects only non-service, non-pending users whose normalized status is `active`. Service-user detection uses the boolean `is_service_user`. Peer records require a valid unique ID. Peer-added mail includes `ip` as the NetBird overlay address and, when supplied, `connection_ip` as the public connection address. Valid IPv4 and IPv6 values are normalized; unavailable or malformed connection-address values are omitted from the email. Malformed required response fields fail before sending alerts or updating baselines.

Responses are capped at 5 MiB and must be JSON arrays. Pagination is not implemented because the reviewed users and peers endpoints return arrays without documented pagination; verify this again on upgrades. Snapshot comparison cannot recover objects created and removed between successful polls.

The deployment owner reports Management v0.78.1 and Dashboard v2.92.0. The v0.78.1 HTTP handler and public API contract have been reviewed; live compatibility and visibility remain acceptance checks.

Prefer a dedicated Auditor identity where available. Auditor is broadly read-only, not restricted to just the selected events, and may expose sensitive users, peers, and configuration. A normal User role may not return the whole account. If the installed edition cannot grant the required read access without broader privilege, document and approve that tradeoff before deploying; do not silently upgrade the role. Token rotation and expiry are the operator's responsibility.

Creation-event baselines and observed IDs are scoped by normalized origin, namespace, and event. Only SHA-256 digests of object IDs are stored. The first real poll after initial enablement or a recorded disabled period silently records the current objects. Pending-user alerts remain state-based and preserve the v0.1.x delivery-key format during migration.

Use one state volume/namespace per account. Changing token within the same account preserves history. Changing to a different account at the same origin requires a distinct namespace or separate volume.

References: [API](https://docs.netbird.io/api), [users](https://docs.netbird.io/api/resources/users), [roles](https://docs.netbird.io/manage/team/user-roles), [Compose environment files](https://docs.docker.com/reference/compose-file/services/#env_file).
