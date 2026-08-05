# Reproducible evaluation protocol

## Corpus manifest

Use an already-local public manifest and optional owner-readable private
overlay. Every source declares non-empty include patterns and a SHA-256 content
digest. Git sources also declare a full lowercase 40-character commit. Verify
both with `sarj_lint_configs.libs.corpus.verify`; never silently refresh pins.

The corpus should include this repository, representative consumer repositories,
and mature public projects for the affected language. Diversity matters more
than raw repository count: include tests, generated-code conventions,
frameworks, monorepos, configuration, and documentation where applicable.

## Labels and counts

Create `EvaluationCase` fixtures with stable IDs and expected diagnostics. Run
`evaluate` and report:

- labeled true positives, true negatives, false positives, and false negatives;
- duplicate diagnostics at one path/line/column;
- per-corpus files and bytes scanned;
- inspected live matches and classification;
- excluded paths and the reason for each exclusion;
- known blind spots that are deliberately safer than guessing.

Zero findings is not evidence of correctness. Seed the corpus with known bad
examples and prove that the rule fires. Likewise, a high hit count is not
evidence of value until matches are inspected.

## Interaction and developer experience

Run the candidate alongside every nearby rule. Assert precedence when a
specific diagnostic supersedes a generic one. Test exact-code suppression,
warning/error exit behavior, malformed input, and repeated invocations. An
autofix must preserve parsing and behavior, converge after one pass, and not
oscillate with a formatter or another fix.

## Performance

Measure the candidate alone and the normal combined runner on the same warm and
cold corpus. Record median of repeated runs, input size, environment, and peak
memory if available. Investigate repeated parsing, subprocess startup, broad
filesystem walks, and non-content-addressed caches. Cache only deterministic
immutable results and bound in-process caches.

## Final decision

Return one of: reject, revise, ship-warning, or promote-error. Include the exact
commands needed to reproduce the decision. Private sources appear only as
`<private-corpus>` and aggregate counts; no snippets or identities leave the
private report boundary.
