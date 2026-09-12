# Deployment acceptance

Use this checklist before approving a release. Record version, date and results without secrets or real profile data. Current target reported by the owner: NetBird Management v0.78.1, Dashboard v2.92.0, open-source self-hosted.

1. Confirm the HTTPS origin and dedicated identity role. Configure ignored `.env` and secret files locally. Confirm recipient addresses before sending mail.
2. Run Compose validation and `--check-config` as described in README. Verify the image runs as UID 10001 and reads mounted secrets without exposing their contents.
3. Run `--dry-run`. Compare each enabled object count against the dashboard. Verify active/invited/service users do not count as pending regular users, only active regular users qualify for joined-user detection, and the peer count is visible when enabled. Record role visibility for both `/api/users` and `/api/peers`.
4. Run `--test-email`; confirm it arrives in each configured inbox. Check the correct sender and subject and, if available, the provider's delivery/TLS information.
5. With continuous operation stopped, run `--once`. Verify existing pending users can alert while the current active users, service users and peers are silently baselined. Record the non-sensitive `baselined` counts.
6. Create one controlled example for each enabled category: a pending regular user, an active joined user, a service user and a peer. Run or wait for a poll and verify the correct subject and minimum expected details once per configured recipient. Do not create production access solely for a test unless its lifecycle and cleanup are approved.
7. Run `--once` again. Verify no additional alert. Disable one creation event for a completed poll, create a controlled object, re-enable it, and verify the re-enable poll silently rebaselines instead of replaying that object. Then create another object and verify one alert.
8. Restart/recreate only the notifier while preserving its volume. Confirm deduplication and creation-event baselines remain intact.
9. Approve the pending test user manually through the normal NetBird dashboard, only if appropriate. Verify the pending alert does not repeat and, when joined-user alerts are enabled, the active transition produces its separate one-time alert. The notifier must never perform approval itself.
10. After a successful poll observes the test user is no longer pending, place the same identity into pending approval again. Verify exactly one new pending-user alert is delivered and subsequent polls do not repeat it.
11. Using an isolated test configuration, test invalid token, incorrect SMTP credentials, unreachable endpoints, malformed user/peer schemas and untrusted TLS certificates. Verify safe logs, failed delivery retry, health expiry and recovery. Never weaken production TLS for testing.
12. Test the schema-2-to-3 upgrade and backup/restore on an isolated volume. Verify old pending-user history remains effective and a corrupt state file is preserved and fails visibly rather than resetting.
13. Confirm resource restrictions, no published ports, no Docker socket, read-only root and private state. Check the final image/dependency scan and tracked files for secrets.
14. Explicitly tell the maintainer that real testing succeeded before merging `dev` into `main`, creating a version tag, or manually starting a release.

Only synthetic local tests may be run without production configuration. Receiving SMTP acceptance in a test server is not proof that Zoho or the real NetBird deployment works.
