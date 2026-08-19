# PR review rule mining evaluation

## Decision summary

The private review corpus contains 238 independently classified entries:

| Disposition | Count |
| --- | ---: |
| New Sarj warning rule | 7 |
| Existing Sarj coverage | 44 |
| Upstream/configuration coverage | 15 |
| Audit-only | 170 |
| Rejected deterministic form | 2 |

The complete one-to-one disposition ledger is in `docs/audits/pr-review-rule-mining.md`. Private source text, repository identities, paths, snippets, hashes, and contributor identities are intentionally absent from both public artifacts.

## Implemented candidates

| Engine | Rule | Code | Initial severity |
| --- | --- | --- | --- |
| Python | `no-redundant-literal-description` | SARJ422 | warning |
| Python | `require-nodecode-for-splitting-settings-field` | SARJ423 | warning |
| Python | `no-nested-pydantic-field-validator` | SARJ424 | warning |
| Python | `no-conftest-test-module-import` | SARJ425 | warning |
| SQL | `no-create-trigger` | SARJ114 | warning |
| ESLint | `no-router-refresh-polling` | — | warning |
| ESLint | `no-duplicate-lifecycle-refresh-listeners` | — | warning |

Local upstream-rule and Sarj-catalog searches found no reusable equivalent for these seven narrow signals. One private consumer had a repository-local trigger check; the SQL rule turns that policy into a reusable, parsed, documented Standards rule. The other 59 deterministically enforceable entries remain owned by existing Sarj rules or upstream tools rather than duplicated here.

## Labeled-case evaluation

All 68 focused test cases pass:

- Python: 40 cases across the four new rules.
- SQL: 11 cases.
- TypeScript: 17 cases.

The cases include public documentation examples, multiple positive forms, safe near-misses, aliasing, shadowed bindings, nested functions, comments and string literals, generated paths, test paths, dialect exclusions, and duplicate-diagnostic checks. Observed results were 0 false positives and 0 false negatives in the labeled set.

## Local corpus calibration

Tracked files from four already-local private corpora were evaluated without publishing corpus identities or contents. Across 4,124 Python, SQL, TypeScript, and TSX files (25,210,233 bytes):

- The four Python rules produced 0 findings.
- The SQL rule produced 5 findings; all 5 were manually inspected and were true PostgreSQL trigger definitions.
- A direct ESLint pass over 1,332 tracked JavaScript/TypeScript-family files produced 4 router-polling findings and 0 duplicate-lifecycle-listener findings; all 4 findings were manually inspected and were true positives.
- No duplicate diagnostics were observed.

These are local tracked snapshots, not a publication-grade public corpus manifest. They support warning-stage introduction but not promotion to error. Promotion should require repeatable consumer manifests and reviewed zero-false-positive evidence after rollout.

## Exclusions and known limitations

- Generated and test files are excluded where the production anti-pattern is not actionable there.
- The SQL rule excludes dumps and inputs not identified as PostgreSQL.
- The Literal-description rule requires a narrow domain-only phrase and exact quoted-value agreement; imported enum definitions are outside its file-local scope.
- The settings rule covers direct `BaseSettings` fields and direct pre-validators that split the validator value parameter; custom source pipelines and indirect helpers remain review concerns.
- The nested-validator rule reports only a nested field validator that names a field on its outer direct `BaseModel`.
- The router rule resolves the imported router hook and router binding and ignores refresh calls inside a separate nested function.
- The lifecycle rule requires the same resolved callback binding in one lexical function scope.
- None of the rules autofix because the correct replacement requires domain or architectural judgment.

## Performance

Repeated local timings used tracked files from one representative private corpus and compared the exact parent revision with the candidate:

| Engine | Files | Baseline median | Candidate median | Result |
| --- | ---: | ---: | ---: | --- |
| Python, complete rule set | 1,277 | 26.458 s | 27.279 s | 3.1% overhead |
| SQL, complete rule set | 226 | 0.294 s | 0.307 s | 4.5% overhead |
| ESLint parse-only vs. the two candidates | 824 | 4.251 s | 3.933 s | no measurable regression |

All measured results remain within the warning-introduction budget of less than 25% warm-run slowdown. ESLint ordering and filesystem cache noise made the candidate median lower; this is treated only as evidence of no regression, not as a speedup claim.

## Rollout recommendation

Ship all seven rules as warnings in the 6.3.0 Standards bundle. Do not promote them to errors in this change. Promotion requires clean warning telemetry across registered consumers, reviewed findings, stable exclusion behavior, and the normal Sarj promotion workflow.

The repository-wide `make verify` gate passes, including generated-artifact checks, documentation build, formatting, Ruff, ESLint, dogfood, basedpyright, TypeScript typechecking, package builds, and all package test suites.
