# SARJ083 `no-implicit-attribute-access` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_implicit_attribute_access.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

The anti-pattern:
    price = foo.get("price")
    user_id = event["user_id"]

Accessing dictionaries with hardcoded string literals implies the object has a known schema.
This should be parsed declaratively with Pydantic instead of plucked manually.

Define a Pydantic model and parse the payload at the boundary instead:
    class Payload(BaseModel):
        price: int
        user_id: str

    data = Payload.model_validate(foo)
    price = data.price

## What the rule is about

The defect is **plucking a field out of a payload nobody parsed**. Every guard
below is a shape where a string subscript is present but that defect is not:
either no mapping is involved at all, or the mapping's schema is already
declared and statically checked, in which case the rule's own advice has already
been taken.

## 2026-07 false-positive audit

The first round of guards (write targets, type subscripts, route/URL `.get`) was
measured on two first-party repos and took the rule from 1,756 findings to 641.
That fix HELD: the same two repos produce 637 today. The rule's total then grew
to **48,024** purely because the corpus grew from 2 repos to 19 (24,644 deduped
files: 6 first-party repos plus django, celery, airflow, litellm, prefect,
saleor, zulip, fastapi, pydantic, rich, httpx, requests). A seeded random sample
of 50 findings read against source classified 30 true positives, 12 false
positives and 8 arguable — a **24% false-positive rate**, in five mechanically
separable classes, each guarded below with its exact size over all 48,024.
Together the guards take the corpus to **45,202** (-2,822, 5.9%) and the
first-party share from 1,741 to **1,676** (-65, 3.7%).

### Guards added

* **A subscript inside an annotation.** `_TYPE_SUBSCRIPTS` covers the constructs
  whose *own* name gives them away (`Literal["x"]`, `Annotated[T, ...]`), but a
  string forward reference is written with an ordinary generic:
  `Optional["Router"]` parses as `Subscript(Name("Optional"), Constant("Router"))`
  and was reported as a dictionary lookup of the key `Router`
  (`litellm/litellm/proxy/vector_store_files_endpoints/endpoints.py:328`,
  `litellm/litellm/proxy/guardrails/guardrail_hooks/grayswan/grayswan.py:536`).
  The guard is positional rather than name-based: any node lexically inside an
  annotation subtree (`arg.annotation`, `FunctionDef.returns`,
  `AnnAssign.annotation`) is skipped. **Recall cost is exactly zero** — an
  annotation is not evaluated as a mapping lookup, so no true positive can live
  there. 1,666 of 48,024 (3.5%).
* **A receiver annotated with a TypedDict declared in the same file.** `d["key"]`
  on a TypedDict IS the declarative, statically-checked access the rule asks for:
  mypy and pyright verify the key against the declaration and reject a typo. The
  sharpest instance in the corpus is `pydantic/docs/plugins/algolia.py:166`,
  where `record['title']` reads a value produced by
  `TypeAdapter(list[AlgoliaRecord]).validate_json(...)` — the rule tells
  Pydantic's own docs tooling to "use a declarative Pydantic model" instead of
  the declarative Pydantic model it is already using. Recall cost is near zero: a
  TypedDict receiver is already schema-bound, which is the whole of the remedy.
  Reaches 499 findings; see the structural residual below.
* **The collection-building mutation idiom.** Writing to a mapping is already
  exempt through the `Store`/`Del` context test, on the grounds that building a
  dict up key by key is ordinary construction rather than plucking. Two spellings
  of the same construction are `Load` contexts and slipped through:
  `errors["attributes"].append(x)` on a `defaultdict(list)`
  (`saleor/saleor/graphql/page/mutations/page_type_update.py:54`) and the other
  in-place collection methods. The guard is one hop of parent structure: a
  Subscript that is the receiver of `.append` / `.add` / `.extend` / `.update` /
  `.insert` / `.discard` / `.setdefault`. 324 of 48,024 (0.7%). `d["k"] += 1` was
  named in the same diagnosis but needs no guard — CPython gives an `AugAssign`
  target `ctx=Store()`, so the existing write test already covers it.
* **`ConfigParser.get(section, option)`.** `_EXCLUDED_BASES` carries `config` but
  not `conf`, and `conf.get("api", "ssl_cert", fallback="")`
  (`airflow/airflow-core/src/airflow/api_fastapi/auth/managers/simple/routes/login.py:96`)
  is not a mapping lookup at all — it is the two-argument
  `ConfigParser.get(section, option)` of
  `airflow/airflow-core/src/airflow/configuration.py:180`. The guard keys on the
  `fallback=` keyword rather than on the receiver name, which makes it exact:
  `dict.get` has no `fallback` parameter, so no dictionary lookup can be written
  this way. **Recall cost zero.** 178 of 48,024 (0.4%), 0 first-party. The
  receiver-name spelling — exempt everything whose base is `conf` — would be 356,
  but it is a guess about a name rather than a fact about a signature, and `conf`
  is a perfectly ordinary variable name for a payload; the exact form is worth
  the 178 it does not reach.
* **A module- or class-level constant lookup table.**
  `GIF_RATING_POLICY_OPTIONS["g"]["id"]` (`zulip/zerver/models/realms.py:722`)
  reads a literal table declared 29 lines above it in the same class body. There
  is no payload, no boundary and no schema to parse — the table IS the schema,
  spelled as a literal. The guard requires all three of: a SCREAMING_CASE root
  receiver, bound at a declaration scope (module body or class body) in this same
  file, to a `dict` or `list` *literal*. 118 of 48,024 (0.2%), 0 first-party. All
  three conditions are load-bearing: the SCREAMING_CASE test alone is 253, and
  the 135 it adds are constants imported from elsewhere or computed by a call —
  including `airflow/providers/fab/.../cli_commands/permissions_command.py:130`,
  whose `RESOURCE_DETAILS_MAP` is imported, so the same-file requirement is what
  this guard trades away to stay a fact rather than a naming convention.
* **Language reflection namespaces.** `f.f_globals["__name__"]`
  (`pydantic/pydantic/main.py:1872`) and `get_type_hints(...).get("return", Any)`
  (`airflow/task-sdk/src/airflow/sdk/bases/decorator.py:489`) read namespaces
  CPython defines; no Pydantic model replaces `__name__`. The guard is a dunder
  key, or a receiver named `f_globals` / `f_locals` / `__annotations__`, or a
  `globals()` / `locals()` / `get_type_hints(...)` call. **Recall cost zero.** 54
  dunder keys plus 16 reflection receivers, of 48,024 (0.1%), 0 first-party.

### A structural residual, recorded rather than guessed at

The TypedDict class is **3,018 of 48,024 (6.3%)**, the largest of the five, and
the guard reaches only its same-file half. That is a structural limit, not a
tuning choice. The class is dominated by TypedDicts declared in *another module*
— `context["ti"]`, where `Context` is `class Context(TypedDict, total=False)` in
`airflow/task-sdk/src/airflow/sdk/definitions/context.py:46` and the reader is
`airflow/providers/google/.../vertex_ai/endpoint_service.py:295`, or
`litellm/litellm/integrations/argilla.py:157`, whose `ArgillaItem` is imported. A
rule that sees one file and one AST cannot know that an imported name is a
TypedDict; resolving it would mean parsing the import graph on every file. The
same-file half is **499 of the 3,018** (57 of them first-party — the only guard
here with a material first-party share, and the reason the first-party total
moves at all). **The other 2,519 are a known residual** and are deliberately not
guessed at by name.

### A house-style call this rule does NOT make

zulip wraps every webhook payload in a `WildValue` and reads it as
`payload["issue"]["iid"].tame(check_int)`. That is declarative validation through
a non-Pydantic validator: `__getitem__` returns another `WildValue` rather than a
raw value, and `.tame()` raises on a schema mismatch, so the unchecked-pluck
defect the rule names is absent. It is **2,063 of 48,024 (4.3%)** and it was
counted ARGUABLE, not false — whether a house accepts a validator other than
Pydantic is a decision for that house, not for this rule. It is deliberately
**left firing**; suppress per-file if the answer is yes.

### No generated/vendored exemption gap

Only 1,030 of 48,024 (2.1%) sit in migration-ish paths, and those are
overwhelmingly airflow database migrations doing real hand-written payload
plucking. `migrations/` is deliberately NOT excluded.
