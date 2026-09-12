# Pending-user notifier for self-hosted NetBird

An independent community project for use with self-hosted NetBird. Not affiliated with or endorsed by NetBird.

Poll the NetBird users API and email administrators when a user needs approval. The notifier sends mail directly through your SMTP provider; NetBird does not need SMTP configured. It never approves users or changes NetBird.

**Status:** version 0.1.0 release candidate. Live acceptance testing and local security checks passed; see [validation](docs/validation.md) for the evidence and limitations.

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

Requires Docker Desktop in Linux-container mode or Docker Engine, with Compose 2.30+. Run these commands from the project directory. Do not run inside the existing NetBird Compose project.

1. Create a dedicated NetBird API identity. Prefer an Auditor role if available and able to list the required users. Verify visibility using a known pending user; a successful empty response alone is not sufficient. Do not use an Owner token. See [configuration](docs/configuration.md).
2. Copy `.env.example` to `.env`. Enter your HTTPS NetBird origin and SMTP settings. Use literal unquoted values: Compose loads this file in raw mode.
3. Create the ignored `secrets` directory. In your editor, create `secrets/netbird_api_token.txt` and `secrets/smtp_password.txt`. Put only the corresponding secret in each file. Do not paste secrets into chat, command arguments, issues, or source files. Restrict host access; see [security](SECURITY.md).
4. Validate and build:

```powershell
docker compose config --quiet
docker compose build
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
```

TLS integration tests generate temporary certificates and use only local synthetic HTTPS/SMTP servers. They require the development dependency; without it they are skipped. No production credentials are needed.

To repeat container checks, build `Dockerfile.test` as `netbird-notifier-tests:local`, run that image, and run `./tests/check-container.ps1` in PowerShell from this directory. The script creates and removes a uniquely named synthetic Compose project; it preserves production state. Do not use its synthetic credentials for real deployment.

See [contributing](CONTRIBUTING.md), [security review](docs/security-review.md), [operations](docs/operations.md), [legal findings](docs/legal-and-licensing.md), [roadmap](ROADMAP.md), and [release process](docs/releasing.md).

## License

The project's original code and documentation are available under the [MIT License](LICENSE), copyright Andre Williams. NetBird and image/development dependencies retain their own licenses. See [license notes](docs/license-recommendation.md).
