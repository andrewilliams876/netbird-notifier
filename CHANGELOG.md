# Changelog

## [0.1.0] - 2026-09-12

- Independent read-only polling of pending regular users through the NetBird API.
- Provider-agnostic TLS SMTP and separate recipient delivery.
- Persistent SQLite deduplication, failed-attempt ordering and safe corruption behavior.
- Configuration checks, dry run, test email, once mode and healthcheck.
- Restricted Docker Compose deployment and pinned Python base image.
- Synthetic unit/TLS integration tests and deployment/security/legal documentation.

Live acceptance testing completed against self-hosted NetBird Management v0.78.1 and Zoho SMTP before release.
