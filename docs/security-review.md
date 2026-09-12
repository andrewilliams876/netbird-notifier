# Security review — 2026-09-11

Scope: Python notifier including v0.2.0 user/peer snapshot detection, configuration, SQLite persistence and migration, Compose/Docker build files, and synthetic tests. This is an implementation review, not an independent penetration test or security certification.

## Controls reviewed

| Threat | Control and verification |
| --- | --- |
| Token disclosure through redirects | Redirect handler refuses redirects; unit and local HTTPS tests |
| TLS interception/downgrade | Verified contexts, TLS 1.2 minimum, mandatory STARTTLS; untrusted certificate and hostname tests |
| Credentials in logs | Static errors and safe categories, no server response bodies; secret-redaction tests |
| Email header injection | Bare ASCII configured addresses, static subject, profile values only in sanitized plain-text body |
| API mismatch causing false alerts | Strict arrays, unique bounded IDs, user booleans/status checks, size/content-type checks; a malformed endpoint aborts the whole cycle before baseline or delivery |
| First-start notification flood | Silent per-event baseline for joined-user, service-user-created and peer-added detection; enable/disable transition tests |
| Existing history lost during upgrade | Schema-3 additive migration; pending-user delivery keys retain their v0.1.x format; migration and restart tests |
| Profile identifiers retained in state | Delivery and observed-object keys are SHA-256 digests; database tests reject raw IDs and recipient addresses |
| Repeated emails after restart | Persistent per-recipient key; restart tests with SQLite and actual local TLS delivery |
| Simultaneous duplicate send | SQLite writer lock across check/send/commit; contention test; single daemon recommended |
| Lost state from corruption | Integrity check and fail-stop; corrupt file preserved in test |
| SMTP acceptance with partial recipient failure | One envelope recipient per delivery; successful recipients retained |
| Failed delivery starving later alerts | Persist failed attempt ordering; prioritize unattempted then oldest failures; regression test |
| Container compromise | UID/GID 10001, read-only root, no capabilities, no-new-privileges, resource limits and no exposed ports |
| Secrets entering image | Production COPY selects only notifier source; Docker context uses allowlist |

## Residual risks and limits

- SMTP and SQLite cannot atomically commit together. Crash/acknowledgment ambiguity can repeat accepted mail. Reused Message-ID is advisory only.
- TLS protects transport to the SMTP relay, not end-to-end mailbox confidentiality. Profile text remains untrusted and email clients may auto-link it.
- A compromised host/Docker administrator can read secrets or alter state. An API endpoint that is itself compromised can falsify data. Configuration is trusted input.
- Auditor may read more than users and peers. GET-only application code does not narrow an overprivileged token.
- Creation alerts are inferred from API snapshots rather than an authoritative event stream. They can miss objects created and removed between successful polls. If an unseen object disappears after SMTP failure, its details are unavailable for another delivery attempt.
- A creation event's first enabled poll is intentionally silent. A configuration that is disabled and re-enabled without the notifier completing a poll while disabled cannot prove that there was a disabled interval.
- Network timeout is per socket operation; a slow peer or many SMTP commands can make a cycle longer. Stop signals are handled between deliveries; forced shutdown can interrupt one delivery and create ambiguity.
- Health reflects a recent successful polling cycle; it is not proof of email arrival. Long backlogs or slow providers can temporarily make a functioning process unhealthy. Docker does not restart solely due to unhealthy status.
- New work is prioritized over failures; an unbounded influx can delay retries. Per-poll caps limit attempts, not an absolute daily quota. Digest and stronger global rate policy are future work.
- State grows with unique notifications, observed object digests and failures and has no automatic retention deletion. This preserves lifetime deduplication; operator monitoring and explicit retention policy are required.
- SQLite on network/shared filesystems is unsupported. Multiple separate volumes can send duplicates. This is not a distributed delivery system.
- Runtime has no third-party Python packages or package installer; Python, OpenSSL, SQLite and OS packages still require vulnerability monitoring. See validation for the point-in-time scan result; no vulnerability-free claim is made.

## Release conditions

Resolve material findings, complete real NetBird/SMTP acceptance tests, inspect image contents and ignored/tracked files, scan the final image, confirm reporting channel and license, and obtain the owner's testing confirmation before publication.
