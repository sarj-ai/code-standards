# SARJ088 `restated-test-docstring` — evidence

Behaviour is specified by
[the tests](../../packages/python/tests/rules/test_restated_test_docstring.py);
every guard below has a named case, and the mutation log at the end names the
case that kills each one. This file holds what a test cannot carry: the census
the rule was chosen from, the measurements, and the false-positive family each
guard exists to stop.

```python
def test_generate_fernet_key_string(self):
    """Test generating a Fernet key."""
    key = generate_fernet_key_string("TEST_KEY")
    assert key == "NBJC_zYX6NWNek9v7tVv64YZz4K5sAgpoC4WGkQYv6I="
```

The name says it. The docstring says it again, in English, and the reader has
to read both to discover they are the same sentence.

## The census this was chosen from

Every comment GROUP — a contiguous run of own-line `#` comments, every trailing
comment, and every module/class/function docstring — was collected with its
adjacent code from **19 repositories, 45,900 Python files**: this repo's
`packages/`, four first-party repos, and fourteen OSS repos (airflow, celery,
dagster, django, fastapi, langchain, litellm, mlflow, prefect, saleor,
sentry-python, superset, warehouse, zulip).

**451,482 groups, 1,293,022 lines.**

| kind | groups | share | lines | share of volume |
| --- | ---: | ---: | ---: | ---: |
| own-line `#` run | 254,140 | 56.3% | 523,412 | 40.5% |
| function docstring | 113,803 | 25.2% | 522,167 | 40.4% |
| trailing `#` | 53,030 | 11.7% | 53,030 | 4.1% |
| class docstring | 21,147 | 4.7% | 133,426 | 10.3% |
| module docstring | 9,362 | 2.1% | 60,987 | 4.7% |

The seven comment/docstring rules already shipped (SARJ016/049/050/051/084/
085/086/087) reported **21,907** findings over that census — **4.9%** of the
groups. The other 95% is what this change was chosen from.

Inside the function-docstring pool, **52,894 sit on a `test_*` function** —
10.1% of every comment group in the census, 127,427 lines — and the existing
rules reached **4.7%** of them. That is the largest precisely-detectable class
the census contains, and it is the one this rule takes.

## The predicate

A `test_*` function (or a `test*` method of a `Test*` class) **in a test file**
whose docstring is summary-only and where **every content word of the docstring**
is already a stem of one of:

- the signature — name, owning class name, parameters, annotations
  (`_docstrings.signature_stems`);
- an **identifier** in the test's own body, plus the keyword singletons
  `None` / `True` / `False`;
- the test-ceremony vocabulary (`test`, `verify`, `ensure`, `assert`, `case`,
  `expect`, `correctly`, `successfully`, …) — words spent on *being* a test
  rather than on which test it is.

Plus the `Test*` class arm: a class-level docstring measured against the class
name and every method signature in it.

Exact-or-stemmed matching, no prefix matching, via the same
`_docstrings.restates` the rest of the family uses.

### Why the body counts, and why only its identifiers

A test's body is the specification. `"""Should raise CardNotFoundError when
store returns None."""` above `with pytest.raises(CardNotFoundError):` is the
same sentence twice, and the signature alone cannot see that — which is why
SARJ050 reaches only 4.7% of this population.

**String literals are excluded on purpose.** A test body is full of English
inside strings, and letting those count as "the code already says it" would
turn an explanatory docstring into a finding the moment its words happened to
appear in a fixture. `test_prose_inside_a_string_literal_does_not_count_as_code`
is that boundary. Inverting it kills
`test_a_docstring_naming_something_new_is_left_alone`.

### The one false-positive family found

`Hook.test_connection` is not a test. Airflow ships one per provider, Superset
one per database engine spec, and each carries `"""Test the Azure Compute
connection."""` — a restatement, but of a production method, where the rule's
advice ("rename the test") is nonsense. **11 of 4,483** findings in the first
sweep were this shape. `is_test_path` removes all of them, and it is the only
guard that removed a true finding from a sample.

## Measured

**5,382 findings** across the census. Distribution: litellm 1,610, superset
1,107, airflow 813, prefect 673, langchain 575, dagster 202, django 130,
sentry-python 87, warehouse 40, saleor 28, celery 28, zulip 12, mlflow 3.
Two of the four first-party repos produce findings (64 and 10); fastapi and two
first-party repos produce none.

Three seeded random samples read against source:

| sample | n | true | false | rate |
| --- | ---: | ---: | ---: | ---: |
| all repos, seed 8801 (pre-guard) | 40 | 39 | 1 | 2.5% |
| all repos, seed 8802 | 40 | 40 | 0 | 0% |
| keyword-singleton arm only, seed 5501 | 18 | 18 | 0 | 0% |

The single false positive was
`airflow/providers/microsoft/azure/.../hooks/compute.py:165`, the
`test_connection` family above; the `is_test_path` guard was built for it and
removes it. On the shipped predicate: **0 of 98**.

**Zero findings on this repo's own source**, across 439 test docstrings. That is
a real zero, not a broken sweep — a must-fire positive control ran on every
pass, and the repo's test docstrings state why a case exists rather than what it
does (`"""Recorded on purpose: the rejected third guard would have silenced
this."""`), which is exactly the shape the restatement test lets through.

## The filler-qualifier amendment shipped alongside

`_docstrings.STOPWORDS` gained `FILLER_QUALIFIERS` — 31 words that narrow
nothing (`specific`, `appropriate`, `entire`, `overall`, `correctly`, …). One of
them was the commonest single reason a pure restatement survived the whole
family: `"""Get a specific account by ID."""` over
`async def get_account(self, account_id: str) -> Account | None` was unflaggable
because `specific` is a content word no signature contains.

`main` was measured and **rejected** from the list: with it in, `"""Main
function."""` over `def main()` has no content words at all, `restates` returns
False for a text with no content words, and the purest ceremony docstring in the
corpus became permanently unflaggable. Two real findings were lost that way
before it was removed; `test_main_is_not_filler` pins it.

Effect on the five rules that predate this change: **+683 findings**
(SARJ050 +588, SARJ087 +43, SARJ086 +28, SARJ085 +24), **-0** — with `main`
excluded, no docstring anywhere in the census becomes content-free under the
amendment. Two seeded samples of the delta, 58 findings read at source, **1
false positive** (`langchain/libs/core/langchain_core/utils/iter.py:207`, where
"If `None`, returns a single batch" states a real behaviour the signature does
not) and 1 arguable (`dagster/.../graph_definition.py:818`, a `@public` property
whose docstring is published documentation) — **~3.4%**.

## Mutation log

Every guard was inverted in turn and the suite re-run. Each mutant dies, and the
case that kills it is named:

| mutation | killed by |
| --- | --- |
| drop the `is_test_path` gate | `test_a_production_method_named_test_connection_is_left_alone` |
| drop the generated-file gate | `test_generated_files_are_exempt` |
| drop the test-name check | `test_a_helper_in_a_test_file_is_left_alone` |
| drop the `Test*` class-method arm | `test_a_method_of_a_test_class_counts_as_a_test` |
| drop the summary-only gate | `test_a_docstring_with_a_google_section_is_left_whole` |
| drop `is_protected` | `test_a_protected_docstring_is_left_alone` |
| drop `VALUE_MARKER_RE` | `test_a_docstring_carrying_a_doctest_is_left_alone` |
| drop the ceremony vocabulary | `test_the_test_ceremony_vocabulary_is_discounted` |
| drop the body stems | `test_flags_a_test_docstring_that_restates_the_name` |
| let string literals widen the body stems | `test_a_docstring_naming_something_new_is_left_alone` |
| drop the keyword singletons | `test_a_word_the_body_already_carries_is_not_novel` |
| drop the `Test*` class-name gate | `test_a_non_test_class_is_left_alone` |
| drop the base-class gate | `test_a_test_class_with_a_base_is_left_alone` |
| drop method stems from the class arm | `test_method_names_count_for_a_test_class` |
| drop the restatement test (class arm) | `test_a_test_class_naming_something_new_is_left_alone` |
| drop the restatement test (function arm) | `test_a_docstring_naming_something_new_is_left_alone` |
| drop any one filler qualifier | `test_the_filler_vocabulary_is_pinned` |
| treat `main` as filler | `test_main_is_not_filler` |

Suppress an intentional case with `# sarj-noqa: SARJ088 — <reason>`.
