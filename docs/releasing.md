# Release process

The owner confirmed real deployment testing and authorized publication of the public `netbird-notifier` repository.

## Prepare locally

1. Complete `docs/acceptance.md` and record evidence in validation. Resolve material security findings; do not label skipped checks as passed.
2. Confirm repository owner/name/visibility, copyright attribution, and license choice. This release uses `andrewilliams876/netbird-notifier`, public visibility, and MIT attributed to Andre Williams.
3. Enable a private vulnerability-reporting channel and update SECURITY.md. Set branch protection/required CI where available.
4. Recheck NetBird terms and compatibility assumptions. Update dated findings.
5. Pin/review the base digest, run the application tests in Windows and the Linux container, validate Compose, scan the final image and development dependencies, and review remaining advisories.
6. Inspect `git status`, tracked files and history. Use a dedicated secret scanner as well as manual review. `.gitignore` is not a retroactive secret remover. Rotate any exposed credentials rather than merely deleting them.
7. Confirm the repository contains only this project, no `.env`, secrets, state, generated private fixtures or unrelated ChatGPT material.

## Publish

Create/configure the agreed GitHub repository, push only reviewed commits, and verify CI. Move the proposed changelog entry to version 0.1.0 with the actual release date. Create the agreed annotated/signed tag (normally `v0.1.0`) and publish release notes stating features, supported/tested environment, delivery limitations, upgrade/state instructions and security status.

Do not publish a container registry image unless separately included in the agreed release scope. If distributing images, include provenance/SBOM and applicable third-party notices. Never distribute the development/test image as the runtime image.

Release notes draft: independent pending-user SMTP notifier for self-hosted NetBird; verified HTTPS and configurable SMTP TLS, persistent per-recipient deduplication, hardened Compose and operational commands. SMTP crash ambiguity and polling limitations remain. Insert actual live validation results before publication; do not use this draft as evidence of those results.
