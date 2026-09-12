# Changelog

## [0.2.0] - Unreleased

- Added the public connection IP returned by NetBird to peer-added email alerts.
- Rearmed pending-user notifications after a successful poll observes that the user is no longer pending, while retaining one delivery per recipient during each continuous pending episode.
- Added independently configurable email alerts for active regular users joining, service users being created, and peers being added.
- Added silent first-enable and re-enable baselines so creation-event alerts do not replay existing objects.
- Added schema 3 with hashed observed-object keys while retaining the v0.1.x pending-user delivery keys and history.
- Added event-specific subjects and minimal, sanitized user or peer details.
- Added read-only `/api/peers` polling only when peer-added alerts are enabled; user event types share one `/api/users` request per cycle.
- Added tests for creation baselines, enable/disable transitions, approval-to-joined transitions, retries, multi-recipient completion, schema migration, restart persistence, malformed peer data and end-to-end TLS delivery for all four events.
- Documented the required deployment structure and mandatory Linux UID/GID 10001 secret-file ownership.

- Default Compose deployment pulls the versioned image from GitHub Container Registry.
- Added an explicit local-build Compose override and a dev-to-main contribution flow.
- Main updates publish a `main` preview image; stable release publication remains explicit and versioned image tags are not overwritten.
- Added OCI source, license, version and revision metadata to locally and remotely built images.

## [0.1.0] - 2026-09-12

- Independent read-only polling of pending regular users through the NetBird API.
- Provider-agnostic TLS SMTP and separate recipient delivery.
- Optional validated SMTP sender display name while retaining a valid envelope address.
- Persistent SQLite deduplication, failed-attempt ordering and safe corruption behavior.
- Configuration checks, dry run, test email, once mode and healthcheck.
- Restricted Docker Compose deployment and pinned Python base image.
- Synthetic unit/TLS integration tests and deployment/security/legal documentation.

Live acceptance testing completed against self-hosted NetBird Management v0.78.1 and Zoho SMTP before release.
