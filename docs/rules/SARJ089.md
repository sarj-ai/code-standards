# SARJ089 `test-phase-label-comment` — evidence

Behaviour is specified by
[the tests](../../packages/python/tests/rules/test_phase_label_comment.py); every
guard below has a named case, and the mutation log at the end names the case
that kills each one. This file holds what a test cannot carry: the census, the
measurements, and the concentration warning.

```python
def test_customer_delete_by_external_reference(staff_api_client, customer_user):
    # given
    user = customer_user
    ext_ref = "test-ext-ref"

    # when
    response = staff_api_client.post_graphql(CUSTOMER_DELETE_MUTATION, variables)

    # then
    content = get_graphql_content(response)
```

Three lines of comment carrying no information whatever. The blank line above
each already marks the phase; the assertions already mark the assertion.

## The predicate

An own-line comment **in a test file** whose entire body is a phase word:
`arrange`, `act`, `assert` / `asserts` / `assertion` / `assertions`, `given`,
`when`, `then`, `exercise`, `execute`, `verify` / `verification`, `cleanup`,
`prepare`, `sanity` / `sanity check`, or a slashed pair of them
(`arrange / act`, `act/assert`, `when/then`). Trailing punctuation is allowed;
trailing *words* are not.

Guards, each with a test:

- **Trailing text disqualifies.** `# then the retry loop would spin forever` is
  a why that happens to start with a phase word. The end anchor is the whole
  difference, and `test_a_phase_word_carrying_a_sentence_is_left_alone` is what
  keeps it: the shape appears in the census.
- **`setup` and `teardown` belong to SARJ016.** They are already in
  `no-comment-cruft`'s section-label vocabulary. One deletion must not read as
  two findings. Measured: **0** of 27,714 findings overlap a SARJ016 finding.
- **Own line only.** `result = act()  # act` is annotating a value; SARJ051 owns
  the trailing-comment population.
- **Bracket depth exempt.** At depth > 0 the word is labelling an element of a
  literal (a `# given` heading a parametrize tuple), not a phase.
- **Test files only**, and **generated files exempt**.

## Measured

**27,714 findings** across the same 19-repository, 45,900-file census described
in [SARJ088.md](SARJ088.md).

Two seeded random samples read against source:

| sample | n | true | false | rate |
| --- | ---: | ---: | ---: | ---: |
| all repos, seed 8901 | 18 | 18 | 0 | 0% |
| largest contributor excluded, seed 8902 | 18 | 18 | 0 | 0% |

**0 of 36.** The predicate is a whole-body match against a closed vocabulary, so
there is very little for it to be wrong about; the sampling is here to prove the
vocabulary does not overreach, not to discover a rate.

### Read the distribution before reading the total

One repository supplies **26,185 of 27,714 (94.5%)** — its test suite is written
Given/When/Then throughout. The remaining 1,529 are spread over ten repositories:
litellm 607, airflow 510, superset 254, prefect 69, mlflow 26, langchain 23,
dagster 19, celery 16, django 4, zulip 1.

**Zero findings on any first-party repo, and zero on this repo's own source.**
This rule is a fence, not a cleanup: it stops the convention arriving, and the
size of the number it produces on an unfamiliar corpus is a property of that
corpus's house style rather than a measure of the class's importance. A consumer
adopting it against an existing Given/When/Then suite wants the baseline
ratchet, not a 26,000-line diff.

### Leakage into non-test files

A bare phase word outside a test file is almost nonexistent: **7** in the whole
census, against 27,642 inside test files. The `is_test_path` gate costs
essentially nothing and keeps the rule's advice ("a test whose phases need
signposting wants a named helper") from being given to code that is not a test.

## Mutation log

| mutation | killed by |
| --- | --- |
| drop the `is_test_path` gate | `test_a_non_test_file_is_left_alone` |
| drop the generated-file gate | `test_generated_files_are_exempt` |
| drop the nested-comment gate | `test_a_label_inside_a_bracketed_expression_is_left_alone` |
| drop the end anchor | `test_a_phase_word_carrying_a_sentence_is_left_alone` |
| add `setup`/`teardown` to the vocabulary | `test_setup_and_teardown_belong_to_sarj016` |

Suppress an intentional case with `# sarj-noqa: SARJ089 — <reason>`.
