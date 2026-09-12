# Operation, recovery and troubleshooting

## Monitoring

Normal logs contain per-event object counts, accepted-delivery counts and silent-baseline counts. `poll_failed` includes a safe exception category and HTTP status where available; SMTP response text is deliberately suppressed. Inspect provider/admin logs locally when more detail is needed without sharing credentials or user data.

Health is a read-only check of the most recent successful poll. It expires after the greater of 180 seconds or three configured polling intervals. API or delivery failures do not advance it. Docker marks the service unhealthy after its configured retries; it does not restart merely because it is unhealthy. `restart: unless-stopped` handles process exits, including persistent errors until the operator stops the service.

Failure backoff doubles up to a maximum of the greater of 900 seconds or the configured normal interval. Successful polls reset backoff. Socket timeouts apply to operations rather than an entire cycle. Allow sufficient shutdown grace for the chosen timeout and provider; the default grace is 45 seconds.

## Back up and restore

Stop this notifier before making a filesystem copy of its named Docker volume, or use SQLite's online backup facility. Do not copy only a live database file while ignoring a possible journal. Keep backups private and encrypted where appropriate.

Use Docker Desktop's volume backup/export workflow for the notifier's `notifier_state` volume, SQLite's online backup API from a tightly scoped helper, or an operator-reviewed volume backup tool. On Windows, a one-off backup helper may need container-root access to write a host bind mount; this does not justify running the notifier itself as root. Confirm the actual volume name with `docker compose volumes` where supported or inspect this Compose project's volume labels. Do not prune or alter other applications' volumes.

To restore: stop the notifier, retain the existing state as a private recovery copy, restore the consistent backup with UID/GID 10001 ownership, then start and check logs. An older backup may repeat alerts sent after its snapshot. Test restore on a separate test volume first.

Corruption/disk-full errors must not be fixed by automatically deleting the database. Stop the service, investigate storage, preserve evidence privately, and restore a known-good backup. Starting with empty state deliberately resends currently pending users.

## Upgrade

Back up state, read the changelog, pull the reviewed versioned image and recreate only this service with `docker compose pull` followed by `docker compose up -d`. Contributors can test a source checkout with `compose.build.yaml`. Schema 2 added failed-delivery ordering. Schema 3 adds event baselines and hashed observed-object keys without deleting schema-1/2 pending-user history. Version 0.2.0 deliberately retains the v0.1.x pending-user delivery-key format. Do not run an older program against newer state unless that migration is explicitly supported; v0.1.0 refuses schema 3, so rollback requires restoring a pre-upgrade state backup as well as the old image.

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
| `PermissionError` immediately at startup or during `--check-config` | On Linux, make both `secrets/*.txt` files owned by UID/GID 10001 with mode `0400`; on Windows, check ACLs and Docker file sharing |
| Cannot write state | Volume mount/ownership, free space, integrity, another process holding the lock |
| No repeated alert | Expected lifetime deduplication; check user ID, recipient and namespace |
| No joined/service-user/peer-added alert immediately after enabling | Expected silent first baseline; check `baselined` in logs, then create a controlled new object |
| New event category is absent | Confirm its `ALERT_*` setting is exactly `true`, run `--dry-run`, and verify the API identity can list that resource |
| Backlog | Per-poll attempt cap, failing recipients, provider throttling and network delays |

Changing namespace or origin creates a separate pending-user history and new creation-event baselines. Adding a recipient can produce a delivery for a user who is still pending, but it does not replay creation events whose object IDs are already observed. Removing then readding the same recipient preserves its old delivery history. A changed SMTP provider or rotated credentials does not reset history.
