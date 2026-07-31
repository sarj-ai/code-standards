# SARJ083 `no-implicit-attribute-access` — evidence (RETIRED)

> **This rule was deleted in `sarj-python-lint` 0.37.0.** The module, its tests,
> its registry entry and the `sarj-no-implicit-attribute-access` pre-commit hook
> are gone. `SARJ083` stays burned: `packages/python/tests/code_ledger.json` is
> append-only and still records it as `no-implicit-attribute-access`, so
> `test_no_rule_reuses_a_retired_code` derives the retirement without anyone
> having to remember it, and `test_ledger_covers_every_deleted_rule_module`
> recovers the deletion from git history if the line is ever removed. The removal
> is also recorded in `rule-ledger.json`, so `sarj-lint-configs doctor` names it
> for any repo whose pre-commit config, `sarj-noqa` comments or
> `.sarj-python-baseline.json` still reference it.
>
> **This file is deliberately retained**, archived under `docs/rules/retired/`
> rather than deleted with the rule. It is the first withdrawal to use the
> retention convention #200 built after #183 deleted `docs/rules/SARJ061.md`
> along with SARJ061 — taking with it the identity of the three findings that
> commit called true positives, which is not recoverable from the tree.
> `scripts/check-file-conventions.sh` enforces it in both directions: a doc
> naming no live rule must be under `retired/` rather than absent, and a diff
> gate against the merge base fails if an evidence file leaves `docs/rules/`
> without arriving there.
>
> **What decided it:** the 2026-07-31 re-audit below. A seeded sample of 30
> findings read at source, *after* three new guards shipped: **10 hard false
> positives, 5 weak true positives, 15 arguable**, against a corpus total of
> **46,089 findings over 4,783 files**. The bar this repo applies is that a rule
> must not fire on correct code, and `df["class"]`, argparse `**options`, Django
> `error_messages`, Streamlit `session_state`, SQLAlchemy `_annotations` and
> `.get()` on a dict produced by `.model_dump()` one line above are all correct
> code. Its TypeScript twin `@sarj/no-implicit-attribute-access` was deleted in
> #183 for scoring 0 true positives in 50 reads; this is the same answer at a
> different sample size.
>
> Everything below is the record as it stood at deletion, unedited. The link to
> the tests is dead by design — the tests went with the rule; they are recoverable
> at tag `python-v0.36.0`, `packages/python/tests/rules/test_no_implicit_attribute_access.py`.

Behaviour was specified by the tests (removed with the rule; see
`python-v0.36.0`); every guard below had a named test asserting it. This file
holds what a test cannot carry: the measurements that chose each threshold, and
the false-positive family each guard existed to stop.

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

## 2026-07-31 re-audit — and a recommendation to DELETE this rule

> **Verdict: SARJ083 does not clear the bar this repo applies to its own rules,
> and it should be deleted.** The three guards below are shipped anyway, because
> they are exact and reduce harm while the decision is taken. They do not change
> the verdict.

### The measurement

Swept over **37,358 Python files across 33 OSS repositories** (a corpus disjoint
from the one above, and 1.5x larger):

| | findings | files |
| --- | --- | --- |
| as shipped | 54,326 | 4,783 |
| after the three guards below | 46,089 | — |

Decomposed: the decorator and `meta` guards are worth 235 together (54,326 ->
54,091); the imported-declared-type guard is worth 8,002 (54,091 -> 46,089).

Two seeded random samples of 30 findings each were read against source — one
before the guards, one after. The post-guard sample of 30 classified:

* **10 hard false positives (33%)** — a mapping is not involved, or the
  declarative schema the rule asks for is already there:
  * `bokeh/examples/basic/annotations/whisker.py:17` — `df["class"]` is a
    **pandas column selection**.
  * `sqlalchemy/lib/sqlalchemy/orm/bulk_persistence.py:1966` —
    `statement.table._annotations["parententity"]`, SQLAlchemy's own internal
    annotation namespace.
  * `zulip/zerver/webhooks/gocd/view.py:62` — `material["git-configuration"]
    ["branch"].tame(check_string)`, zulip's `WildValue` declarative validator.
  * `litellm/litellm/proxy/common_request_processing.py:2873` — `d.get("content",
    "")` where `d = chunk.model_dump(...)`. The advice is inverted: a Pydantic
    model was just dumped to produce this dict.
  * `ansible/lib/ansible/modules/file.py:371` and
    `airflow/dev/breeze/.../constraints_version_check.py:397` — dicts built by
    the same function a few lines above.
  * `zulip/zerver/management/commands/create_realm.py:53` — `options["realm_name"]`,
    argparse's `**options`, a framework API.
  * `django/django/contrib/postgres/forms/array.py:215` —
    `self.error_messages["required"]`, Django's documented extension point.
  * `streamlit/e2e_playwright/st_chat_input.py:50` — `st.session_state.get(...)`,
    Streamlit's key-value store.
  * `streamlit/e2e_playwright/websocket_reconnects_test.py:196` — a counter dict
    in a test file that `_is_test_path` does not recognise (`*_test.py` outside a
    `tests/` directory).
* **5 plausible true positives (17%)** — `litellm/litellm/integrations/
  langsmith.py:458`, `airflow/dev/registry/extract_metadata.py:783`,
  `airflow/providers/amazon/.../hooks/comprehend.py:61`,
  `airflow/providers/apache/livy/.../hooks/livy.py:552`,
  `streamlit/scripts/log_agent_metrics.py:236`. Every one is "an external JSON /
  YAML / REST payload that could in principle be modelled", so the fix is an
  architecture change, not a local edit.
* **15 arguable (50%)** — provider payloads, kwargs bags, locally built dicts.

The pre-guard sample of 30 read the same way: 9 hard false positives, 1–2 clear
true positives.

### Why that is a deletion, not a tuning problem

* **Its TypeScript twin was deleted in #183 on this exact evidence** —
  `@sarj/no-implicit-attribute-access`, read at 50 findings, **0 true positives**.
  The Python rule scores 5/30 weak true positives. That is not a different
  answer, it is the same answer at a different sample size.
* **46,089 findings across 4,783 files is not actionable at any severity.** It
  ships as a pre-commit hook (`sarj-no-implicit-attribute-access`). The only
  realistic consumer response is to turn it off.
* **The residual FP classes are open-ended, not enumerable.** pandas DataFrames,
  argparse `**options`, Django `error_messages`, Streamlit `session_state`,
  SQLAlchemy `_annotations`, zulip's `WildValue`, `.model_dump()` output, dicts
  built four lines above the read — each needs its own guard, and the next corpus
  will supply more. `d["k"]` is one of Python's most common expressions; syntax
  cannot tell "unparsed payload" from "mapping" without types the rule cannot see.

### The three guards shipped anyway

Each is exact, each has a named test, and each test dies when the guard is
mutated out.

* **A `.get(...)` in `decorator_list` position.** `_looks_like_route_or_url` only
  exempts a value starting with `/` or containing `://`, so the router-root
  registration `@task_state_store_router.get("")` slipped through both. **23
  findings** across airflow (`connections.py:185`, `dag_versions.py:80`,
  `event_logs.py:84`, `import_error.py:133`, `providers.py:33`, `tasks.py:59`,
  `xcom.py:141`, `ui/dags.py:87`, and 13 more), litellm and prefect. Position
  answers it where the argument cannot; a decorator is never a mapping lookup, so
  **recall cost is zero**.
* **`meta` in `_EXCLUDED_BASES`.** A deliberately OPEN extension bag whose keys
  third-party middlewares invent — `scrapy/core/downloader/handlers/
  http11.py:531`, `request.meta.get("download_maxsize", self._maxsize)`. No model
  can enumerate them.
* **A receiver annotated with a type IMPORTED from another module.** This
  **reverses** the "structural residual, recorded rather than guessed at"
  decision above, which left 2,519 findings on cross-module TypedDicts
  unguarded. The reversal is justified by a fact the earlier note missed: a
  string subscript on a receiver whose annotation is a non-mapping class does not
  type-check, so the annotation heads that actually survive to a subscript are
  mapping-like by construction — TypedDicts, `dict` subclasses, and open bags.
  `litellm/…/prompt_templates/factory.py:2080` (`current_message.get("tool_calls")`
  where `current_message: AllMessageValues`) and `:3216` are the measured shape.
  `typing` / `collections` exports are excluded, because `Any` and `dict` declare
  nothing, and a test asserts that `payload: Any` and `payload: dict` still fire.

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
