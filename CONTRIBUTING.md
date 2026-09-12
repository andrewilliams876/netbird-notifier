# Contributing

The repository is being prepared for its first release. Confirm its final license before submitting external contributions.

Use Python 3.12+, install `requirements-dev.txt`, and run `python -m unittest discover -s tests -v`. Tests use synthetic data only. Production has no third-party Python dependencies. Keep imports, validation and networking straightforward; add tests for meaningful behavior and failure modes rather than implementation details.

For Docker testing, build the production image, then `docker build -f Dockerfile.test -t netbird-notifier-tests:local .` and run the test image with a writable `/tmp` and read-only root. Do not publish the test image as the production image.

Before submitting changes:

- Explain the user-visible problem, final behavior and validation.
- Preserve HTTPS verification, STARTTLS enforcement, least privilege and secret-safe logs.
- Do not introduce any NetBird mutations or license-gated endpoint dependencies.
- Include state migrations and restart/rollback tests when changing persistence.
- Use only sanitized fixtures. Never attach genuine API payloads, tokens or SMTP credentials.
- Update configuration, operations, changelog and security notes where behavior changes.
- Discuss broader alert types against the roadmap before expanding the first version.

Report security issues privately following SECURITY.md. CI must never use real NetBird or SMTP secrets for pull-request tests.
