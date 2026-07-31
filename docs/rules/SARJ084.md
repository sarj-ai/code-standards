# SARJ084 `duplicated-override-docstring` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_duplicated_override_docstring.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

    class RecordManager(ABC):
        def exists(self, keys: Sequence[str]) -> list[bool]:
            """Check if the provided keys exist in the database."""

    class SQLRecordManager(RecordManager):
        def exists(self, keys: Sequence[str]) -> list[bool]:
            """Check if the provided keys exist in the database."""   # ← byte-identical
            ...

(That pair is real: `langchain/libs/core/langchain_core/indexing/base.py:331`.)

The copy carries **provably zero** information: it is the same bytes as the text
one class up in the same file. Not a summary, not an implementation note, not a
narrowing of the contract — a paste. And Python already serves the base's text
where the copy is missing: `inspect.getdoc`, `help()`, Sphinx autodoc and every
editor hover walk the MRO, so deleting the override's docstring changes nothing
a reader sees. What it changes is the number of places that sentence has to be
edited when the contract moves — today two, and only one of them next to the
code that implements it.

That drift is the cost. A copied docstring is the one kind that can be wrong
while looking maintained.

**The fix is to delete the override's docstring**, not to reword it. Nothing in
this repo's strict ruff config asks for it back: D102 (`undocumented-public-method`)
is off, and DOC201/DOC402/DOC501 fire only on a docstring that exists.

**Never flagged**

- **A base this file does not define.** Resolution is by plain `ast.Name`
  against classes in the same module, and nothing else. A per-file linter cannot
  follow `from .protocols import Store`, and guessing by name would make every
  same-named class in a repo a candidate parent. This guard costs the most
  recall and is not negotiable.
- **A dotted base.** Matching on the last dotted part alone made a class its own
  parent: a module that does `class Stream(upstream.Stream)` — subclassing an
  import while shadowing its name locally — had its own docstring reported as a
  copy of itself. One finding, one false positive, and requiring the base to be
  an undotted `Name` removes the whole class of error.
- **A stub whose body IS the docstring.** Deleting it leaves an empty suite, so
  the advice would not compile — the same carve-out SARJ050 makes.
- **`@overload` declarations**, whose docstrings belong to the type checker's
  view of the signature rather than to the implementation.
- **A docstring the base does not have.** An override that documents something
  new is the point of writing one.
- **Generated code**, which mirrors whatever the generator emits — and this is
  the shape a generator produces most: one OpenAPI client in the corpus holds 11
  base/subclass method pairs with identical text. Taken by **path as well as
  header** — see the audit note below.

**Measured.** **49 findings across 2,440 reviewable first-party files.** Every
one was read: **49 true positives, 0 false.** All 49 sit in the same layout — a
`Protocol` or ABC declaring the contract and its single in-file implementation
pasting it back. There is no judgement call available, because the test is byte
equality; the only way to be wrong is to resolve the wrong parent, which is what
the two resolution guards above exist to prevent.

Over 14 OSS repos the same predicate finds **137**: langchain 41, airflow 20,
django 19, mlflow 19, prefect 14, dagster 13, saleor 4, superset 2, litellm 2,
sentry-python 2, zulip 1, celery/fastapi/warehouse 0. 18 were sampled and read —
**18 true positives, 0 false** — including
`langchain/libs/langchain/langchain_classic/agents/agent.py:416` and `:692`,
`django/django/db/migrations/questioner.py:173`,
`dagster/python_modules/dagster/dagster/_core/execution/context/hook.py:319`,
`mlflow/mlflow/bedrock/stream.py:140` and
`prefect/src/prefect/server/database/orm_models.py:1624`. The rate is low in
libraries for a structural reason: they put the contract on the ABC and leave
the implementation bare. It is the Protocol-plus-one-implementation layout of
service code that makes the copy tempting.

## 2026-07 false-positive audit — a documented exemption that did nothing

**111 findings before, 111 after — a delta of zero on this corpus, and the fix
still belongs here.** No false-positive class was found. What was found is an
exemption that is documented but not wired to the predicate that implements it.

Being explicit about the number, because it is the honest part: none of the 19
corpora swept in this audit contains a banner-less generated Python tree, so
re-measuring cannot show this fix working. The justification is not a count, it
is that the rule's own stated exemption provably cannot fire for the generator
it names.

The generated-code exemption above called the **header-only** predicate. That
predicate cannot see the generator the exemption was written for:
openapi-python-client emits **no banner**, and `_paths` records **240 such
modules in one checked-in SDK with zero markers in their first five lines**. So
the header-only guard exempted **none of the 11 base/subclass pairs it names**.
The fix is one call site — `is_generated(path, source)`, the union of the path
and header halves.

The divergence was invisible for a structural reason worth recording: the two
sibling rules added alongside this one (SARJ085, SARJ086) already called the
union predicate, this one did not, and **no corpus in the sweep that added the
exemption contained a banner-less generated tree** — so nothing failed. A guard
whose corpus cannot contain its own subject is untested by construction.

Suppress an intentional case with `# sarj-noqa: SARJ084 — <reason>`.
