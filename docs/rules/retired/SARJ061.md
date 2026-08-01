> **RETIRED.** SARJ061 `no-patching-system-under-test` was withdrawn in #183
> (`7316369`). This document is the evidence it shipped on, recovered from
> `7316369^` and archived here rather than deleted, so the decision stays
> revisitable. Nothing below has been edited; read it as of the day the rule was
> withdrawn.
>
> **The withdrawal record does not agree with itself.** #183's message says
> SARJ061 was "read at ... 25 findings with ... 3 true positives" — 12% precision
> over a 25-finding sample. This document reports something else entirely: a
> before/after finding-count census over 21 corpora, 1,968 findings narrowed to
> 1,736 by three guards, with **no sampled precision measurement at all**. The two
> are not contradictory so much as non-overlapping: 1,736 findings shipped at
> `error`, and the first time anyone measured how many were worth acting on was
> the commit that deleted the rule. The identity of the 3 true positives was
> recorded nowhere and is not recoverable — which is the concrete loss that the
> retention gate in `scripts/check-file-conventions.sh` now exists to prevent.
>
> `SARJ061` is on the append-only code ledger
> (`packages/python/tests/code_ledger.json`, #186) and can never be reallocated:
> this document recommended `# sarj-noqa: SARJ061` by name, so consumer trees may
> still hold suppressions keyed to it.
>
> Links below point at files this commit's parent deleted along with the rule.
> They are left as written rather than repaired; `git show 7316369^:<path>`
> resolves them.

# SARJ061 `no-patching-system-under-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_patching_system_under_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Mocking is a boundary tool. Replacing a collaborator the unit *talks to* — an
HTTP client, a store, a clock — keeps the unit's own behaviour under test. Ripping
out a function or method the unit *is made of* does the opposite: the code path
the test claims to cover no longer runs. `patch.object(Paginator,
"validate_number")` followed by `paginator.get_elided_page_range(2)` proves only
that `get_elided_page_range` calls a mock the test installed a line earlier. Delete
the real `validate_number` and the test still passes.

The failure mode is quiet and permanent. The mock answers with whatever the test
said, so the assertions describe the test's own fixture data; the real branch,
its error handling, and every later change to it are unguarded. Worse, the test
now pins an *internal* call shape, so refactoring the unit — inlining the helper,
renaming it, moving the work — breaks a test that was supposed to be describing
behaviour.

RELATIONSHIP TO SARJ040 (`mock-without-spec`)
---------------------------------------------

**This rule supersedes SARJ040 wherever both fire, and they almost always both
fire.** Measured over the 21-corpus census below, 1,731 of this rule's 1,736
findings are also a SARJ040 finding at the *identical* line and column — 99.71%.
The five exceptions (airflow `test_aws.py:87` and `test_s3.py:1141`, litellm
`test_user_api_key_auth.py:892,938`, langchain `test_summarization.py:1023`)
already pass `autospec=True`, so SARJ040 is satisfied there while this rule still
fires.

The two rules give contradictory instructions at a shared site. SARJ040 says keep
the patch and make the double faithful (`spec=<RealType>`); this rule says the
patch itself is the defect, because the code path the test claims to cover does
not run. Obeying SARJ040 cannot satisfy this rule: a perfectly specced mock of
`Paginator.validate_number` still means `validate_number` never executes. So the
message says so outright — adding `spec=`/`autospec=` does not address the
finding, because the problem is *what* is patched rather than how faithfully.
SARJ040 is the older, broader rule and is left unchanged.

**Cross-file resolution is impossible here, so the rule only fires on shapes it
can prove from one file.** Both are deliberately narrow.

Shape 1 — a sibling of the symbol under test:

* the test does `from <mod> import <names>` and patches `"<mod>.<attr>"` where
  `<attr>` is *itself* one of the names this test file imported from `<mod>` —
  which is the only local proof that `<attr>` is a member of that module rather
  than something the module imported from elsewhere, and
* **the enclosing function itself enters `<mod>`**, either by calling another of
  the names imported from it or through a module alias the file binds (`from
  airflow.security import kerberos` … `kerberos.run(...)`). The evidence has to be
  in the same function as the patch; see the pooled-evidence bullet below.

Shape 2 — the object under test, with a hole in it:

* `patch.object(X, "<attr>")` where the same function constructs `X(...)` (or binds
  a local from a constructor call), `X` is imported from a non-stdlib module, and
* the same function then calls some *other* attribute on that same object. The
  test builds the unit, cuts a method out of it, and exercises what is left.

Deliberately NOT flagged:

* **Patching the SUT module's reference to an external dependency** — the "patch
  where it's used" idiom, `patch("app.billing.requests")` /
  `patch("app.billing.stripe_client")`. The target string names the SUT module but
  the attribute is a third-party import the SUT happens to hold, and patching it is
  correct practice. This is the dominant population: relaxing shape 1 to "any
  attribute of an imported module" produced 86 celery, 14 django and 12
  first-party extra hits, and every one sampled was this idiom — `patch(
  "app.task_executor.rtc")` (livekit's `rtc` module, one first-party site),
  `patch("app.call_manager.add_span_attributes")` (a telemetry helper, a second
  first-party site), `patch("app.services.message_enqueuer.inject")` (a DI
  decorator, a third first-party site), `patch(
  "django.contrib.auth.hashers.get_random_string")` (imported from
  `django.utils.crypto`, `django/tests/auth_tests/test_hashers.py:469`), `patch(
  "celery.backends.database.session.sessionmaker")` (SQLAlchemy,
  `celery/t/unit/backends/test_database.py:808`). Requiring the patched attribute
  to be a name the test file *itself* imported from that module removes all of
  them: a re-exported third-party symbol is not something a test imports from the
  wrapper module,
* **evidence borrowed from a sibling test.** The proof that `<mod>` is the unit
  under test must live in the same function as the patch. Pooling it file-wide let
  one test license another's unrelated patch:
  `litellm/tests/test_litellm/router_utils/test_health_check_allowed_fails_integration.py:661`
  patches `cooldown_handlers._set_cooldown_deployments` while exercising
  `proxy_server._write_health_state_to_router_cache` — a different module
  entirely — and the `from ...cooldown_handlers import _set_cooldown_deployments`
  that licensed it is a function-local import inside a sibling test 400 lines up.
  Test files that import a module in a dozen different test bodies made this the
  single largest false-positive class,
* **module singletons.** A snake_case target that the file only ever drives
  through its attributes and never calls is an object, not a function:
  `patch("...mcp_server_manager.global_mcp_server_manager")` (declared
  `global_mcp_server_manager: MCPServerManager = MCPServerManager()` and patched 83
  times across two litellm suites, always via `mock_mgr.expand_permission_list...`)
  and `patch("celery.platforms.signals")` (`celery/t/unit/utils/test_platforms.py`,
  used as `signals.supported('INT')`). Swapping a module-level singleton is the
  canonical dependency-injection seam — the opposite of the defect,
* **classes and constants.** Only a plain function-shaped name (`snake_case`,
  optionally one leading underscore) is a candidate. A CapWords target is a
  collaborator *type* being swapped for a double — the ordinary seam, e.g. `patch(
  "app.agent_tools.data_capture.collect_tool._CollectTask")` at one first-party
  site, which stands in for a
  LiveKit task — and an ALL_CAPS target is a config knob, e.g. `monkeypatch.setattr(
  "app.orders.batch_order_store.MAX_CONCURRENT_OUTBOUND_PER_ORG", 2)`.
  Dunders (`__call__`, `__init__`) fall out of the same check: they are framework
  hooks, not the unit's logic,
* **boundary-shaped attribute names** — `*_client`, `*_session`, `connection`,
  `engine`, `pool`, `bucket`, `broker`, `socket`, `logger` and friends. A module
  global with that name is an I/O handle, and replacing it is the whole point of
  the seam,
* **a concrete replacement.** `new=` (keyword or positional — arg 2 of `patch`,
  arg 3 of `patch.object`), `new_callable=` and `wraps=` all mean the author wrote
  a substitute rather than accepting an auto-generated `MagicMock`. So does a
  `side_effect=` that delegates back to the real symbol, which is the spy idiom:
  `patch("django.db.models.sql.compiler.cursor_iter", side_effect=cursor_iter)`
  (`django/tests/queries/test_iterator.py:29`) and `patch.object(hasher, "encode",
  side_effect=hasher.encode)` (`django/tests/auth_tests/test_hashers.py:221`) both
  keep the real behaviour and only count calls,
* **`side_effect=<Exception>`.** A mock that raises is a tripwire or a fault
  injector, never a stand-in for the real answer, and the code path being proved is
  the *caller's* — which does run. `patch.object(handler, "format_subject",
  side_effect=AssertionError("Should not be called"))` proves `emit` short-circuits
  when `ADMINS` is empty (`django/tests/logging_tests/tests.py:570`);
  `patch.object(manager, "persist_parsing_result", side_effect=RuntimeError("boom"))`
  proves the parsing loop still records stats
  (`airflow/airflow-core/tests/unit/dag_processing/test_manager.py:1302`);
  `patch("prefect._internal.send_entrypoint_logs._send", side_effect=Exception(...))`
  is a test named `test_silently_swallows_exceptions`
  (`prefect/tests/_internal/test_send_entrypoint_logs.py:115`),
* **`monkeypatch.setattr` in every spelling.** pytest's `setattr` requires a
  replacement value, so it is *always* the concrete-replacement case above — a
  hand-written fake, which is the practice this rule steers toward. It is also the
  house idiom in the audited repos (464 call sites across two first-party repos
  against 243 `mock.patch*` calls); flagging it would bury the signal,
* **stdlib types.** `out = StringIO(); patch.object(out, "flush")` while
  `management.call_command(...)` runs (`django/tests/user_commands/tests.py:454`)
  patches a stdlib buffer, not the unit. The constructor's import module is checked
  against `sys.stdlib_module_names`,
* **test-local classes and factories.** If the class, or the factory that built the
  instance, is defined in the test file, the object is a stub the suite wrote for
  itself, not the production unit: `DoNothingDecorator` in
  `django/tests/test_utils/tests.py:2460` (a two-method `TestContextDecorator`
  subclass declared right above the test) and `no_pool_connection()` in
  `django/tests/backends/postgresql/tests.py:478`,
* **an object that is patched but never exercised through its own surface.**
  `hasher = get_hasher("default"); patch.object(hasher, "verify"); check_password(...)`
  hands the hasher to a module-level function — there the hasher IS the
  collaborator. Shape 2 requires a call to another attribute *of the patched
  object* in the same function,
* `patch` reached through a name no `unittest.mock` import backs — a project's own
  `patch` helper is not this rule's business. **pytest-mock's `mocker.patch` /
  `mocker.patch.object` are deliberately among them**, and that was measured rather
  than overlooked. superset alone spells 1,290 patches through `mocker` against 355
  through `mock.patch`, a 3.6:1 majority, so the omission looks large. Teaching
  `_ModuleFacts.patcher` the `mocker` fixtures (including `module_mocker` /
  `class_mocker` / `session_mocker`, and dropping the `reaches_mock` gate a file
  that never imports `unittest.mock` would otherwise fail) takes the census from
  1,736 to **1,857** — airflow 494 -> 507 and superset 102 -> 210 — and **every one
  of the 121 additions is in OSS**: all seven first-party repos are unchanged to
  the finding. Reading the superset
  additions, they are concentrated on `_get_query`, RLS and permission helpers —
  same-module functions that are really datastore lookups, which is precisely the
  ambiguity recorded under KNOWN LIMIT below. So the spelling buys 121 diagnostics
  of mixed precision, none of them in a repo that runs this ratchet.

KNOWN LIMIT
-----------

The rule cannot separate a helper that *is* the unit's logic from an I/O boundary
the SUT happens to spell as a private function of its own module. Both are
snake_case members of the module under test, both are imported by the test, and
nothing syntactic tells them apart. `patch("sentry_sdk.utils.get_git_revision")`
(`sentry-python/tests/test_utils.py:704`) shells out to `git`;
`patch("corporate.lib.stripe.get_latest_seat_count")`
(`zulip/corporate/tests/test_stripe.py:3065`) is a database aggregate;
`patch("zerver.lib.send_email._send_messages")`
(`zulip/zerver/tests/test_send_email.py:210`) opens SMTP. Each is a legitimate
seam that this rule flags. A verb-prefix heuristic was measured and rejected: 43%
of all hits are I/O-verb-prefixed (`get_`, `send_`, `read_`, `write_`, `fetch_`),
so it would take most of the true positives with it. These are what
`# sarj-noqa: SARJ061` is for.

Shape 2 has a second, narrower limit: it cannot tell a *constructed third-party
client* from the unit. Bind one to a local and drive it, and the message's claim
that the target "belongs to the unit this test then exercises" is false:

```python
client = Redis(host="localhost")     # `_ModuleFacts.origin["Redis"] == "redis"`
with patch.object(client, "ping"):   # reported as the unit's own logic
    client.close()
```

(The literal spelling `patch.object(Redis(...), "ping")` reports nothing, because
`_method_of_object_under_test` accepts only an `ast.Name` receiver, so the binding
is what exposes it.) **No guard for it survived measurement, and the reason is that
the shape does not occur in real code.** Reusing the boundary vocabulary above on
the *constructor* name removes 4 of the 982 shape-2 findings, all four in
dagster-cloud's `ecs_tests/test_client.py` (`patch.object(client,
"_check_for_stopped_tasks")` at lines 439, 506 and 554 plus
`"_check_all_essential_containers_are_running"` at 440), where `Client` is
dagster's own ECS wrapper and the unit under test — 4 true positives, 0 false.
A CamelCase-aware type tail
(`*Client`, `*Session`, `*Pool`, `*Logger`, `*Cache`, …) removes 39, and they are
the same mistake at scale: litellm's `WebSearchInterceptionLogger` (10),
`RedisSemanticCache` (4), `LangsmithLogger`, `S3Logger` and airflow's
`DataFusionEngine` (6) are all classes their own suites construct and test. A
library that *implements* clients, caches and loggers names its units that way, so
the name cannot separate them. Not one of the 43 findings the two guards would
remove is the Redis shape, and that is structural rather than luck: shape 2
requires the test to construct the object *and* call another of its methods, which
is what a suite does to its own unit, not to a client it hands to one. The
diagnostic is therefore accurate on every finding the corpus contains, and the
synthetic case is recorded here rather than guarded against.

CORPUS EVIDENCE
---------------

Measured over 19 repos — five first-party repos and the 14 OSS corpora, 40,336
Python files. `before` is the rule as first written; `after` is with the three
guards above (function-local evidence, module singletons,
`side_effect=<Exception>`). Repo labels are stable within this docstring only:

| corpus        | before | after |
|---------------|--------|-------|
| repo A        | 0      | 0     |
| repo B        | 0      | 0     |
| repo C        | 0      | 0     |
| repo D        | 0      | 0     |
| repo E        | 1      | 1     |
| airflow       | 512    | 494   |
| dagster       | 34     | 26    |
| litellm       | 755    | 645   |
| saleor        | 0      | 0     |
| django        | 11     | 10    |
| mlflow        | 273    | 216   |
| langchain     | 2      | 2     |
| superset      | 115    | 102   |
| zulip         | 146    | 130   |
| prefect       | 36     | 34    |
| fastapi       | 0      | 0     |
| warehouse     | 0      | 0     |
| sentry-python | 5      | 5     |
| celery        | 78     | 71    |
| **total**     | 1968   | 1736  |

**Every guard costs zero first-party hits** — repo A, repo B, repo C and
repo D are 0 before and after, and repo E's single hit survives all three, so
all 232 removals are OSS. Applied on its own to the unguarded rule, the
function-local guard removes 196, the singleton guard 76 and the tripwire guard
30; they overlap heavily (63 of the singleton removals are also pooled-evidence
removals), so dropping one guard from the finished rule re-adds 126, 12 and 24
respectively.

The module-alias half of the function-local guard is what keeps it honest. The
naive form — "a bare call to another name imported from `<mod>`, in this
function" — removes a comparable 199, but 18 of those are real findings reached
through the module object rather than a bare name: `@mock.patch(
"airflow.security.kerberos.renew_from_kt")` on a test whose body runs
`kerberos.run(...)` and asserts `mock_renew_from_kt.mock_calls == [...]`
(`airflow/airflow-core/tests/unit/security/test_kerberos.py:306`), and
`mock.patch("mlflow.utils.databricks_utils.get_workspace_id")` around
`databricks_utils._print_databricks_deployment_job_url(...)`
(`mlflow/tests/utils/test_databricks_utils.py:964`). Resolving `kerberos` back to
`airflow.security.kerberos` recovers all 18 and still removes every one of the 96
litellm pooled-evidence hits.

All 11 original django hits and 10 sampled celery hits were read at the cited
line, as were every removal of the tripwire guard and a sample of the other two.
The remaining hits are the real pattern, and most of them assert on the mock and
nothing else: `django/tests/pagination/tests.py:597` (`patch.object(paginator,
"validate_number")` then `paginator.get_elided_page_range(2)`, whose only
assertion is `mock.assert_called_with(2)`),
`django/tests/backends/oracle/test_creation.py:43` and
`django/tests/backends/postgresql/test_creation.py:105` (`DatabaseCreation.
_create_test_db` exercised with `_test_user_create` / `_database_exists` mocked
out), `django/tests/auth_tests/test_hashers.py:462` (`check_password` called with
its module siblings `identify_hasher` and `make_password` both mocked),
`celery/t/unit/backends/test_gcs.py:105` (`GCSBackend(...).get(...)` with
`_get_blob` and `_is_firestore_ttl_policy_enabled` mocked, asserting
`mock_get_blob.assert_called_once_with("testkey1")`),
`celery/t/unit/contrib/test_migrate.py:209` (`move_by_taskmap(...)` with its own
module's `move` mocked, asserting `move.assert_called()`),
`celery/t/unit/utils/test_platforms.py:97` (`set_mp_process_title(...)` with the
sibling `set_process_title` mocked, asserting only that it was called) and
`celery/t/unit/tasks/test_chord.py:228` (`ch.apply_async()` with `ch.run`
replaced, asserting `run.assert_called_once_with(...)`).

celery's remaining 71 are concentrated: `t/unit/backends/test_gcs.py` (39) and
`t/unit/utils/test_platforms.py` (24) account for 63 of them, both suites that
mock a module's own functions and assert on the mock. The rule is a real finding
there, not noise, but a codebase adopting it mid-flight should expect to
`# sarj-noqa: SARJ061` the deliberate cases — a sibling that really is slow or
privileged (`celery.platforms.setuid`) is exactly what suppression is for.

The rule finds nothing in repo A or repo B today. Both reach for
`monkeypatch.setattr` with a hand-written replacement (464 sites) rather than an
auto-generated `MagicMock`, which is the practice this rule exists to protect, so
zero is the right answer there rather than evidence the rule is dead.

## Implementation notes

### `_raises_instead_of_answering`

`side_effect=AssertionError("Should not be called")` is a tripwire and
`side_effect=RuntimeError("boom")` is a fault injector. Neither stands in for
the unit's own logic, and the path being proved is the caller's, which runs.

### `_top_level_functions`

Walking these rather than every `FunctionDef` keeps the check to a single pass
over each body — a nested closure is visited as part of its enclosing function,
not a second time on its own.

### `_Scope`

Both shapes need facts confined to a single function: which names it calls and
through which receivers (shape 1's proof that this test enters the module it
patches), and which classes it constructs, which locals hold the result of a
construction and which attributes it calls on each name (shape 2).

### `_Scope.other_attrs_called_on`

Covers both spellings: the local instance itself, and any instance built
from a patched class in the same body.

### `_ModuleFacts`

Every judgement this rule makes is local: which module a name came from, which
names the file imported from a given module, what the file defines itself, and
how it uses each name. Cross-file resolution is out of reach, so these tables
are the entire evidence base.

### `_ModuleFacts.is_module_singleton`

`global_mcp_server_manager.expand_permission_list(...)` with no bare
`global_mcp_server_manager(...)` anywhere is a module-level instance, and
swapping one is the dependency-injection seam this rule steers toward.

### `_ModuleFacts.resolve_module`

`import a.b as x` makes `x.f()` a call into `a.b`; `from a import b` makes
`b.f()` a call into `a.b` when `b` is a submodule. Anything else is already
absolute or unresolvable, and is returned unchanged.

### `_ModuleFacts.is_module_under_test`

Two conditions, and both matter. The file must import `attr` itself from
`module` — that is the only local proof `attr` is a member of `module`
rather than a third-party name `module` re-exports. And the function
holding the patch must itself enter `module`, which is what makes `module`
the unit under test rather than an incidental dependency of some other
test in the same file. Entering it counts either way round: calling
another name imported from it, or calling through a module alias.
