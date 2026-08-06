# sarj-iac-lint

Custom Terraform / IaC lint rules — stdlib only, line/block based, pre-commit-friendly.
Mined from recurring infra review comments across the org.

```bash
uv tool install sarj-iac-lint
```

## Rules

| Code | Rule | What it flags |
|------|------|---------------|
| SARJ201 | `require-deletion-protection` | A stateful resource (Cloud SQL, GKE, BigQuery, Spanner, AlloyDB, Bigtable, RDS, DynamoDB, ElastiCache, DocumentDB, Neptune, Azure databases, Cosmos DB, ...) without `deletion_protection = true`. |
| SARJ202 | `no-comment-cruft` | Commented-out Terraform/HCL and section-banner / divider comments. |
| SARJ203 | `require-prevent-destroy-on-irreplaceable` | An irreplaceable bucket, secret, or artifact registry without an effective provider-side deletion guard or `lifecycle { prevent_destroy = true }`. |

Terraform safety rules scan `.tf` files; comment hygiene also scans `.hcl` and `.tfvars`. `.yaml`/`.yml`
(Helm/k8s/Compose) are scanned by `no-comment-cruft` for banners only.

## Pre-commit

```yaml
- repo: https://github.com/sarj-ai/standards
  rev: iac-v0.6.0
  hooks:
    - id: sarj-require-deletion-protection
    - id: sarj-no-comment-cruft-iac
    - id: sarj-require-prevent-destroy-on-irreplaceable
```

## CLI

```bash
sarj-iac-lint check --rule require-deletion-protection iac/
sarj-iac-lint list-rules
```

Diagnostic format is `path:line:col: CODE message` — Ruff-compatible.
`--exit-zero` reports without failing (warn mode).

## Adoption

All three rules are designed for hard (blocking) adoption; inspect existing
findings before enabling them repository-wide.

Variable/expression-gated protection is not proof of protection:
`deletion_protection` must be a literal
`true`, or `lifecycle { prevent_destroy = true }` must be present. Protection
must sit on the resource itself: a flag nested in `settings { ... }` is the
API-side switch and does not stop `terraform destroy`.

Memorystore Redis is protected when `deletion_protection` is omitted; an
explicit `false` remains unsafe. Current Google resources covered by SARJ201
also accept their documented literal `deletion_policy = "PREVENT"` guard;
AlloyDB is deliberately excluded because its same-named policy means
`DEFAULT`/`FORCE`, not Terraform deletion prevention.

`require-prevent-destroy-on-irreplaceable` accepts the current Google provider's
literal `deletion_policy = "PREVENT"` for Cloud Storage buckets, Secret Manager
secrets, and Artifact Registry repositories. Secret Manager also accepts literal
`deletion_protection = true`. Other values and expressions are not proof of
protection; `lifecycle { prevent_destroy = true }` remains the portable guard.
The rule also exempts resources explicitly declared disposable with literal
`force_destroy = true`.

## Suppression

Inline `# sarj-noqa: SARJ201 — <reason>` on the reported line. SARJ201 and
SARJ203 report the `resource` line.
