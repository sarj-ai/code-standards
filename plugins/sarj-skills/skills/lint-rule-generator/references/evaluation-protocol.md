# Rule evaluation

Use the packaged corpus verifier with immutable local sources; never refresh
pins silently. Choose representative affected stacks, not a repository quota.

Prove detection with labeled bad cases and rejection with near misses. Inspect
live hits, or use a reproducible unbiased sample and disclose its selection.
Report TP/FP/FN/TN, duplicate locations, exclusions and blind spots. Case counts
and zero findings do not establish correctness; distinct fixtures need distinct
contracts, not merely different titles.

Exercise nearby-rule precedence, exact suppressions, severity exits and malformed
input where affected. Fixes must preserve semantics and converge with formatters.
Use `run_isolated_corpora` for process isolation and bounded batching.

Compare candidate and baseline cold/warm runs on the same inputs and environment;
report repeated-run median, input size, overhead and available peak memory.
Investigate unexplained regressions before recommending shipment.

Return reject, revise, ship-warning or promote-error with exact commands and
limitations. Zero known inspected false positives is required for error advice;
advice does not bypass warning-release policy. Public reports use redacted
private labels and aggregates, without source, paths or identifying hashes.
