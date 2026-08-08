# sarj-python-lint

Custom Python lint rules via stdlib `ast`. Designed for pre-commit. For SQL rules see [`sarj-sql-lint`](../sql/).

```bash
uv tool install sarj-python-lint
```

## Pre-commit

```yaml
- repo: https://github.com/sarj-ai/standards
  rev: python-v0.53.0
  hooks:
    - id: sarj-no-sequential-await
    - id: sarj-inefficient-string-concat-in-loop
    - id: sarj-prefer-str-enum
    - id: sarj-no-fat-try-blocks
    - id: sarj-pydantic-at-boundaries
    - id: sarj-fastapi-openapi-contract            # SARJ094
    - id: sarj-no-hidden-constructor-fallback      # SARJ095 (warning)
    - id: sarj-prefer-self-documenting-constant    # SARJ097 (warning)
    - id: sarj-no-duplicate-dunder-all-entry       # SARJ098 (warning)
    - id: sarj-redundant-module-docstring          # SARJ099 (warning)
    - id: sarj-prefer-class-row
    - id: sarj-prefer-timedelta-for-durations
    - id: sarj-prefer-struct-over-namedtuple
    - id: sarj-no-comment-cruft
    - id: sarj-no-fstring-in-log
    - id: sarj-prefer-non-nullable-collection      # SARJ082
```

### FastAPI OpenAPI contracts (0.44.0)

`SARJ094` complements Ruff's `ANN*` and `FAST001`-`FAST003` checks. It requires
schema-visible operations to declare their summary, description and status;
uses described `Annotated` request markers; rejects schema-erasing response
shapes and response projections; requires explicit content schemas for direct
response objects; and keeps direct errors, custom responses, bodyless statuses,
GET/HEAD inputs and local route ordering honest in OpenAPI. Missing Python
annotations remain owned by Ruff's `ANN*` rules, so enable both policies.

The rule resolves module-level FastAPI imports and locally constructed or
aliased routers without guessing from names. Dynamic decorator mappings,
function-local framework imports, imported router instances and the assembled
`app.openapi()` document remain application-level integration-test concerns.
Existing projects can adopt the default-enabled rule with `--update-baseline`
and then shrink that baseline as endpoint contracts are repaired.

### Hidden constructor settings fallback (0.45.0)

`SARJ095` warns when a keyword-only constructor parameter defaults to `None`
and the constructor silently replaces it with a proven pydantic-settings value.
The effective dependency is invisible at the call site, and `value or
settings.VALUE` also treats an explicit falsey value as omitted. Make the
argument required and resolve the setting at the application composition root;
the annotation may remain nullable when `None` is still a valid explicit value.

The rule resolves same-module settings objects, imports, aliases and re-exports
back to an instance of a `pydantic_settings.BaseSettings` subclass. Literal and
enum defaults, mutable-container initialization, arbitrary factories and
clients, module constants, environment-variable APIs, other parameters and
instance state are deliberately outside v1. No autofix is offered because
changing constructor optionality requires coordinated call-site edits.

Measured over 4,638 tracked Python files in 33 first-party repositories: three
constructor warnings across two repositories, all three actionable. A pinned
15-repository OSS sweep covered 29,203 files and produced zero reports, which is
compatibility evidence rather than a precision claim. An environment-variable
arm was rejected before shipping: it reported a public first-party library and
two intentional LiteLLM integration constructors, all non-actionable.

### Self-documenting constants

`SARJ097` warns when an immediately attached, same-indent comment is the only
place a numeric module or class constant names its unit. It also replaces bare
HTTP integers in commented `*STATUS_CODES` collections with a recommendation to
use `http.HTTPStatus` members. A unit already present in the constant name and
unit-bearing values such as `timedelta(seconds=10)` are accepted.

The first release intentionally avoids judging boolean-policy comments or
trying to delete rationale. It does not autofix: diagnostics ask callers to
encode the proven fact in the name or value while preserving compatibility,
security and vendor-contract reasoning that code cannot express.

### Export and module-docstring noise

`SARJ098` reports an exact duplicate string inside one static package
`__all__` declaration. It deliberately accepts explicit re-export facades:
imports bind the package namespace, while `__all__` defines its supported
export surface. Dynamic or subsequently mutated export lists are skipped, and
there is no autofix because export order and comments can be observable.

`SARJ099` warns only when a one-sentence module docstring re-spells its filename
and immediate package path, such as `element.py` saying “Element class for
element operations.” Lowercase compound filenames are compared conservatively,
so `cacheprovider.py` also matches “Implementation of the cache provider,” but
common inflections such as `log.py` and “Logging utilities” also align. An
extra purpose or constraint keeps the prose. Package initializers, tests,
generated files, structured or multiline docs, and prose carrying an invariant,
consumer, compatibility
constraint, value or external reference are excluded. In particular, the rule
keeps architecture statements about canonical JSON/SARIF diagnostics. It does
not overlap `SARJ085`, which remains the owner of class-name restatements.

### Test-quality rules (0.15.0)

Mined from an AST audit of ~7,500 test functions across two production repos.
Every one is scoped to test files and carries the false-positive guard that made
it shippable; `sarj-python-lint explain` links each rule to its behavioral tests.

```yaml
    - id: sarj-mock-without-spec                   # SARJ040
    - id: sarj-test-loops-over-literal-cases       # SARJ041
    - id: sarj-parametrize-case-needs-id           # SARJ042
    - id: sarj-zero-assertion-test                 # SARJ043
    - id: sarj-fixture-returns-bare-tuple          # SARJ044
    - id: sarj-kwarg-heavy-construction-in-test    # SARJ045
    - id: sarj-xfail-requires-strict               # SARJ046
    - id: sarj-sleep-with-computed-arg-in-test     # SARJ047
```

### Private access, first-party only (0.19.0)

```yaml
    - id: sarj-no-first-party-private-import       # SARJ048
```

Reaching past a module's public surface is a design finding when the module is
ours and an unavoidable fact of life when it is not: a dependency that moves an
API private in a minor release leaves no edit that satisfies the lint.

`SARJ048` fires only when the module declaring the private name resolves to a
package inside your own project. Third-party privates are never flagged.

**It replaces ruff's `PLC2701 import-private-name`,** whose only exemption is
*same top-level package* — a different question, and one that cannot separate
`from app.stores.order_store import _row_to_order` (real; export it) from
`from livekit.agents.inference_runner import _InferenceRunner` (no fix exists).
`sarj-lint-configs` ≥ 0.8.0 ships `PLC2701` in its ignore list for exactly this
reason; if you take that config, turn this hook on, or you lose the check
entirely.

Attribute access (`session._stt`) is out of scope and stays with ruff's
`SLF001`, which cannot make the distinction either — see the rationale in
`ruff.strict.toml`.

### Comment-hygiene rules (0.20.0)

From a 37,918-comment, nine-repo measurement study. All three are
deletion-class, so each was validated against pydantic / trio / attrs as well as
the maintained repos before shipping, with each false-positive guard encoded in
the behavioral tests linked by `sarj-python-lint explain`.

```yaml
    - id: sarj-no-restated-comment                 # SARJ049
    - id: sarj-redundant-docstring                 # SARJ050
    - id: sarj-trailing-value-narration            # SARJ051
```

`redundant-docstring` finds real volume on a codebase that has never had it
(105 in one first-party repo), so the same baseline ratchet applies.

### Docstring-ceremony rules (0.31.0)

SARJ050 tests a *function* docstring against its *own signature*. That leaves
three shapes it cannot reach, each now its own code so a consumer can baseline
them separately:

```yaml
    - id: sarj-duplicated-override-docstring       # SARJ084
    - id: sarj-redundant-class-docstring           # SARJ085
    - id: sarj-docstring-args-restate-signature    # SARJ086
```

`SARJ084` flags an override whose docstring is **byte-identical** to the base
method's, with the base resolved by undotted name inside the same file. There is
no judgement call — the test is byte equality — and `inspect.getdoc`, `help()`,
Sphinx and editor hovers all walk the MRO, so deleting the copy changes nothing
a reader sees. 49 first-party findings, 49 true positives; 137 across 14 OSS
repos, 18 sampled and read, 0 false positives.

`SARJ085` flags a class docstring that only re-spells the class name — the case
SARJ050's walker structurally never inspects. Its largest guard is that anything
whose docstring becomes a **published schema description** (pydantic models,
enums, `TypedDict`s, `@strawberry.type`) is exempt: that string is emitted as
the JSON-Schema `description` and reaches OpenAPI documents and LLM tool
schemas. The exemption costs 28 of 34 first-party findings and is not
negotiable.

`SARJ086` flags an `Args:` block whose every entry only re-spells its own
parameter. It fires where SARJ050 cannot: the header word "args" is a content
word no signature contains, so *any* `Args:` block makes a docstring
permanently unflaggable by SARJ050 — 126 first-party functions carry one and
SARJ050 flags none of them. The remedy deletes the section and keeps the
summary, which was checked against the shipped strict config: ruff's D417 does
not fire on a docstring with no parameter section.

Two more shapes were rejected on volume — property docstrings restating the
property name and reST/epydoc type duplication (`:type x: int`, `:rtype:`) both
measure **0** first-party findings outside generated code.

### The `Returns:` half (0.36.0)

```yaml
    - id: sarj-docstring-returns-restate-signature  # SARJ087
```

`SARJ087` is the `Returns:` sibling of SARJ086, and it was **rejected once**:
deleting a `Returns:` section used to make ruff's DOC201 fire, so the only
compliant remedy was deleting the whole docstring. #164 then removed DOC201 from
`ruff.strict.toml` as a rule that DEMANDS prose, and the premise expired — under
the shipped config the section goes and the summary stays.

756 findings over 33 OSS repos / 35,254 files; two seeded samples of 40 and 20
read against source gave **~2%** false positives, the whole of which was one
family (`Returns: A new X` — whether the value is a copy is the one thing
`-> Self` cannot say) now guarded. Three findings on this repo's own source, all
true, all deleted. The guarded copy-return case is covered by the paired rule tests.

### Test ceremony, and the census it was chosen from (0.38.0)

```yaml
    - id: sarj-restated-test-docstring              # SARJ088
    - id: sarj-test-phase-label-comment             # SARJ089
```

Every comment GROUP in 19 repositories / 45,900 Python files was collected with
its adjacent code and classified: **451,482 groups, 1,293,022 lines**, of which
the seven comment/docstring rules that predate this release reached **4.9%**.
The shipped predicate and its boundaries are recorded in the paired rule tests.

The largest precisely-detectable class left in it is the **test docstring**:
52,894 of them, 10.1% of every comment group, and SARJ050 reached 4.7%. It
reached so few because SARJ050 measures a docstring against its *signature*, and
a test's specification is its BODY. `SARJ088` measures it against the signature,
the identifiers in the test's own body, and the vocabulary a test docstring
spends on being a test. **5,382 findings; 98 read at source, 0 false positives
on the shipped predicate.**

`SARJ089` deletes the bare `# given` / `# when` / `# then` / `# Arrange` /
`# Act` / `# Assert` phase label. 27,714 findings, 36 read, 0 false positives —
but **94.5% come from one OSS suite**, and none from any first-party repo. It is
a fence against the convention arriving, not a cleanup; adopt it behind the
baseline ratchet.

Shipped with them, `_docstrings.STOPWORDS` gained `FILLER_QUALIFIERS`: 31
qualifiers that narrow nothing (`specific`, `appropriate`, `entire`, `overall`).
One of these was the commonest single reason a pure restatement survived the
whole family — `"""Get a specific account by ID."""` over
`get_account(self, account_id: str)`. **+683 findings across SARJ050/085/086/087,
-0; 58 of the delta read, ~3.4% false positives.** `main` was tried and rejected:
as filler it makes `"""Main function."""` content-free, hence unflaggable.

**Three shapes measured on the same census and rejected**, each on a seeded
12-finding read at source:

| shape | findings | true | why it fails |
| --- | ---: | ---: | --- |
| comment restates the `if` / `for` / `with` header below it | 225 | 3/12 | the population is BRANCH LABELS naming a case (`# PIL.Image` over `if isinstance(item, PILImage.Image)`), not narration |
| comment restates a plain assignment (no call on the RHS) | 308 | 2/12 | the population heads a multi-line literal or a 3-statement block — a section label, which is SARJ016's subject |
| multi-line comment run restating the block it heads | 119 | 1-2/12 | banners, Sphinx `#:` attribute docs, and worked calculations dominate |

Those three are why SARJ049 still excludes block openers, plain assignments and
multi-line runs. The exclusions are load-bearing, not unfinished work.

### House conventions moved out of consumer repos (0.21.0)

```yaml
    - id: sarj-no-stdlib-logging                   # SARJ052
    - id: sarj-no-gen-random-uuid-in-sql           # SARJ053
    - id: sarj-no-file-level-escape-hatch-noqa     # SARJ054
```

`SARJ052` bans importing stdlib `logging` in application code, because the
house logger is loguru and two logger hierarchies mean two handler chains: the
records written to the one nobody configured skip the JSON formatter, the
redaction patcher and the error reporter, and — since the stdlib root defaults
to WARNING — usually vanish in production while looking fine locally.

The one legitimate reason to touch stdlib logging in a loguru house is to
*bridge* it, and the bridge cannot be written without naming both loggers, so a
module importing loguru is exempt. Measured across two production repos that
exemption is exact: all four sites that import stdlib logging (three in the
first repo — its package `__init__.py`, a dedicated `configure_logging.py`, and
a service entrypoint `main.py` — plus a `common/logging.py` in the second) are
bridges, all four import loguru, and no other module in either repo imports
stdlib logging at all. Tests, `scripts/`,
`notebooks/`, generated files and `if TYPE_CHECKING:` imports are also exempt.

**This is a house-convention rule, not a universal one.** A *library* should log
through stdlib `logging` precisely so it does not impose a sink on its callers —
trio's three sites are correct for trio. Enable it in applications only.

`SARJ053` flags `gen_random_uuid()` in SQL embedded in a Python string literal:
UUIDv4 keys scatter B-tree inserts across every leaf page, where `uuidv7()`
(Postgres 18) is time-ordered and appends. It is the embedded-SQL third of a
policy the stack already states twice — `ruff.strict.toml` bans `uuid.uuid4`,
and `sarj-sql-lint`'s SARJ109 `prefer-uuidv7-default` covers `.sql` migration
files (41 sites in one first-party repo, 14 in another, all of them a
primary-key `DEFAULT`).
A literal only counts when it is SQL-shaped, so prose naming the function is not
a finding.

`SARJ054` is SARJ038's scoped sibling. SARJ038 bans the unscoped blanket
(`# ruff: noqa`); this bans a *scoped* file-level exemption that names an
escape-hatch code — a code whose remediation `ruff.strict.toml` spells as an
inline `# noqa: CODE — <reason>`, which today is `TID251` alone, ruff's only
banned-API code. Hoisting that to the top of a file turns N reviewed per-site
decisions into one unreviewable one and pre-authorizes every mock added later.
Scoped exemptions for mechanical codes (`E501`, `F401`, `UP035`) are never
flagged — measured across five repos those are the entire population.


### Mock-quality and real-dependency rules (0.24.0)

The second test-quality wave. Where the 0.15.0 family asks "does this test assert
anything?", this one asks "does it exercise anything real?" — it pushes suites off
hand-rolled doubles and onto the real store, the real database and a maintained fake
library. Measured against seven first-party repos and fourteen
OSS corpora; two candidates were dropped outright when the corpus showed they only
duplicated ruff.

```yaml
    - id: sarj-prefer-real-store-in-tests          # SARJ058
    - id: sarj-prefer-library-fake                 # SARJ059
    - id: sarj-tautological-mock-assertion         # SARJ060
    - id: sarj-over-mocked-test                    # SARJ062
    - id: sarj-interaction-only-test               # SARJ063
    - id: sarj-trivially-true-assertion            # SARJ064
    - id: sarj-conditional-assertion-in-test       # SARJ065
    - id: sarj-duplicate-test-body                 # SARJ066
    - id: sarj-unused-mock-setup                   # SARJ067
```

### Expressiveness rules (0.24.0)

```yaml
    - id: sarj-prefer-fstring-over-concat          # SARJ068
    - id: sarj-prefer-or-pattern                   # SARJ070
    - id: sarj-require-port-for-service            # SARJ071
```

`require-port-for-service` treats a local concrete superclass differently from
an abstract/Protocol port and follows local port inheritance transitively.
Class-size enforcement stays with Ruff `PLR0904` (enabled by the strict `ALL`
selection); a second custom size rule would duplicate that owner.

Tuple boundaries are deliberately stricter than Ruff: SARJ026 rejects fixed
multi-field tuple annotations on public production functions, including local
aliases and abstract/NotImplemented contracts, while SARJ044 applies the same
named-result requirement to pytest fixtures. Variadic `tuple[T, ...]` remains a
sequence rather than a positional record. Prefer `typing.NamedTuple`, a frozen
dataclass, or a frozen validation model at schema boundaries.

SARJ008 accepts `TypedDict` as the static-only option for a fixed-key mapping,
alongside a frozen dataclass or a pydantic model when runtime validation is
needed. It does not ask arbitrary `dict[str, T]` mappings to become records:
the function must build and return a string-keyed record literal.

SARJ082 also recognizes a nullable list parameter whose only body read is an
immediate `value or []` normalization. That proof makes `None` and an empty
list observationally equivalent inside the function. Constructors and module
functions receive a warning to require the list or accept an immutable empty
default such as `Sequence[T] = ()`; ordinary methods are excluded because an
inherited framework signature may constrain them even without `@override`.

SARJ006 also warns on transparent module-level `build_` / `make_` constructor
factories that copy at least two three-value inline string `Literal` domains
and forward them unchanged under the same keyword names. Named aliases put each
domain in one model-owned location. Ordinary APIs, methods, decorated
registrations, two-value switches, transformed arguments, generated code, and
test files remain outside the arm. Ordinary inline `Literal` annotations remain
accepted, so existing SARJ006 behavior does not become noisy.

SARJ093 recognizes `str`, `int`, UUID and supported containers as non-nominal ID
carriers, while preserving `NewType` aliases as nominal identities. SARJ006
keeps wire-derived values open, respects `Literal`/enum annotations across
closures and comprehensions, and recognizes explicit and Django-style choice
collections.
### Suppression ratchet (`sarj-ratchet`, 0.21.0)

```yaml
    - id: sarj-suppression-ratchet
```

One tool replacing the per-repo ratchet scripts. It counts every escape hatch in
the tree and enforces three ceilings that may only shrink:

* **per code** — `noqa:TID251` going 40 → 41 is a regression even if the total falls
* **per package** — one package's headroom must not finance another's debt
* **per file** — a global cap so new suppressions cannot pile into one hot spot;
  pre-existing hot spots are grandfathered at their then-current counts

All four dialects are counted under distinct key prefixes, so moving a
suppression between spellings can never hide it: `noqa:CODE`,
`sarj-noqa:CODE`, `pyright:CODE`, `type-ignore:CODE` / bare `type-ignore`, plus
the file-level `file-noqa:CODE` / `file-noqa:<blanket>` and `file-pyright:RULE`.

```bash
sarj-ratchet --update python/          # seed (or lock in a drop)
sarj-ratchet python/                   # gate
sarj-ratchet --update --allow-increase python/   # a reviewed ceiling raise
```

`--update` **refuses** to raise a ceiling unless `--allow-increase` says the
raise was reviewed, and it drops a per-file grandfather clause as soon as the
file falls back under the global cap, so an allowance cannot outlive its debt.

### Two conventions that stayed pygrep

`sarj-fakes-in-shared-location` and `sarj-no-raw-connection-in-tests` ship as
pygrep hooks, not SARJ rules, and both need a `files:`/`exclude:` from the
consumer. An AST port of each was built and measured, and the boundary each
encodes turned out to be repo-specific rather than shared: "shared fake" flagged
9/9 single-use test doubles in one first-party repo that are idiomatic where
they sit, and "raw connection in a test" flagged 46 sites in another of which every one is
already an intentional exemption (store tests asserting DB state, pool-lifecycle
tests, retention tests where physical deletion is the subject). SARJ036
`no-raw-sql-in-tests` remains the corpus-validated shared rule for raw SQL in
tests.

Adopting these against an existing suite is easier through the baseline ratchet
than as a big-bang fix — snapshot the current counts, then let them only shrink:

```bash
sarj-python-lint check --rule mock-without-spec --update-baseline test-quality-baseline.json python/
sarj-python-lint check --rule mock-without-spec --baseline test-quality-baseline.json python/
```

### Multi-tenant scoping (0.24.0)

```yaml
    - id: sarj-no-optional-tenant-predicate        # SARJ056
```

`SARJ056` fires when every WHERE-fragment mentioning a tenant column
(`organization_id` and friends) sits inside a conditional, so the predicate
disappears — and the query still runs — whenever the filter is empty:

```python
where_conditions = []
if args.organization_ids:  # ← optional
    where_conditions.append(SQL("organization_id = ANY(%s::uuid[])"))
...
where_clause = SQL(" AND ").join(where_conditions) if where_conditions else SQL("1=1")
```

The safe idiom seeds the list, so scoping always applies and the rule stays
quiet:

```python
conditions: list[Composable] = [SQL("organization_id = %s")]
```

A function with **no** tenant predicate at all never fires — an intentionally
cross-tenant admin query is out of scope; only *attempted-but-optional* scoping
is a finding. Where a caller genuinely wants the all-tenant query, that
intent belongs in an explicit method (or an inline `sarj-noqa`) rather than in
an omitted filter.

Measured before shipping: **0 findings across 26,345 files** of pydantic, trio,
attrs, Airflow and Home Assistant — single-tenant codebases have no tenant
column, so the rule is silent by construction — and 0 across four other
first-party repos. In the fifth it finds 10 sites, all genuine fail-open
compositions, two of which were reachable cross-tenant reads at the time of
writing (two paginated list endpoints, both of which composed `WHERE 1=1` for a
user whose `organization_id` was NULL).

### Assertions that can never fail (0.23.0)

```yaml
    - id: sarj-no-tautological-expect              # SARJ057
```

`SARJ057` fires when an assertion's operands are all literals, so its outcome is
fixed before the code runs. `SARJ043` already catches the test with *no*
assertion; this is the test whose assertion is decorative.

The placeholder spelling (`assert True`) is the obvious half. The expensive half
is the assertion whose real condition slid out of the condition slot, because it
was a working assertion when it was typed:

```python
assert {  # ← braces, not parentheses
    "referencing a non existing `via_device` " in caplog.text
}  # one-element SET, always truthy

assert [f"No logs found on hdfs for ti={ti}"]  # the `== messages` was lost
assert True, cover_result_json[0]["success"][...]  # slid into the MESSAGE slot
```

**The narrowness is the rule.** The obvious generalisation — "flag a comparison
of a thing with itself" — measures ~95% false positives: `assert i == i`,
`assert x is x`, `expect(hash([o])).toEqual(hash([o]))` are reflexivity,
determinism and memoization tests, and for a type with custom `__eq__`/`__hash__`
they can genuinely fail. So an identifier, attribute or call operand is never
enough; both sides must be literals, and textually identical ones. `assert True`
as the sole statement of an `except` handler is exempt — it asserts *which branch
ran* — as is anything inside a pytest-benchmark test.

Measured before shipping: **4 findings across 28,608 files** — 26,346 of
pydantic, trio, attrs, Airflow and Home Assistant plus 2,262 first-party files
across five first-party repos. All 4 are true positives
(Home Assistant `tests/helpers/test_device_registry.py:3711` and `:3777`,
`tests/components/emulated_hue/test_hue_api.py:1078`, Airflow
`providers/apache/hdfs/.../log/test_hdfs_task_handler.py:170`); 0 false
positives. The two `except ...: assert True` markers that a carve-out-free
version does flag — `pydantic-core/tests/benchmarks/test_micro_benchmarks.py:716`
and `core/tests/components/mqtt/test_client.py:1353` — were verified silent.

The TypeScript half of the same rule ships as `@sarj/no-tautological-expect` in
`@sarj/eslint-plugin` ≥ 2.14.0; until now there was no TS counterpart at all,
which is how `expect(true).toBe(true); // placeholder` survived in a suite named
for the behaviour it was supposed to check.

## CLI

```bash
sarj-python-lint check --rule no-sequential-await path/to/file.py
sarj-python-lint list-rules
```

Diagnostic format is `path:line:col: CODE message` — Ruff-compatible.

## Suppression

Inline `# sarj-noqa: SARJ00X — <reason>` on the offending line.

Each rule's source under `src/sarj_python_lint/rules/` carries its own `description` and diagnostic message.
