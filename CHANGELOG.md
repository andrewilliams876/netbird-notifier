# Changelog

## Unreleased

- Default Compose deployment pulls the versioned image from GitHub Container Registry.
- Added an explicit local-build Compose override and a dev-to-main contribution flow.
- Release and container publication now require a manually started workflow; versioned image tags are not overwritten.
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
