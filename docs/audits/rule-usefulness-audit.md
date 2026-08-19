# Rule usefulness audit queue

This queue tracks every custom rule that was active when the audit began against two immutable, pre-adoption production corpora. Corpus identities, paths, source snippets, and commit hashes are intentionally omitted; the reproducible private evaluation record retains them. A historical hit proves reach, not precision. Zero findings flag a rule for applicability, selector, upstream-overlap, and removal review; they do not by themselves prove the rule is useless.

Evaluation coverage: an initial historical reach scan of all 177 rules active at audit start, plus seven rules added on `main` during the audit and the replacement Python candidate. The current catalog has 183 active rules. Native evaluations completed without runner issues; the original TypeScript evaluations covered 545 and 333 source files, excluded declared generated SDK paths, and recorded four and two parse failures respectively, so TypeScript zeroes are incomplete lower bounds. Timings and peak memory were not measured. A checkbox means the rule has a completed disposition, not merely that it executed. Unchecked rows remain follow-up tasks for applicability and precision classification.

## eslint

- [ ] `eslint:duplicate-test-body` — hit; inspect findings and record precision.
- [ ] `eslint:enforce-file-structure` — hit; inspect findings and record precision.
- [x] `eslint:get-delegates-to-get-many` — **ZERO — flagged**; removed and replaced after no historical or current reach.
- [ ] `eslint:iac-source-coupled-test` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-bare-return-from-test-catch` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-client-side-data-fetching` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-comment-cruft` — hit; inspect findings and record precision.
- [ ] `eslint:no-cors-wildcard-with-credentials` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-declaration-comment-wall` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-dynamic-sql` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-enum` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-fat-try-blocks` — hit; inspect findings and record precision.
- [ ] `eslint:no-generic-single-export-module` — hit; inspect findings and record precision.
- [ ] `eslint:no-hand-rolled-sleep` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-hand-rolled-spinner` — hit; inspect findings and record precision.
- [ ] `eslint:no-impossible-zod-literal-bounds` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-insecure-random-id` — hit; inspect findings and record precision.
- [ ] `eslint:no-json-stringify-error` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-log-only-catch` — hit; inspect findings and record precision.
- [ ] `eslint:no-long-comment` — **ZERO — flagged**; proposed retirement unless another pinned corpus supplies a concrete defect.
- [ ] `eslint:no-offset-pagination` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-positional-tuple-return` — hit; inspect findings and record precision.
- [ ] `eslint:no-raw-env` — hit; inspect findings and record precision.
- [ ] `eslint:no-raw-fetch-outside-clients` — hit; inspect findings and record precision.
- [ ] `eslint:no-repeated-string-literal` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-restated-comment` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-restated-jsdoc` — hit; inspect findings and record precision.
- [ ] `eslint:no-restricted-library-load` — **ZERO — flagged**; split ownership: upstream handles static imports; custom rule only dynamic loads.
- [ ] `eslint:no-secret-in-log` — hit; inspect findings and record precision.
- [ ] `eslint:no-select-star` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-sentinel-return-on-catch` — hit; inspect findings and record precision.
- [ ] `eslint:no-silent-promise-catch` — hit; inspect findings and record precision.
- [ ] `eslint:no-sleep-in-test-body` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-storage-in-stateless-modules` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-string-concat-in-loop` — hit; inspect findings and record precision.
- [ ] `eslint:no-tautological-expect` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-trailing-value-narration` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-type-member-comment-wall` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-typed-doc-sections` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-union-in-comment` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-unnecessary-use-client` — hit; inspect findings and record precision.
- [ ] `eslint:no-unsafe-mock-casting` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-vague-suppression-description` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:no-zod-native-enum` — **ZERO — flagged**; reconcile with installed zod/no-native-enum; retain only proven extra coverage.
- [ ] `eslint:prefer-await-in-async-return` — **ZERO — flagged**; revise or retire; no historical reach and existing async-return policy is adjacent.
- [ ] `eslint:prefer-constant-time-secret-compare` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-discriminated-union` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-immutable-module-constant` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-input-group-search` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:prefer-module-level-constant` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-module-level-schema` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-native-random-uuid` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:prefer-non-nullable-collection` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-schema-for-api-payload` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-semantic-colors` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-server-actions` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:prefer-shadcn-primitives` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-whole-object-assertion` — hit; inspect findings and record precision.
- [ ] `eslint:prefer-zod-infer` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:repeated-static-call-cases` — hit; inspect findings and record precision.
- [ ] `eslint:require-assert-never` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:require-fetch-timeout` — hit; inspect findings and record precision.
- [ ] `eslint:require-port-for-service` — hit; inspect findings and record precision.
- [ ] `eslint:require-static-next-matcher` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:require-zod-form-validation` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:source-coupled-test` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:stepdown` — hit; inspect findings and record precision.
- [ ] `eslint:store-insert-requires-on-conflict` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `eslint:test-loops-over-literal-cases` — hit; inspect findings and record precision.
- [ ] `eslint:zod-naming-convention` — hit; inspect findings and record precision.

## python

- [ ] `python:created-at-order-requires-tiebreaker` — hit; inspect findings and record precision.
- [ ] `python:defect-xfail-requires-strict` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:docstring-args-restate-signature` — hit; inspect findings and record precision.
- [ ] `python:docstring-returns-restate-signature` — hit; inspect findings and record precision.
- [ ] `python:duplicate-test-body` — hit; inspect findings and record precision.
- [ ] `python:duplicated-override-docstring` — hit; inspect findings and record precision.
- [ ] `python:fastapi-openapi-contract` — hit; inspect findings and record precision.
- [ ] `python:fixture-returns-bare-tuple` — hit; inspect findings and record precision.
- [ ] `python:iac-source-coupled-test` — hit; inspect findings and record precision.
- [ ] `python:invalid-pydantic-field-default` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:kwarg-heavy-construction-in-test` — hit; inspect findings and record precision.
- [ ] `python:mock-without-spec` — hit; inspect findings and record precision.
- [ ] `python:negative-only-http-status-assertion` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:no-aggregation-in-store-query` — hit; inspect findings and record precision.
- [ ] `python:no-comment-cruft` — hit; inspect findings and record precision.
- [ ] `python:no-cors-wildcard-with-credentials` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:no-duplicate-dunder-all-entry` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:no-file-level-escape-hatch-noqa` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [x] `python:no-file-level-suppression` — **ZERO — flagged**; retired because enabled Ruff PGH003 owns the supported cases.
- [ ] `python:no-first-party-private-import` — hit; inspect findings and record precision.
- [ ] `python:no-frozen-after-validator-field-write` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:no-gen-random-uuid-in-sql` — hit; inspect findings and record precision.
- [ ] `python:no-generic-single-export-module` — hit; inspect findings and record precision.
- [ ] `python:no-hidden-constructor-fallback` — hit; inspect findings and record precision.
- [ ] `python:no-isinstance-union-chain` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:no-long-comment` — **ZERO — flagged**; retire unless another pinned corpus provides a true positive.
- [ ] `python:no-offset-pagination` — hit; inspect findings and record precision.
- [ ] `python:no-optional-tenant-predicate` — hit; inspect findings and record precision.
- [ ] `python:no-query-with-many-joins` — **ZERO — flagged**; revise or retire; broadening to analytical SQL produced false positives.
- [ ] `python:no-repeated-string-literal` — hit; inspect findings and record precision.
- [ ] `python:no-restated-comment` — hit; inspect findings and record precision.
- [ ] `python:no-secret-in-log` — hit; inspect findings and record precision.
- [ ] `python:no-select-star` — hit; inspect findings and record precision.
- [ ] `python:no-sentinel-return-on-except` — hit; inspect findings and record precision.
- [ ] `python:no-stdlib-logging` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:no-string-concat-in-loop` — hit; inspect findings and record precision.
- [ ] `python:no-tautological-expect` — **ZERO — flagged**; merge or retire after upstream ownership check.
- [ ] `python:no-typed-doc-sections` — hit; inspect findings and record precision.
- [ ] `python:no-unique-violation-message-match` — hit; inspect findings and record precision.
- [ ] `python:opaque-parametrize-case-needs-id` — hit; inspect findings and record precision.
- [ ] `python:over-mocked-test` — hit; inspect findings and record precision.
- [ ] `python:prefer-class-row` — hit; inspect findings and record precision.
- [ ] `python:prefer-constant-time-secret-compare` — hit; inspect findings and record precision.
- [ ] `python:prefer-fstring-over-concat` — hit; inspect findings and record precision.
- [ ] `python:prefer-immutable-module-constant` — hit; inspect findings and record precision.
- [ ] `python:prefer-library-fake` — **ZERO — flagged**; retire unless another pinned corpus supplies a true positive.
- [ ] `python:prefer-match-assert-never` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:prefer-match-type-dispatch` — hit; inspect findings and record precision.
- [ ] `python:prefer-module-level-constant` — hit; inspect findings and record precision.
- [ ] `python:prefer-namedtuple-over-tuple-return` — hit; inspect findings and record precision.
- [ ] `python:prefer-nominal-id-types` — hit; inspect findings and record precision.
- [ ] `python:prefer-non-nullable-collection` — hit; inspect findings and record precision.
- [ ] `python:prefer-or-pattern` — hit; inspect findings and record precision.
- [ ] `python:prefer-self-documenting-constant` — **ZERO — flagged**; expand narrowly for unambiguous duration narration.
- [ ] `python:prefer-self-type-annotation` — hit; inspect findings and record precision.
- [ ] `python:prefer-str-enum` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:prefer-struct-over-namedtuple` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:prefer-timedelta-for-durations` — hit; inspect findings and record precision.
- [ ] `python:prefer-walrus-comprehension-filter` — hit; inspect findings and record precision.
- [ ] `python:prefer-walrus-regex-match` — hit; inspect findings and record precision.
- [ ] `python:prefer-walrus-stream-loop` — hit; inspect findings and record precision.
- [ ] `python:preserve-declared-nominal-id` — hit; inspect findings and record precision.
- [ ] `python:preserve-enum-types` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:production-derived-test-cases` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:pydantic-at-boundaries` — hit; inspect findings and record precision.
- [ ] `python:redundant-class-docstring` — hit; inspect findings and record precision.
- [ ] `python:redundant-docstring` — hit; inspect findings and record precision.
- [ ] `python:redundant-module-docstring` — **ZERO — flagged**; retire unless another pinned corpus provides a true positive.
- [ ] `python:repeated-static-call-cases` — hit; inspect findings and record precision.
- [ ] `python:require-keyword-only-swap-prone-params` — hit; inspect findings and record precision.
- [ ] `python:require-port-for-service` — hit; inspect findings and record precision.
- [ ] `python:require-pydantic-for-external-json` — hit; inspect findings and record precision.
- [ ] `python:require-pydantic-ordinal-lower-bound` — **ZERO — flagged**; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `python:require-validated-row-factory` — hit; inspect findings and record precision.
- [ ] `python:restated-test-docstring` — hit; inspect findings and record precision.
- [ ] `python:source-coupled-test` — hit; inspect findings and record precision.
- [ ] `python:sql-requires-injected-pool-owner` — hit; inspect findings and record precision.
- [ ] `python:stepdown` — hit; inspect findings and record precision.
- [ ] `python:store-insert-requires-on-conflict` — hit; inspect findings and record precision.
- [ ] `python:test-phase-label-comment` — **ZERO — flagged**; retire unless another pinned corpus supplies a true positive.
- [ ] `python:trailing-value-narration` — **ZERO — flagged**; expand narrowly for literal-plus-unit narration.
- [ ] `python:trivially-true-assertion` — **ZERO — flagged**; merge or retire after upstream ownership check.
- [ ] `python:uncontrolled-randomness-in-test` — **ZERO — flagged**; retire unless another pinned corpus supplies a true positive.
- [ ] `python:unused-mock-setup` — hit; inspect findings and record precision.

## sql

- [ ] `sql:add-constraint-requires-not-valid` — hit; inspect findings and record precision.
- [ ] `sql:enforce-timestamptz` — hit; inspect findings and record precision.
- [ ] `sql:idempotent-ddl` — hit; inspect findings and record precision.
- [ ] `sql:index-concurrently` — hit; inspect findings and record precision.
- [ ] `sql:insert-requires-on-conflict` — hit; inspect findings and record precision.
- [ ] `sql:no-offset-pagination` — **ZERO — flagged**; proposed warning-only parser refinement for multiline SQL and `OFFSET 0`, not lexical broadening.
- [ ] `sql:no-pg-enum` — **ZERO — flagged**; proposed opt-in warning or retirement after correcting inaccurate transaction wording.
- [ ] `sql:prefer-jsonb` — **ZERO — flagged**; proposed opt-in warning because plain JSON can intentionally preserve order, whitespace, and duplicate keys.
- [ ] `sql:prefer-text-over-varchar` — hit; inspect findings and record precision.
- [ ] `sql:prefer-uuidv7-default` — hit; inspect findings and record precision.
- [ ] `sql:require-fk-index` — hit; inspect findings and record precision.
- [ ] `sql:require-lock-timeout` — hit; inspect findings and record precision.

## iac

- [ ] `iac:no-comment-cruft` — hit; inspect findings and record precision.
- [ ] `iac:no-dead-environment-input` — hit; inspect findings and record precision.
- [ ] `iac:no-environment-conditional` — hit; inspect findings and record precision.
- [ ] `iac:no-terraform-test-file` — **ZERO — flagged**; proposed removal because Terraform's semantic `.tftest.hcl` runner is an expert testing mechanism.
- [ ] `iac:require-deletion-protection` — hit; inspect findings and record precision.
- [ ] `iac:require-prevent-destroy-on-irreplaceable` — hit; inspect findings and record precision.

## text

- [ ] `text:commented-out-config` — hit; inspect findings and record precision.
- [ ] `text:config-comment-wall` — **ZERO — flagged**; proposed removal because the error-level scanability heuristic lacks live defect evidence.
- [ ] `text:ephemeral-execution-artifact` — hit; inspect findings and record precision.
- [ ] `text:iac-source-coupled-test` — **ZERO — flagged**; proposed warning-only expansion to conventional check/verify shell-test names, pending a live true positive.
- [ ] `text:unpinned-github-action` — hit; inspect findings and record precision.

## Candidate evaluated during remediation

- [x] `python:get-delegates-to-get-many` — corpus A: 3 historical findings; corpus B: 0. The final implementation was then run in isolated batches over six immutable current snapshots containing 2,566 tracked Python files and 19,381,932 bytes: one corpus produced 3 findings and the other five produced 0. Every finding was inspected and classified as an actionable duplicated singleton/bulk implementation path, with 0 known false positives. Five warm rule-only samples over 556 Python files (3,778,801 bytes) had a 44 ms median, and the repository performance budget passed. Shipped as a warning with no autofix.

## Rules added on main during the audit

- [ ] `eslint:test-phase-label-comment` — corpus A: 0; corpus B: 0; applicable files parsed without errors; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `iac:no-restated-comment` — corpus A: 3; corpus B: 21; inspect findings and record precision.
- [ ] `python:no-unnecessary-docstring` — corpus A: 464; corpus B: 2,556; classify a deterministic sample before promotion.
- [ ] `python:no-vague-suppression-description` — corpus A: 0; corpus B: 0; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `sql:no-comment-cruft` — corpus A: 3; corpus B: 0; inspect all findings and record precision.
- [ ] `text:exact-config-comment-restatement` — corpus A: 0; corpus B: 0; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
- [ ] `text:hidden-markdown-heading` — corpus A: 0; corpus B: 0; proposed keep as a narrow categorical or profile-gated guard; broaden only after a labeled defect.
