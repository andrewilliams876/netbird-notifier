# Security policy

Security fixes are provided for the latest released version. Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/andrewilliams876/netbird-notifier/security/advisories/new). Do not disclose exploitable vulnerabilities or real credentials in public issues.

## Deployment requirements

- Use a dedicated least-privilege NetBird token and dedicated SMTP identity/app password.
- Store credentials in ignored secret files, restrict Windows ACLs to the operator and required system/Docker identities, and use disk encryption appropriate to the host.
- Linux Compose file secrets are bind mounts. Ensure UID 10001 can read the files, for example with appropriate ownership and restrictive file modes; do not make them globally readable as a blanket fix. Test actual readability using `--check-config`.
- Compose secrets are not encrypted at rest by Compose. Docker/host administrators can access them. Treat Docker control as privileged host access.
- Retain verified TLS. Mount a CA bundle for a private CA rather than disabling verification.
- Restrict outbound traffic to the NetBird origin, SMTP server and required DNS with host/network policy where practical. Compose does not supply an egress allowlist.
- Keep the state directory private and on local storage. Hashes are pseudonymous identifiers, not guaranteed anonymization. Email contents include the pending user's name/email/ID; restrict recipients and mailbox retention accordingly.
- Keep one daemon per volume. Back up state consistently and monitor disk capacity.
- Never publish `.env`, `secrets/`, state, mailbox contents, debug bundles or genuine API responses.
- Rebuild and review image/dependency updates. Digest pinning prevents unnoticed changes but also requires deliberate patch updates.

The notifier is not an approval authority, does not verify a user's identity, and does not enforce NetBird access policy. Verify requests in the trusted dashboard before approving them.

See [review and residual risks](docs/security-review.md) and [legal considerations](docs/legal-and-licensing.md).
