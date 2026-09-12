# Validation record

Last updated 2026-09-12. Results apply to the current local pre-release tree and local image, not a published release.

## Passed

- 47 Python tests inside the restricted Linux test image. Six tests use temporary local certificates and synthetic HTTPS/SMTP servers. The synthetic suite uses no external NetBird or mail account.
- HTTPS verification, hostname mismatch, untrusted certificates, redirects, unauthorized responses, STARTTLS-before-authentication, implicit TLS, and missing STARTTLS behavior.
- Strict user/peer schemas, regular/service-user classification, active-user filtering, silent creation baselines, enable/disable rebaselining, approval-to-joined transitions, per-recipient retries, lifetime deduplication, restart persistence, schema-1/2-to-3 migration, corruption preservation, lock contention, failed-state commits and safe logs.
- End-to-end local TLS tests delivered the pending-user, user-joined, service-user-created and peer-added templates, then verified restart deduplication and exactly one users plus one peers request per enabled polling cycle.
- Production/test image builds with the pinned official Python Alpine base.
- Compose configuration and secret mounts using synthetic values.
- Container UID 10001, zero effective capabilities, no-new-privileges, read-only root filesystem, writable state volume and persistent deduplication across two one-off containers.
- Docker health transitions from healthy to unhealthy after the stored success expires, then back to healthy after a successful synthetic poll.
- The v0.2.0 development image passed the isolated Compose smoke test as UID/GID 10001 with no capabilities, no-new-privileges, a read-only root filesystem, schema-3 state persistence and health recovery.
- An authenticated v0.2.0 read-only dry run against self-hosted NetBird Management v0.78.1 successfully validated both `/api/users` and `/api/peers` responses with all four event categories enabled. It sent no mail and changed no state or baselines.
- The same live peers response confirmed `connection_ip` is available for public-address reporting. Valid IPv4 values were present; one unavailable non-IP marker was safely omitted rather than copied into mail or allowed to fail the polling cycle.
- A real v0.2.0 `--once` cycle used a separate project and volume, silently baselined the current active users, service users and peers, found no pending regular user, and accepted no mail. A second cycle accepted no mail and added no baseline objects. Read-only state inspection reported schema 3, three active event baselines, the expected hashed-object count and zero sent deliveries; the v0.1.0 production volume was not mounted or migrated.
- Actionlint accepted the modified CI and release workflows.
- Verified TLS connection from the production container to `https://netbird.servar.xyz/api/users`; the unauthenticated request returned HTTP 401 as expected. This proves reachability and certificate validation, not authenticated API compatibility.
- Authenticated live `GET /api/users` succeeded against self-hosted NetBird Management v0.78.1 using the dedicated service identity. A read-only dry run detected one known pending regular user and sent no email or notification-state update.
- Zoho SMTP accepted a marked test message and the owner confirmed it arrived in the configured inbox.
- A real pending-user cycle produced exactly one alert, which the owner confirmed arrived with the expected details. An immediate second authenticated poll still found the pending user and accepted zero messages, verifying live per-recipient deduplication with the persistent Docker volume.
- Continuous Compose service started against the preserved state and its first poll found the same pending user with zero new deliveries.
- After the owner manually approved the test user, the next scheduled production poll reported zero pending users and zero deliveries. A separate read-only dry run confirmed the same result, and Docker continued to report the service healthy.
- The live state database was backed up with SQLite's online backup API while the notifier remained running, restored into a newly created isolated Docker volume, and passed an integrity check with the expected single notification record. The temporary restore volume was removed; the ignored host backup was retained privately.
- The Compose project, runtime image and exact container name were changed to `netbird-notifier`. SQLite online backup migrated the expected single notification record into `netbird-notifier_notifier_state`; the renamed service became healthy and subsequent polls reported zero pending users. The original volume remains available locally as a rollback copy.
- The final Compose smoke test creates a unique project-scoped state volume, verifies deduplication across containers, exercises healthy/unhealthy recovery, and removes only its synthetic resources. This also verifies test projects do not share the production volume.
- On the `dev` branch, the pull-based Compose definition and separate local-build override both passed Compose validation. The local-build override built successfully, and the pull-based definition was exercised against the locally tagged GHCR image while preserving production state; the service returned healthy as UID/GID 10001 and accepted no duplicate alert.
- Main-branch CI passed and published the mutable `main` preview after the merge tests succeeded. Stable release automation retested tag `v0.1.0`, published immutable `0.1.0` and mutable `latest` GHCR tags with the repository workflow token, and retained the existing GitHub release. The final workflow is manual-only and refuses to replace an existing versioned image tag.
- An anonymous pull using an empty Docker credential directory downloaded `ghcr.io/andrewilliams876/netbird-notifier:0.1.0` with digest `sha256:522bc1fe28b81ced82894777e9692a08948b56cca9e15d6bb3ecdb80d34ee6d3`. The production Compose service was recreated from that registry image, retained its state volume, became healthy as UID/GID 10001, and accepted no duplicate alert.
- Final source secret scan found zero findings in distributable files. `.env`, `secrets/`, state, Git metadata and generated scan artifacts were excluded by design and are ignored by Git; they require separate operator protection.

## Image scanning

The initial Debian-based image produced high and critical scanner findings. The runtime was moved to the pinned Alpine base and upgraded to fixed `libuuid`; unused Python package-installation tooling was removed from the production image. The v0.1.0 release and current local v0.2.0 runtime image scans reported **zero known vulnerabilities and zero embedded-secret findings**. Direct inspection also confirmed `pip`, `setuptools`, and `msgpack` are absent. A zero-finding scan is a point-in-time database result, not proof that an image is vulnerability-free.

The v0.2.0 distributable-source scan, excluding local `.env`, `secrets/`, Git data and ignored private artifacts by design, reported zero known vulnerabilities and zero secret findings. It reported two low-severity Dockerfile checks because neither Dockerfile embeds a `HEALTHCHECK`; the deployed service defines its healthcheck in `compose.yaml`, and the test image is not distributed. This accepted finding avoids baking deployment-specific health timing into the reusable image.

The current local v0.2.0 test-image scan reproduced three findings attributed to `msgpack`/`setuptools` metadata (two high, one medium). Direct module and installed-distribution inspection found neither package in the final test-image filesystem. The test image deliberately installs development-only certificate tooling, is not referenced by Compose, and must never be distributed as the runtime image. The scanner/metadata discrepancy does not alter the separately scanned production image's zero-finding result.

The local scanner was Trivy using its downloaded advisory database. Docker Scout was unavailable without signing in. The distributable-source secret scan reported zero findings. Scanner reports and exported images live under ignored `artifacts/` and are not release files.

## Unverified / release blockers

- Longer-running provider rate/relay behavior and token-rotation procedure.
- Longer-running upgrade behavior across future NetBird releases.
- Private vulnerability-reporting setup.
- Live creation and delivery for each new v0.2.0 category against the owner's real NetBird/SMTP deployment; the API compatibility check and synthetic deliveries are complete, but release acceptance still requires controlled real events.

Version 0.1.0 is public. Version 0.2.0 remains development work on `dev`; it has not been merged to `main`, tagged, released, or published as a stable image.
