# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not
open a public issue for a suspected vulnerability, leaked credential, malicious
dependency, or package-registry compromise.

Include the affected package and version, reproduction details, impact, and any
known mitigations. We will acknowledge a report as soon as practical and keep
coordination private until a fix is available.

## Supported releases

Only the latest release of each `@sarj/*` npm package and `sarj-*` PyPI package
receives security fixes. Consumers should pin exact versions or lockfiles and
update after reviewing provenance and release notes.

## Release integrity

Releases are built only by GitHub Actions after a version-changing merge to
`main`. npm and PyPI authentication uses short-lived OIDC trusted publishing;
long-lived registry tokens are not used. PyPI publishes wheels with attestations.
All third-party Actions are pinned to full commit SHAs.

