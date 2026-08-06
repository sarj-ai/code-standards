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
| SARJ203 | `require-prevent-destroy-on-irreplaceable` | A bucket, Secret Manager secret, or artifact registry — which expose no `deletion_protection` argument at all — without `lifecycle { prevent_destroy = true }`. |

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

All four rules are designed for hard (blocking) adoption; inspect existing
findings before enabling them repository-wide.

Variable/expression-gated protection is not proof of protection:
`deletion_protection` must be a literal
`true`, or `lifecycle { prevent_destroy = true }` must be present. Protection
must sit on the resource itself: a flag nested in `settings { ... }` is the
API-side switch and does not stop `terraform destroy`.

`require-prevent-destroy-on-irreplaceable` covers the stores SARJ201 cannot,
because they have no protection argument to check. It exempts only resources
explicitly declared disposable with literal `force_destroy = true`.

## Suppression

Inline `# sarj-noqa: SARJ201 — <reason>` on the reported line. SARJ201 and
SARJ203 report the `resource` line.
