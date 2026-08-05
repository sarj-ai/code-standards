# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability in the packages,
release workflow, or build infrastructure. Use GitHub's
[private vulnerability reporting](https://github.com/sarj-ai/standards/security/advisories/new)
so reports and supporting evidence remain confidential.

Include the affected package and version, impact, reproduction steps, and any
suggested mitigation. We will acknowledge a report within 3 business days,
provide a status update within 7 business days, and coordinate disclosure after
a fix is available. Please allow up to 90 days for coordinated disclosure unless
active exploitation or another material risk requires a faster timeline.

## Supported versions

Security fixes are released for the latest published version. Consumers should
use `sarj-standards update --check` to detect a coherent bundle upgrade and
review the generated changes before applying them.
