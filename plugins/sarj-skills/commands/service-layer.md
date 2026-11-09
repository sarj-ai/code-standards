# Service boundaries

Apply [protocol](../skills/audit-protocol/SKILL.md).

Move privileged client work/presentation policy to an authorized boundary only
when contracts or measured cost improve. Add layers for real substitution/policy,
not simple CRUD. Keep deploy-varying settings at a typed startup boundary; inspect
unsafe fallbacks without turning stable constants into settings.

Trace deployment accounts/projects, service origins, resource identifiers, local
paths and operational tuning to their configuration owner. Externalize values
that vary by deployment; reuse existing inputs instead of adding parallel env
names. Parse and validate required settings once at startup, fail before remote
effects when absent/invalid, and inject the validated values into consumers.
Production fallbacks must not silently select another account or service.

| File/runtime | Configuration boundary to inspect |
| --- | --- |
| Python | Typed startup settings from environment or the existing settings loader; inject settings into services instead of repeated environment reads. |
| JavaScript/TypeScript | Validated server startup env or the platform's runtime bindings; keep secrets out of public build variables visible to clients. |
| Shell/Make | Required, quoted shell variables such as `${ACCOUNT_ID:?required}`; respect Make versus shell expansion and use quoted argument passing. |
| GitHub Actions YAML | Repository/environment `vars` for deployment values and `secrets` for credentials, passed through `env` or action inputs with validation before deployment. |
| Terraform/HCL | Typed module inputs supplied by caller configuration, tfvars or `TF_VAR_`; reuse resource/data references and locals for fixed shared values. |
| Compose/Kubernetes/Dockerfile | Native environment/config/secret references and supported interpolation; verify precedence, and keep credentials out of image `ARG`/`ENV` layers. |
| JSON/JSONC/TOML/INI | The consuming tool's supported config/env interface or an explicit generation step; these formats do not inherently expand `${VAR}`. |
| SQL | Bound application parameters or explicit migration/session configuration; preserve schema names and immutable migration literals. |
| Swift/Kotlin/native apps | Platform build/runtime configuration for public deployment values; packaged values are extractable, so keep privileged secrets at an authorized server or secret store. |
| Markdown/examples | Document required variable names and safe placeholders; preserve deterministic fixtures, public protocol constants and illustrative literals. |

Keep reviewed security allowlists and expected deployment identities independently
authoritative. Reading both a target and its expected identity from the same env
setting removes the check. Do not externalize policy, snapshots or stable
constants merely because they look like deployment values; no mechanical env
autofix can establish their owner.

Trace acquisition/close ownership through the last consumer, including lazy
responses. FastAPI provider changes must preserve authorization/security schema:
`Security` and `Depends` can differ for the same callable.

Reuse compatible write commands without widening fields/access. Preserve
omitted/null, update-only, per-key authorization, ordering, results and atomic
transitions. Require observable alias/effect evidence for mutation/discarded-copy
findings; copy changed ancestors, preserve intentional stateful APIs.
