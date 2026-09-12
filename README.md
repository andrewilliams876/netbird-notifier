# NetBird Notifier

Secure pending-user email notifications for self-hosted NetBird.

An independent community project for use with self-hosted NetBird. Not affiliated with or endorsed by NetBird.

Poll the NetBird users API and email administrators when a user needs approval. The notifier sends mail directly through your SMTP provider; NetBird does not need SMTP configured. It never approves users or changes NetBird.

**Status:** version 0.1.0. Live acceptance testing and security checks passed; see [validation](docs/validation.md) for the evidence and limitations.

```text
Self-hosted NetBird API <-- HTTPS GET -- Notifier -- SMTP/TLS --> Your mail provider
                                          |
                                    SQLite volume
```

## Behavior

- Alerts only for a boolean `pending_approval: true`; service users are excluded.
- Existing pending users are notified on first startup. Polls normally run every 60 seconds.
- One accepted alert per user ID and recipient for the lifetime of a state namespace. Approval followed by another pending period does not rearm that user.
- Separate deliveries and state for each recipient; unsuccessful deliveries are retried with backoff. New deliveries precede old failures to avoid a failed recipient blocking the queue.
- TLS and certificate verification are required by default. STARTTLS and implicit TLS are supported; SMTP username/password authentication or unauthenticated relays are supported. OAuth-only SMTP is not implemented.
- No inbound ports, NetBird changes, host networking, privileged mode, or Docker socket are needed.

SMTP acceptance is not proof of inbox delivery. A crash after SMTP acceptance but before durable state commit can cause a duplicate. Stable Message-IDs do not guarantee deduplication by a mail provider. Polling can miss short-lived pending states. This is an administrative convenience, not an access-control enforcement mechanism.

## Quick start

Requires Docker Desktop in Linux-container mode or Docker Engine, with Compose 2.30+. You only need `compose.yaml` and `.env.example`; cloning the source repository is optional:

```powershell
New-Item -ItemType Directory netbird-notifier
Set-Location netbird-notifier
curl.exe -LO https://raw.githubusercontent.com/andrewilliams876/netbird-notifier/main/compose.yaml
curl.exe -LO https://raw.githubusercontent.com/andrewilliams876/netbird-notifier/main/.env.example
Copy-Item .env.example .env
New-Item -ItemType Directory secrets
```

Run the remaining commands from that directory. Do not place this Compose file inside the existing NetBird Compose project.

Before starting the notifier, the deployment directory must have this structure:

```text
netbird-notifier/
├── .env
├── compose.yaml
└── secrets/
    ├── netbird_api_token.txt
    └── smtp_password.txt
```

Docker Compose also recognizes the legacy filename `docker-compose.yml` if you choose to rename `compose.yaml`.

1. Create a dedicated NetBird API identity. Prefer an Auditor role if available and able to list the required users. Verify visibility using a known pending user; a successful empty response alone is not sufficient. Do not use an Owner token. See [configuration](docs/configuration.md).
2. Copy `.env.example` to `.env`. Enter your HTTPS NetBird origin and SMTP settings. Use literal unquoted values: Compose loads this file in raw mode.
3. Create the ignored `secrets` directory. In your editor, create `secrets/netbird_api_token.txt` and `secrets/smtp_password.txt`. Put only the corresponding secret in each file. Do not paste secrets into chat, command arguments, issues, or source files.

   **Required on Linux before running any Docker Compose command that starts the notifier:** Compose mounts local secret files with their host ownership. The notifier runs as UID/GID 10001, so give that identity read-only access:

   ```bash
   chmod 0700 secrets
   sudo chown 10001:10001 secrets/netbird_api_token.txt secrets/smtp_password.txt
   sudo chmod 0400 secrets/netbird_api_token.txt secrets/smtp_password.txt
   chmod 0600 .env
   ```

   Verify the metadata without displaying either secret:

   ```bash
   ls -ldn secrets
   ls -ln secrets/netbird_api_token.txt secrets/smtp_password.txt
   ```

   Both files must show numeric owner and group `10001 10001` with read access for the owner. If this step is skipped, `--check-config`, `--dry-run`, `--test-email`, and the continuous container will fail with `operation_failed category=PermissionError`. Do not make secret files globally readable as a workaround. Windows operators should restrict their ACLs to the operator and required Docker identities. See [security](SECURITY.md).
4. Pull the published versioned image and validate it:

```powershell
docker compose config --quiet
docker compose pull
docker compose run --rm notifier --check-config
docker compose run --rm notifier --dry-run
```

`--dry-run` queries NetBird and prints only a pending count. It sends no mail and changes no notification state. Configuration validation does not test connectivity or role visibility.

5. Send a test to the configured administrator recipient(s), then verify the inbox and spam folder:

```powershell
docker compose run --rm notifier --test-email
```

6. Run the [acceptance checks](docs/acceptance.md), then start continuous operation:

```powershell
docker compose up -d
docker compose logs --tail 50 notifier
docker compose ps
```

Only the notifier is started by this Compose file. Keep its volume: **`docker compose down --volumes` deletes deduplication history and can repeat alerts.** Ordinary `docker compose down` preserves the named volume.

## Upgrading

Stable deployments use an explicit image version in `compose.yaml`. Read the release notes, change the image tag from the installed version to the new release, then run:

```powershell
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail 50 notifier
```

For example, an upgrade from `0.1.0` to `0.2.0` changes only this line before the commands above:

```yaml
image: ghcr.io/andrewilliams876/netbird-notifier:0.2.0
```

Compose recreates the container with the downloaded image and retains the named state volume. Never add `--volumes` during an ordinary upgrade. To roll back, restore the previous image tag and run the same pull/up commands, provided the older release supports the current state schema.

The mutable `latest` tag is published for convenience, but the versioned tag is recommended for predictable deployments. Changes merged into `main` run validation and update the `main` preview image without becoming a stable release. A maintainer-approved release publishes a new versioned image, updates `latest`, and creates the corresponding GitHub release.

## Zoho and other providers

Set the SMTP hostname shown in your account's server configuration; Zoho account type and data centre change the required host. Typically use port 587 with `SMTP_SECURITY=starttls`, or port 465 with `SMTP_SECURITY=ssl`. Use a permitted sender and, where required, an app-specific password. [Zoho's official configuration guide](https://www.zoho.com/mail/help/zoho-smtp.html) is authoritative for your account.

Other providers use the same generic settings. This application supports SMTP AUTH through Python's `smtplib.login` (server-supported CRAM-MD5, PLAIN, LOGIN), exclusively over TLS. Providers that require OAuth need a supported relay or future OAuth support. Sender authentication, account permissions, SPF/DKIM/DMARC, quotas and spam filtering remain provider/operator responsibilities.

Keep `SMTP_FROM` as the real permitted email address. Set `SMTP_FROM_NAME=NetBird` to show **NetBird** as the sender name in supporting mail clients.

## Commands

| Command argument | Effect |
| --- | --- |
| `--check-config` | Validate configuration and CA files; no network or state write |
| `--dry-run` | Fetch and validate API response; log pending count; no delivery/state write |
| `--test-email` | Send a clearly marked test per recipient; no deduplication changes |
| `--once` | Perform one real polling/delivery cycle |
| `--healthcheck` | Read the last successful poll timestamp; return healthy/unhealthy |
| no argument | Poll until stopped, with failure backoff |

Do not run `--once` or a second daemon concurrently with normal operation. A shared-volume writer lock prevents simultaneous same-key sends but contention can stop one process. Independent volumes have independent history.

## Development

Python 3.12+; the application has no third-party Python runtime dependencies.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m unittest discover -s tests -v
docker compose -f compose.yaml -f compose.build.yaml build
```

TLS integration tests generate temporary certificates and use only local synthetic HTTPS/SMTP servers. They require the development dependency; without it they are skipped. No production credentials are needed.

The development override builds the current checkout as `netbird-notifier:dev`; normal Compose usage pulls the versioned GHCR image. To repeat container checks, first build the runtime as `netbird-notifier:0.1.0`, build `Dockerfile.test` as `netbird-notifier-tests:local`, run that image, and run `./tests/check-container.ps1` in PowerShell. The script creates and removes a uniquely named synthetic Compose project and preserves production state. Do not use its synthetic credentials for real deployment.

See [contributing](CONTRIBUTING.md), [security review](docs/security-review.md), [operations](docs/operations.md), [legal findings](docs/legal-and-licensing.md), [roadmap](ROADMAP.md), and [release process](docs/releasing.md).

## License

The project's original code and documentation are available under the [MIT License](LICENSE), copyright Andre Williams. NetBird and image/development dependencies retain their own licenses. See [license notes](docs/license-recommendation.md).
