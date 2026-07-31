# SARJ058 `prefer-real-store-in-tests` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_real_store_in_tests.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A `Store` / `Repository` / `Dao` is a persistence port, and in this codebase the
implementation behind it is SQL — `PsqlUserStore`, `PsqlOrganizationStore`,
`PsqlTaskStore`. Re-implementing that port over a Python `dict` produces something
that agrees with Postgres on the happy path and disagrees everywhere the database
actually earns its keep: unique and foreign-key constraints, `ON CONFLICT` upsert
semantics and `COALESCE` on omitted columns, transaction rollback, ordering without an
explicit `ORDER BY`, NULL sort position, type coercion, `LIMIT`/`OFFSET` pagination and
concurrent writes. A suite built on the dict is green by construction: it asserts that
the fake behaves the way its author believed the database behaves. The bug is not
caught in the test — it is *encoded* in it.

The tell is that the fakes read like a second implementation. One first-party
`InMemoryOrganizationStore` docstring says it "mirrors the PsqlOrganizationStore
upsert" and hand-lowers domains "matching the real store's COALESCE/LOWER handling";
its sibling `InMemoryUserStore` reproduces upsert-on-email conflict resolution in
Python. Every
line of that is a claim about SQL that nothing verifies. Both repos already run real
Postgres in tests — one has a `db_pool` fixture in its integration `conftest.py`
and test subclasses of `PsqlTaskStore` / `PsqlOrderStore` that inject faults
into the *real* store — so the real thing is available and the pattern for using it is
already established.

Fires when ALL of these hold:

* the file is a test file or a test-double module — `tests/`, `conftest.py`, a
  `testing/` / `fakes/` / `mocks/` / `test_fakes/` directory, or a `fake*.py`,
  `mock*.py`, `stub*.py` stem. This deliberately reaches past `is_test_path`, which
  misses the shared first-party fake modules such as a `common/testing/fakes.py`
  or a `test_fakes/` directory beside the web server,
* the class name carries a test-double marker (`InMemory`, `Mock`, `Fake`, `Stub`,
  `Dummy`) as a prefix or suffix,
* the class name ends in a persistence-port token (`Store`, `Repository`, `Repo`,
  `Dao`, `Db`, `Database`), or it subclasses a base whose name does,
* and the body is a re-implementation, in one of the two shapes the corpora contain:
  - **dict-backed**: some `self.<attr>` is bound to a container (`{}`, `[]`, `set()`,
    `defaultdict(...)`, a comprehension, a `field(default_factory=dict)`) and, ignoring
    `__init__`, one method *writes* it while a *different* method *reads* it — i.e. the
    class really is keeping the rows, not just recording calls, or
  - **hollow**: the class subclasses the port, leaves at least two methods as bare
    `raise NotImplementedError`, and still has at least one live method — a partial
    second implementation that satisfies the type checker and abandons the contract.

What this rule recognises, and what it does not. It models exactly one spelling of the
defect: a **hand-written class** whose name carries a double marker and a
persistence-port tail. The other spelling — a `unittest.mock` object standing in for a
port, `MagicMock(spec=AudioFileStore)` in a conftest or a bare `AsyncMock()` assigned
into a worker's store slot by a factory — is invisible to it, because there is no class
to name and no body to classify. One first-party repo carries the defect in that form
(roughly a hundred candidate sites) and this rule reports zero there. Reaching it needs
type-directed resolution of what the mock is standing in for, which is a different rule;
do not read a clean run as "no dict-backed ports here".

Corpus evidence. Swept over 42,657 files in 19 repositories: five first-party repos —
repo A (1,179 files, 6 hits), repo B (502 files, 2 hits), repo C (267, 0),
repo D (194, 0), repo E (179, 0), labels stable within this docstring only — and
40,336 files of mature OSS Python — airflow,
dagster, litellm, saleor, django, mlflow, langchain, superset, zulip, prefect, fastapi,
warehouse, sentry-python, celery — with **0 hits**. Exactly ten classes in the two
first-party repos match the name gate; the body gates accept eight and reject two, and
both rejections are correct (below). All eight were read in full and classified by hand:
8 true positives, 0 false positives.

An earlier revision claimed zero OSS hits over a 4,474-file corpus. At nine times that
corpus it fired five times and all five were false positives: langchain's shipped
`InMemoryVectorStore`, litellm's `FakeRedisLockStore`, mlflow's
`MockAbstractStore(AbstractStore)` and two airflow `FakeTaskStateStore`s. The two guards
below — non-relational port qualifiers, and the port-under-test module — remove all five
and cost nothing: repo A stays at 6 and repo B at 2.

Deliberately NOT flagged:

* **a genuine in-memory backend that is the product.** `InMemoryCache`, an LRU, a
  session registry, django's `locmem` cache and email backends and its shipped
  `InMemoryStorage` (`django/core/files/storage/memory.py:168`) — none of these end
  in a persistence-port token, because `Storage`, `Cache`, `Backend`, `Session` and
  `Queue` are deliberately absent from that token list. This was measured, not
  assumed: re-running the identical body gates with those five tails added produces
  three extra hits and all three are false positives — django's
  `DummyStorage` (`tests/messages_tests/utils.py:4`), a first-party
  `FakeCache(CacheClient)` and a first-party
  `FakeAgentSession`. A cache with no durability
  contract, a message-storage backend and a live agent session are not stores,
* **a double whose backing really is a real backend.** One first-party
  `MockDataStore` in a third-party adapter package is
  named like a fake and lives under a `mock_*.py` stem, but it is a Redis-backed
  store of demo-mode session data — a shipped product feature, not a test double.
  It binds `self.cache = cache_client` and every method goes through it, so the
  container-literal requirement rejects it. This is the guard that keeps the rule
  off "mock mode" features,
* **recording spies and canned-response doubles.** One first-party
  `FakeAnalyticsStore` holds
  `self.metric_calls: list[...] = []` and `self._metric_returns`, so it is superficially
  list-backed — but each list is touched by exactly one method: it records the call
  and replays a canned row. Nothing is stored and read back, so there is no second
  implementation of the port to diverge. Requiring a writer method and a *distinct*
  reader method is what separates "keeps the rows" from "remembers the call", and it
  is why `__init__` is excluded from the writers,
* **the never-touched port.** One first-party `_UnusedTaskStore(TaskStore)`
  in a route-discovery test raises `NotImplementedError`
  from *every* method, which is an assertion that route discovery never invokes a
  handler. That is good practice, so the hollow shape additionally requires at least
  one live method,
* **fault injectors built on the real store.** `DeadlockOnMergeOrderStore(
  PsqlOrderStore)`, `RaisingCreateTaskStore(PsqlTaskStore)`,
  `_GatedUserProfileStore(PsqlUserProfileStore)` — a subclass of a `Psql*` /
  `ClickHouse*` / `Redis*` / `Gcs*` base already drives the real implementation and
  only overrides the failure it wants. Any such base suppresses the diagnostic,
* **ports that are not persistence.** `MockMessageEnqueuer`, `FakeEventPublisher`,
  `FakeClerk`, `FakeCommerceAPIService`, `StubVerifier` — a queue, a pub/sub topic and a
  third-party HTTP API have no SQL implementation to prefer, and an in-memory double
  of them is the right call. Only `Store`/`Repository`/`Repo`/`Dao`/`Db`/`Database`
  tails fire; `Client`, `Service`, `Api`, `Gateway`, `Publisher`, `Enqueuer` and
  `Queue` do not. `Table` is excluded too — it names a schema object or a rendered
  grid, not a port,
* **ports whose backend is not a relational database.** langchain's
  `InMemoryVectorStore(VectorStore)` — which langchain *ships*, it is not a test
  double — litellm's `FakeRedisLockStore` and airflow's `FakeTaskStateStore` are a
  vector index, a Redis lock and a task-state bag. There is no `Psql*` sibling to
  prefer, so this rule's advice would be actively wrong. A `Vector`, `Redis`, `Blob`,
  `Doc`, `Graph`, `Lock`, `Memory`, `State`, `Artifact` or `Trace` qualifier
  immediately before the port tail suppresses it, on the port base or on the class
  name with its double marker stripped — `FakeRedisLockStore` declares no base at
  all, and stripping the marker first is what keeps `InMemory` from reading as the
  `Memory` qualifier, so a bare `InMemoryStore` still fires. Of those ten tokens
  `Vector`, `Lock` and `State` are the ones the corpus exercises; the rest are there
  because the same argument applies to them, and all ten together cost zero first-party
  hits. `Key` and `Object` are deliberately absent: adding them was measured and it
  kills a first-party `InMemoryApiKeyStore` and `InMemoryObjectStore`, both true positives,
* **the port under test.** mlflow's `MockAbstractStore(AbstractStore)` lives in
  `tests/store/model_registry/test_abstract_store.py`: it is the minimal concrete
  subclass needed to exercise the ABC's template methods, and the ABC is the system
  under test, not a shipped port being doubled. When the module stem is
  `test_<snake(port)>` or `<snake(port)>_test` the file's whole purpose is testing the
  port, so the subclass is harness. Not tried: "require a `Psql*` sibling in the same
  file" — measured, and it removes all 8 first-party true positives, because the fakes
  live in files that import the port and nothing else,
* **abstract bases, `Protocol`s and `TypedDict`s**, and any class with an
  `@abstractmethod` — those are the port, not a re-implementation of it,
* **null objects.** `NullUpsertTokenStore`, `NoopStore` — the null-object pattern
  is a deliberate no-op, not a claim to behave like the database, so `Null` and `Noop`
  are not double markers here.

The diagnostic names the port only when a base class supplies one. A class that
declares no base — `class FakeMessageStore:` — has no port name to quote, and an
earlier revision fell back to the class's own name, producing "`FakeTaskStateStore`
re-implements the `FakeTaskStateStore` persistence port". That spelling now drops the
name instead of inventing one.

This rule is the persistence-port counterpart of SARJ059 (`prefer-library-fake`),
which covers hand-rolled doubles of *external* services that a maintained library
already fakes. Doubles of this project's own SQL-backed ports have no library to reach
for; the fix is the real store plus the test database.

## Implementation notes

### `_self_attr_access`

`ast.walk` is breadth-first, so an assignment target is marked before the
`self.<attr>` node inside it is reached, and one pass suffices.

### `_container_targets`

A bare `rows = {}` only counts at class-body level; inside a method it is a
local, and treating it as an attribute would couple it to an unrelated
`self.rows`.

### `_is_dict_backed`

Requires a container-bound attribute that one method writes and a *different*
method reads, ignoring `__init__`. A spy that appends to `self.calls` and never
reads it back, or a stub whose only container is seeded in the constructor and
read by one accessor, is recording calls rather than storing rows.

### `_is_port_under_test`

`tests/store/model_registry/test_abstract_store.py` defines
`MockAbstractStore(AbstractStore)` — the minimal concrete subclass needed to
exercise the ABC's template methods. The abstract base is the system under test,
so the subclass is the harness, not a second implementation of a shipped port.

### `_undoubled`

`InMemoryVectorStore` -> `VectorStore`, `UserStoreFake` -> `UserStore`. Removing
the marker first is what keeps `InMemory` from reading as the `Memory` qualifier:
a bare `InMemoryStore` reduces to `Store` and stays flaggable.

### `_is_test_double_path`

Wider than `is_test_path`: both repos park reusable fakes in `testing/`,
`test_fakes/` and `mock_*.py` modules that sit inside production packages.

### `_message`

A class that declares no base class supplies no port name, and naming the fake as
its own port ("`FakeTaskStateStore` re-implements the `FakeTaskStateStore` port")
is nonsense. The second spelling drops the name rather than inventing one.
