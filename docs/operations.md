# Operation, recovery and troubleshooting

## Monitoring

Normal logs contain pending and accepted counts. `poll_failed` includes a safe exception category and HTTP status where available; SMTP response text is deliberately suppressed. Inspect provider/admin logs locally when more detail is needed without sharing credentials or user data.

Health is a read-only check of the most recent successful poll. It expires after the greater of 180 seconds or three configured polling intervals. API or delivery failures do not advance it. Docker marks the service unhealthy after its configured retries; it does not restart merely because it is unhealthy. `restart: unless-stopped` handles process exits, including persistent errors until the operator stops the service.

Failure backoff doubles up to a maximum of the greater of 900 seconds or the configured normal interval. Successful polls reset backoff. Socket timeouts apply to operations rather than an entire cycle. Allow sufficient shutdown grace for the chosen timeout and provider; the default grace is 45 seconds.

## Back up and restore

Stop this notifier before making a filesystem copy of its named Docker volume, or use SQLite's online backup facility. Do not copy only a live database file while ignoring a possible journal. Keep backups private and encrypted where appropriate.

Use Docker Desktop's volume backup/export workflow for the notifier's `notifier_state` volume, SQLite's online backup API from a tightly scoped helper, or an operator-reviewed volume backup tool. On Windows, a one-off backup helper may need container-root access to write a host bind mount; this does not justify running the notifier itself as root. Confirm the actual volume name with `docker compose volumes` where supported or inspect this Compose project's volume labels. Do not prune or alter other applications' volumes.

To restore: stop the notifier, retain the existing state as a private recovery copy, restore the consistent backup with UID/GID 10001 ownership, then start and check logs. An older backup may repeat alerts sent after its snapshot. Test restore on a separate test volume first.

Corruption/disk-full errors must not be fixed by automatically deleting the database. Stop the service, investigate storage, preserve evidence privately, and restore a known-good backup. Starting with empty state deliberately resends currently pending users.

## Upgrade

Back up state, read the changelog, run tests, build the reviewed image and recreate only this service. Schema 2 adds failed-delivery ordering to schema 1 without deleting notification history. Do not run an older program against newer state unless that migration is explicitly supported; the original schema-1 application refuses schema 2.

The Python Alpine base is pinned to an image digest. The runtime removes the package installer because it has no third-party Python dependencies. Periodically review a newer supported base, scan it, update the digest and rerun container acceptance tests. Pinning is reproducibility, not automatic patching.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| HTTP 401 | Expired/revoked token; correct token file and origin |
| HTTP 403 or missing expected users | Identity role and account visibility; do not automatically use Owner |
| TLS error | Correct hostname, system time, trust chain, optional mounted CA bundle |
| Protocol error | API version/shape, JSON content type, proxy returning login HTML, redirects, response size |
| SMTP failure | Provider host/port, TLS mode, permitted sender, app password, authentication policy, quotas |
| SMTP accepted but no inbox email | Spam folder, provider delivery logs, recipient address, sender DNS/authentication |
| Cannot read secret files | Windows ACLs or Linux file ownership and non-root UID readability |
| Cannot write state | Volume mount/ownership, free space, integrity, another process holding the lock |
| No repeated alert | Expected lifetime deduplication; check user ID, recipient and namespace |
| Backlog | Per-poll attempt cap, failing recipients, provider throttling and network delays |

Changing namespace/origin or adding a recipient creates new deduplication identities. Removing then readding the same recipient preserves its old history. A changed SMTP provider or rotated credentials does not reset history.
