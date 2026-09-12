# Legal and licensing findings

Reviewed 2026-09-12. This is a documented technical/licensing assessment, not legal advice or a guarantee against claims. The owner reports open-source self-hosted NetBird Management v0.78.1 and Dashboard v2.92.0. The deployed binaries and any separately accepted contracts have not been inspected.

## Conclusion within the reviewed scope

An independently written program using the documented public users and peers APIs, with authorized credentials, is a reasonable architecture for this project. It does not copy NetBird implementation code, link its internal libraries, modify its services, invoke its built-in notification system, or bypass license checks. Similarity to a paid feature alone does not establish that the integration infringes a license; equally, it does not establish legal clearance. Contract scope, implementation, branding and applicable law still matter.

## Source licenses

The [v0.78.1 root license](https://github.com/netbirdio/netbird/blob/v0.78.1/LICENSE) assigns BSD-3-Clause to most of the repository and identifies `management/`, `signal/`, `relay/`, and `combined/` as AGPLv3 exceptions. Review the [management license](https://github.com/netbirdio/netbird/blob/v0.78.1/management/LICENSE) and any files actually incorporated when evaluating a derivative work. This notifier incorporates no NetBird source or binaries. Its own proposed license would not change NetBird's licenses.

The [FSF aggregation discussion](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation) explains that separate processes and communication mechanisms can support separate-work treatment, but the substance of communication also matters. Container boundaries alone do not settle that question. Our independent HTTP client design supports, but does not legally prove, a separate-work analysis.

## Public API and feature documentation

The [API introduction](https://docs.netbird.io/api) expressly presents the API for application/script automation. The documented [users](https://docs.netbird.io/api/resources/users) and [peers](https://docs.netbird.io/api/resources/peers) resources expose the fields used for the four implemented alert categories. The [v0.78.1 users handler](https://github.com/netbirdio/netbird/blob/v0.78.1/management/server/http/handlers/users/users_handler.go) implements a user-list GET handler. Authenticated read-only access to both resource lists was confirmed against the owner's deployment; that technical test does not determine contractual permission.

The current [notifications page](https://docs.netbird.io/manage/settings/notifications) says built-in notifications are available in NetBird Cloud and self-hosted Enterprise, and that open-source self-hosted NetBird does not include them. The [Enterprise overview](https://docs.netbird.io/selfhosted/enterprise) distinguishes self-hosted Enterprise from Cloud plans. This project independently observes documented public API resources and delivers its own mail; it does not activate, call, patch, or copy the built-in notification implementation. That technical separation supports the architecture but is not a legal determination about every contract or jurisdiction.

## Contracts: do not conflate editions

The [SaaS terms](https://netbird.io/terms), section 1, describe hosted software and related services. Section 8 contains broad restrictions around personal-data harvesting, automated access, disruption and security circumvention; section 4 reserves IP rights. Those restrictions deserve clarification for cloud use despite the automation documentation. We do not infer that they automatically govern all open-source self-hosted use, or that API documentation overrides a contract. This application is scoped to self-hosting and refuses NetBird-owned hosts.

The [Commercial & PoC self-hosted EULA](https://netbird.io/self-hosted-EULA) includes restrictions on modification/reverse engineering (4.1), third-party managed services (4.2), and circumvention of license/usage/security controls (4.3). Section 9.2 recognizes separate open-source component licenses; proprietary rights are not expanded by them. Review this agreement and any higher-priority order/master agreement if Enterprise/proprietary binaries or a PoC are involved. The owner's reported open-source edition is materially different, but accepted agreements still require checking.

No express standalone API permission covering this exact notifier, and no separate comprehensive trademark policy, was established in the reviewed public sources. This is a research limit, not an assertion that no such terms exist.

## Branding and personal data

Use NetBird only descriptively to identify compatibility. Do not use its logo, claim official status/endorsement, or describe the project as a paid-feature/license bypass. The README carries an independence statement. Relevant IP reservations are in the SaaS terms; any commercial naming dispute would need qualified review.

Administrators can receive user names, email addresses and IDs or peer names, hostnames, addresses and IDs through their mail provider. Restrict enabled events and recipients, review the organization's lawful basis and provider arrangements as applicable, and apply retention/access controls. State hashes are pseudonymous, not guaranteed anonymous. This assessment does not determine compliance with a particular organization's data-protection obligations.

## Before public release

Confirm the actual edition/binary provenance, any applicable contracts, copyright attribution and our license. Recheck source terms on release. Seek qualified advice or written vendor clarification if distributing copied components, selling managed services, using proprietary/cloud features, encountering restrictive contracts, or requiring legal assurance beyond this assessment.

Optional inquiry draft (not sent):

> We are developing an independent open-source notifier for our open-source self-hosted NetBird deployment. It uses an authorized read-only identity to GET the documented `/api/users` and `/api/peers` resources, compares snapshots locally, and sends selected SMTP alerts through our own mail provider. It copies no NetBird code, modifies no NetBird services, and does not call the built-in notification system. Are there applicable API or trademark terms, or other restrictions we should review for this independent integration with a clear non-affiliation statement?
