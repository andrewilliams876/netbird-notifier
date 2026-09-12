# Validation record

Last updated 2026-09-12. Results apply to the current local pre-release tree and local image, not a published release.

## Passed

- 33 Python tests on Windows Python 3.12 and inside the restricted Linux test image. Five tests use temporary local certificates and synthetic HTTPS/SMTP servers. No external NetBird or mail account is used.
- HTTPS verification, hostname mismatch, untrusted certificates, redirects, unauthorized responses, STARTTLS-before-authentication, implicit TLS, and missing STARTTLS behavior.
- Strict pending-user schema, regular/service-user filtering, per-recipient retries, lifetime deduplication, restart persistence, schema-1-to-2 migration, corruption preservation, lock contention, failed-state commits and safe logs.
- Production/test image builds with the pinned official Python Alpine base.
- Compose configuration and secret mounts using synthetic values.
- Container UID 10001, zero effective capabilities, no-new-privileges, read-only root filesystem, writable state volume and persistent deduplication across two one-off containers.
- Docker health transitions from healthy to unhealthy after the stored success expires, then back to healthy after a successful synthetic poll.
- Verified TLS connection from the production container to `https://netbird.servar.xyz/api/users`; the unauthenticated request returned HTTP 401 as expected. This proves reachability and certificate validation, not authenticated API compatibility.
- Authenticated live `GET /api/users` succeeded against self-hosted NetBird Management v0.78.1 using the dedicated service identity. A read-only dry run detected one known pending regular user and sent no email or notification-state update.
- Zoho SMTP accepted a marked test message and the owner confirmed it arrived in the configured inbox.
- A real pending-user cycle produced exactly one alert, which the owner confirmed arrived with the expected details. An immediate second authenticated poll still found the pending user and accepted zero messages, verifying live per-recipient deduplication with the persistent Docker volume.
- Continuous Compose service started against the preserved state and its first poll found the same pending user with zero new deliveries.
- After the owner manually approved the test user, the next scheduled production poll reported zero pending users and zero deliveries. A separate read-only dry run confirmed the same result, and Docker continued to report the service healthy.
- The live state database was backed up with SQLite's online backup API while the notifier remained running, restored into a newly created isolated Docker volume, and passed an integrity check with the expected single notification record. The temporary restore volume was removed; the ignored host backup was retained privately.
- The Compose project, runtime image and exact container name were changed to `netbird-notifier`. SQLite online backup migrated the expected single notification record into `netbird-notifier_notifier_state`; the renamed service became healthy and subsequent polls reported zero pending users. The original volume remains available locally as a rollback copy.
- The final Compose smoke test creates a unique project-scoped state volume, verifies deduplication across containers, exercises healthy/unhealthy recovery, and removes only its synthetic resources. This also verifies test projects do not share the production volume.
- Final source secret scan found zero findings in distributable files. `.env`, `secrets/`, state, Git metadata and generated scan artifacts were excluded by design and are ignored by Git; they require separate operator protection.

## Image scanning

The initial Debian-based image produced high and critical scanner findings. The runtime was moved to the pinned Alpine base and upgraded to fixed `libuuid`; unused Python package-installation tooling was removed from the production image. The final production image scan reported **zero known vulnerabilities**. Direct inspection also confirmed `pip`, `setuptools`, and `msgpack` are absent. A zero-finding scan is a point-in-time database result, not proof that the image is vulnerability-free.

The local test image reported three findings attributed to inherited `msgpack`/`setuptools` metadata (two high, one medium), although direct runtime inspection of the production image confirms those packages are absent. The test image deliberately installs development-only certificate tooling, is not referenced by Compose, and must never be distributed as the runtime image. This discrepancy should be rechecked with a fresh scanner/SBOM before release; it does not alter the production image's zero-finding result.

The local scanner was Trivy using its downloaded advisory database. Docker Scout was unavailable without signing in. The distributable-source secret scan reported zero findings. Scanner reports and exported images live under ignored `artifacts/` and are not release files.

## Unverified / release blockers

- Longer-running provider rate/relay behavior and token-rotation procedure.
- Longer-running upgrade behavior across future NetBird releases.
- GitHub CI execution and private vulnerability-reporting setup after repository publication.

At the time of this record, no push, tag, GitHub release or public image had occurred. The owner confirmed real deployment acceptance and authorized public repository publication.
