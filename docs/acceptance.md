# Deployment acceptance

Use this checklist before approving a release. Record version, date and results without secrets or real profile data. Current target reported by the owner: NetBird Management v0.78.1, Dashboard v2.92.0, open-source self-hosted.

1. Confirm the HTTPS origin and dedicated identity role. Configure ignored `.env` and secret files locally. Confirm recipient addresses before sending mail.
2. Run Compose validation and `--check-config` as described in README. Verify the image runs as UID 10001 and reads mounted secrets without exposing their contents.
3. Run `--dry-run`. Compare the count against a known pending user in the dashboard. Also verify active/invited/service users do not count as pending regular users. Record role visibility.
4. Run `--test-email`; confirm it arrives in each configured inbox. Check the correct sender and subject and, if available, the provider's delivery/TLS information.
5. With continuous operation stopped, run `--once` against a deliberately chosen pending test account. Verify one alert per configured recipient.
6. Run `--once` again. Verify no additional alert. Start the service; wait through multiple polling intervals and check that duplicates do not appear.
7. Restart/recreate only the notifier while preserving its volume. Confirm deduplication remains intact.
8. Approve the test user manually through the normal NetBird dashboard, only if appropriate. Verify subsequent polling does not alert for that approved user. The notifier must never perform approval itself.
9. Using an isolated test configuration, test invalid token, incorrect SMTP credentials, unreachable endpoints, and untrusted TLS certificates. Verify safe logs, failed delivery retry, health expiry and recovery. Never weaken production TLS for testing.
10. Test backup/restore on an isolated volume. Verify a corrupt state file is preserved and fails visibly rather than resetting.
11. Confirm resource restrictions, no published ports, no Docker socket, read-only root and private state. Check the final image/dependency scan and tracked files for secrets.
12. Explicitly tell the maintainer that real testing succeeded before GitHub push/tag/release.

Only synthetic local tests may be run without production configuration. Receiving SMTP acceptance in a test server is not proof that Zoho or the real NetBird deployment works.
