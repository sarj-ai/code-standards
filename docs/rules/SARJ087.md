# SARJ087 `docstring-returns-restate-signature` — evidence

Behaviour is specified by
[the tests](../../packages/python/tests/rules/test_docstring_returns_restate_signature.py);
every guard below has a named case, and the mutation log at the end names the
case that kills each one. This file holds what a test cannot carry: the
measurements, and the false-positive family each guard exists to stop.

```python
def get_line_length(cls, line: List["Segment"]) -> int:
    """Get the length of list of segments.

    Args:
        line (List[Segment]): A line encoded as a list of Segments.

    Returns:
        int: The length of the line.
    """
```

The summary and the `Args:` block are someone's work. The `Returns:` block is
four words the name and `-> int` already spell, and it exists because DOC201
asked for it.

## Why this is not SARJ050 or SARJ086

SARJ050 `redundant-docstring` tests the WHOLE docstring against the signature,
so one substantive sentence anywhere makes the ceremony beneath it permanently
unflaggable. SARJ086 `docstring-args-restate-signature` split the `Args:` half
out for exactly that reason. This is the other half.

**The sibling `Returns:` shape was measured and rejected once** — see
`packages/python/README.md` at 0.31.0: "deleting a `Returns:` section makes
DOC201 fire, so the only compliant remedy is deleting a docstring whose summary
may be the valuable part." That premise expired. #164 removed DOC201, DOC402 and
DOC501 from `ruff.strict.toml` under the heading *rules that DEMAND prose*, so
under the shipped config deleting the section IS the compliant remedy and the
summary stays. The rule completes the family rather than conflicting with it.

## The predicate

A function whose docstring has a Google-style `Returns:` / `Return:` /
`Yields:` / `Yield:` section where **every content word of that section** is
already a stem of the signature — the function name, the owning class name,
every parameter name and every annotation, return included. Exact-or-stemmed
matching, no prefix matching, via the same `_docstrings.restates` the rest of
the family uses.

Guards, each with a test:

- **The whole-docstring case belongs to SARJ050.** When the summary restates the
  signature too, `redundant-docstring` already reports the docstring; one
  deletion must not read as two findings.
- **Protected class exempt.** `_comments.is_protected` and
  `_docstrings.VALUE_MARKER_RE` — a ticket, URL, unit, causal connective or
  security term in the block means it is not ceremony.
- **Identity semantics exempt.** See below.
- **Schema-producing decorators exempt.** A `@router.get` handler's docstring is
  the description in the generated OpenAPI document, so deleting a section of it
  changes an artefact rather than tidying a file.
- **Generated files exempt.**

### The identity guard is the one false-positive family found

`new`, `same`, `copy` and `itself` are STOPWORDS for the restatement tokenizer,
so a block whose only real content is *whether the value handed back is a fresh
object* reads as pure ceremony:

```python
def configure(self, key_storage: Storage, ...) -> Self:
    """...

    Returns:
        A new cache policy with the given key storage, lock manager, ...
    """
```

`-> Self` cannot say "a copy". `_IDENTITY_RE` exempts a block naming that
property. MEASURED: removes **40 of 796 (5.0%)**; ten of the removal set read at
source are the same shape every time — `prefect/context.py:252` "A new model
instance", `rich/style.py:650` "New style object",
`pydantic/_internal/_discriminated_union.py:141` "The new core schema".

## Measured

Corpus: **33 OSS Python repos, 35,254 files** (aiohttp, airflow, ansible, attrs,
black, bokeh, celery, click, django, django-rest-framework, dvc, fastapi, flask,
httpx, jinja, litellm, luigi, mkdocs, mypy, poetry, prefect, pydantic, pytest,
requests, rich, saleor, scrapy, sqlalchemy, starlette, streamlit, tornado,
typer, zulip).

**756 findings.** Two seeded random samples read against source:

| sample | n | true | false | arguable | rate |
| --- | --- | --- | --- | --- | --- |
| all repos, seed 11 | 40 | 38 | 1 | 1 | 2.5% |
| prefect excluded, seed 42 | 20 | 20 | 0 | 0 | 0% |

The single false positive was `prefect/cache_policies.py:80`, the "A new cache
policy" shape above; the identity guard was built for it and removes it. Read
the residual as **~2%**, and read it as corpus-dependent the way SARJ049's
evidence file says: prefect supplies 48% of the findings, and 200 of those are
`prefect-github`'s GraphQL wrappers, every one carrying the same
`Returns:` / `A dict of the returned fields.` under `-> Dict[str, Any]`.

Distribution: prefect 380, bokeh 145, litellm 122, pydantic 99, rich 38,
airflow 5, saleor 2, attrs 2, dvc / celery / aiohttp 1 each. Twenty-two of the
thirty-three repos produce none.

**Three findings on this repo's own source**, all true, all deleted in the same
change: `packages/iac/src/sarj_iac_lint/rule_base.py:18` and
`packages/sql/src/sarj_sql_lint/rule_base.py:188`
(`Returns:` / `True when the line is suppressed for 'code'.` under
`is_suppressed(...) -> bool`), and
`packages/lint-configs/src/sarj_lint_configs/scaffold.py:70`
(`Returns:` / `The detected ecosystems.` under `detect(root) -> Ecosystems`).

## Mutation log

Every guard was inverted in turn and the suite re-run. Each mutant dies, and the
case that kills it is named:

| mutation | killed by |
| --- | --- |
| drop `_IDENTITY_RE` | `test_identity_semantics_are_not_a_restatement` |
| drop `is_protected` | `test_a_protected_block_is_left_alone` |
| drop `VALUE_MARKER_RE` | `test_a_block_carrying_a_unit_is_left_alone` |
| drop the decorator gate | `test_a_schema_producing_decorator_exempts_the_docstring` |
| drop the SARJ050 hand-off | `test_a_whole_docstring_restatement_belongs_to_sarj050` |
| drop the generated-file gate | `test_generated_files_are_exempt` |
| `_RETURN_SECTIONS` narrowed to `("Returns",)` | `test_every_return_section_spelling_is_read` |
| owning class name dropped from the stems | `test_the_owning_class_name_counts_as_signature` |
| drop the restatement test itself | `test_a_block_naming_something_the_signature_does_not_is_left_alone` |

A tenth candidate guard — a fast path for a whitespace-only `Returns:` block —
was **removed** rather than kept: the mutant survived, because
`_docstrings.restates` already reports False for a text with no content words. A
guard that cannot change behaviour is noise.

Suppress an intentional case with `# sarj-noqa: SARJ087 — <reason>`.
