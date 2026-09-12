# Roadmap

These are proposals, not implemented features or delivery promises. First release scope is pending regular-user email alerts.

| Future capability | Candidate data source | Investigation required |
| --- | --- | --- |
| New/deleted peers | `/api/peers` snapshots; audit activity | Startup baseline, stable IDs, missed events, deletion versus permission changes |
| Pending peer approval | Peer approval fields where exposed | Edition/version availability; never bypass a restricted feature |
| Routing-peer disconnect/recovery | Peer connectivity plus Networks/router and legacy Routes configuration | Correct routing membership, redundant routers, debounce duration, outage/recovery state |
| New users/service users | `/api/users` snapshots or audit activity | Baseline versus new event, identity sync timing and service-user classification |
| Setup-key events | `/api/setup-keys` snapshots and audit activity | Creation, expiry, revocation, usage semantics; never email actual key material |
| Webhooks | Independent outbound delivery adapter | HTTPS validation, authentication/signatures, SSRF controls, retries, redaction and idempotency |
| Slack | Optional independent webhook adapter | Secret URL handling, payload escaping, rate limits and safe delivery retry |
| Digests/rules | Internal notification queue | Global quotas, quiet hours, backlog visibility, per-event recipients and deduplication |
| Observability | Local operational metadata | Failure counters, queue depth and external health monitoring without user-data leakage |

The current [peers API](https://docs.netbird.io/api/resources/peers) and [setup-keys API](https://docs.netbird.io/api/resources/setup-keys) are starting points, not proof that every proposed event is exposed in every edition. The [events API](https://docs.netbird.io/api/resources/events) documents `/api/events/audit`; verify event codes, retention, completeness and pagination against supported versions. Do not confuse audit access with cloud-only traffic-event features.

Before implementing each event: establish a minimum compatible version, least-privilege access, a synthetic fixture, live feasibility evidence, event lifecycle and restart behavior. Snapshot comparison cannot reconstruct all events during downtime. Detecting a disconnected peer is not automatically evidence that routing has failed.
