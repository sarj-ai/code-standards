# SARJ086 `docstring-args-restate-signature` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_docstring_args_restate_signature.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

    def delete(self, key: str) -> None:
        """Drop the entry, and the tombstone the compactor would have read.

        Args:                                  <- everything below is ceremony
            key: The key of the value to delete
        """

The summary earns its place — "the tombstone the compactor would have read" is
not readable off the signature. The `Args:` block does not: every content word
of every entry is already in the parameter's own name, its annotation, or the
function name. It is a table of contents for a list of one. (That entry is real:
`celery/celery/backends/azureblockblob.py:154`.)

**The fix is to delete the `Args:` section only**, leaving the summary. That is
safe, and it was checked against the shipped strict config rather than assumed:
ruff's D417 (`undocumented-param`) does **not** fire on a Google-style docstring
with no parameter section at all, so removing the block does not trade one
finding for another. It is also the whole reason this rule exists and the
sibling `Returns:` shape does not — deleting a `Returns:` section makes DOC201
fire, so the only compliant remedy there is deleting a docstring whose summary
may be the valuable part.

**Why SARJ050 cannot reach this.** SARJ050 tests every content word of the
docstring against the signature stems. The literal header word "args" is a
content word and no signature contains it, so the mere presence of an `Args:`
block makes a docstring permanently unflaggable by that rule, whatever the block
says. Across the first-party corpus **126** functions carry a parsed `Args:`
block; SARJ050 flags **0** of them.

**Never flagged**

- **One informative entry protects the whole block.** The test is over every
  entry: a block where three entries restate and the fourth carries a default, a
  unit, an example value or a constraint stays whole. Splitting a parameter
  table is worse than leaving it. Relaxing this to "any entry restates" raises
  the first-party count from 12 to 16 and immediately admits entries documenting
  defaults.
- **An entry with no description at all** — the bare `name (type):` stub. Every
  one of the 8 first-party instances came from an OpenAPI client generator whose
  output carries no generated-code marker, so a content-only check cannot see
  it; judging a machine-emitted stub tells the author to edit a file that will
  be regenerated. Dropping them is what takes the raw 20 findings to 12.
- **An empty block, or one no entry parses out of.** Nothing to judge.
- **Prompt / CLI / route decorators.** For an agent tool the `Args:` block is
  part of the description shipped to the model; for click/typer it is the
  argument help text — the same hard exemption SARJ050 makes.
- **The protected class and the value markers**, evaluated over the block, so a
  parameter documented with a unit, a status code, an RFC, a ticket or a causal
  clause keeps its whole table.
- **NumPy-style parameter blocks** (`Parameters` under a `-----` underline).
  `_docstrings` parses Google style only; the first-party corpus holds 2 NumPy
  docstrings in total, which is not enough evidence to tune a second parser.

**What counts as "already in the signature".** The function's own name and its
owning class contribute stems, not just the parameter's. An entry reading
`token: JWT access token to verify` on a `JwtService.verify_access_token(token: str)`
shape is a restatement, because "JWT" is on the class the caller types. That is also the
loosest the test gets: of the 12 first-party findings, exactly one turned on a
word supplied by the function name rather than the parameter, and it was judged
borderline-true rather than false.

**Measured.** 20 raw findings across 2,440 reviewable first-party files, 8 of
them generator output that the empty-description guard removes, leaving **12**.
All 12 were read: **12 true positives, 0 false** (1 borderline, above). The
dominant shape is an ID parameter documented as its own name in title case.

Over 14 OSS repos the predicate finds **864** (langchain 257, mlflow 256,
dagster 137, litellm 107, prefect 87, celery 8, superset 8, airflow 4, and 0 in
django, fastapi, saleor, sentry-python, warehouse, zulip). 20 were sampled
across celery, superset and airflow and read: **20 true positives, 0 false**,
including `celery/celery/app/task.py:1030` ("sig (Signature): signature to
replace with."), `celery/celery/backends/cosmosdbsql.py:206`,
`superset/superset/utils/jinja_template_validator.py:38` ("template_str: The
template string to validate") and
`airflow/providers/openlineage/src/airflow/providers/openlineage/utils/spark.py:131`
("properties: Spark properties.").

Suppress an intentional case with `# sarj-noqa: SARJ086 — <reason>`.
