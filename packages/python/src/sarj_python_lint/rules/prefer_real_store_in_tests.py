"""SARJ055: a hand-rolled in-memory store makes the test verify a dict, not the database.

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

The tell is that the fakes read like a second implementation. bulbul's
`InMemoryOrganizationStore` docstring says it "mirrors the PsqlOrganizationStore
upsert" and hand-lowers domains "matching the real store's COALESCE/LOWER handling";
`InMemoryUserStore` reproduces upsert-on-email conflict resolution in Python. Every
line of that is a claim about SQL that nothing verifies. Both repos already run real
Postgres in tests — bulbul has a `db_pool` fixture in `integration/tests/conftest.py`
and test subclasses of `PsqlTaskStore` / `PsqlScenarioIssueStore` that inject faults
into the *real* store — so the real thing is available and the pattern for using it is
already established.

Fires when ALL of these hold:

* the file is a test file or a test-double module — `tests/`, `conftest.py`, a
  `testing/` / `fakes/` / `mocks/` / `test_fakes/` directory, or a `fake*.py`,
  `mock*.py`, `stub*.py` stem. This deliberately reaches past `is_test_path`, which
  misses noura-be's `common/testing/fakes.py` and bulbul's `webserver/test_fakes/`,
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

Corpus evidence. Measured over bulbul (`/Users/nasrmaswood/code/bulbul/python`, 1,179
files, 6 hits), noura-be (`/Users/nasrmaswood/code/noura-be/python`, 502 files, 2 hits),
django (2,927 files, 0), fastapi (1,130, 0) and celery (417, 0). Exactly ten classes in
the two first-party repos match the name gate; the body gates accept eight and reject
two, and both rejections are correct (below). All eight were read in full and classified
by hand: 8 true positives, 0 false positives. The OSS corpora produce zero hits — not
one class in 4,474 files of mature Python pairs a test-double marker with a
persistence-port tail — which is the right behaviour for a rule this opinionated, and a
direct consequence of `Storage` and `Cache` being kept out of the token list.

Deliberately NOT flagged:

* **a genuine in-memory backend that is the product.** `InMemoryCache`, an LRU, a
  session registry, django's `locmem` cache and email backends and its shipped
  `InMemoryStorage` (`django/core/files/storage/memory.py:168`) — none of these end
  in a persistence-port token, because `Storage`, `Cache`, `Backend`, `Session` and
  `Queue` are deliberately absent from that token list. This was measured, not
  assumed: re-running the identical body gates with those five tails added produces
  three extra hits and all three are false positives — django's
  `DummyStorage` (`tests/messages_tests/utils.py:4`), noura-be's
  `FakeCache(CacheClient)` (`dashboard/tests/test_coalescing_cache.py:10`) and its
  `FakeAgentSession` (`voice/tests/fakes.py:163`). A cache with no durability
  contract, a message-storage backend and a live agent session are not stores,
* **a double whose backing really is a real backend.** noura-be's
  `MockDataStore` (`common/adapters/vision_bank/v2/mock_data_store.py:104`) is
  named like a fake and lives under a `mock_*.py` stem, but it is a Redis-backed
  store of demo-mode session data — a shipped product feature, not a test double.
  It binds `self.cache = cache_client` and every method goes through it, so the
  container-literal requirement rejects it. This is the guard that keeps the rule
  off "mock mode" features,
* **recording spies and canned-response doubles.** bulbul's
  `FakeAnalyticsStore` (`webserver/tests/fakes/analytics_fakes.py:26`) holds
  `self.kpi_calls: list[...] = []` and `self._kpi_returns`, so it is superficially
  list-backed — but each list is touched by exactly one method: it records the call
  and replays a canned row. Nothing is stored and read back, so there is no second
  implementation of the port to diverge. Requiring a writer method and a *distinct*
  reader method is what separates "keeps the rows" from "remembers the call", and it
  is why `__init__` is excluded from the writers,
* **the never-touched port.** bulbul's `_UnusedTaskStore(TaskStore)`
  (`integration/tests/router/test_mcp_discovery.py:44`) raises `NotImplementedError`
  from *every* method, which is an assertion that route discovery never invokes a
  handler. That is good practice, so the hollow shape additionally requires at least
  one live method,
* **fault injectors built on the real store.** `DeadlockOnMergeScenarioIssueStore(
  PsqlScenarioIssueStore)`, `RaisingCreateTaskStore(PsqlTaskStore)`,
  `_GatedAgentProfileStore(PsqlAgentProfileStore)` — a subclass of a `Psql*` /
  `ClickHouse*` / `Redis*` / `Gcs*` base already drives the real implementation and
  only overrides the failure it wants. Any such base suppresses the diagnostic,
* **ports that are not persistence.** `MockMessageEnqueuer`, `FakeEventPublisher`,
  `FakeClerk`, `FakeSallaAPIService`, `StubVerifier` — a queue, a pub/sub topic and a
  third-party HTTP API have no SQL implementation to prefer, and an in-memory double
  of them is the right call. Only `Store`/`Repository`/`Repo`/`Dao`/`Db`/`Database`
  tails fire; `Client`, `Service`, `Api`, `Gateway`, `Publisher`, `Enqueuer` and
  `Queue` do not. `Table` is excluded too — it names a schema object or a rendered
  grid, not a port,
* **abstract bases, `Protocol`s and `TypedDict`s**, and any class with an
  `@abstractmethod` — those are the port, not a re-implementation of it,
* **null objects.** `NullUpsertCredentialStore`, `NoopStore` — the null-object pattern
  is a deliberate no-op, not a claim to behave like the database, so `Null` and `Noop`
  are not double markers here.

This rule is the persistence-port counterpart of SARJ056 (`prefer-library-fake`),
which covers hand-rolled doubles of *external* services that a maintained library
already fakes. Doubles of this project's own SQL-backed ports have no library to reach
for; the fix is the real store plus the test database.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# A test-double marker leading the class name (`InMemoryUserStore`, `StubUserStore`).
# The lookahead keeps `Mockery` / `Fakeout` out. `Null` and `Noop` are absent on
# purpose: a null object does not claim to behave like the real store.
_DOUBLE_PREFIX_RE = re.compile(r"^_*(?:InMemory|Mock|Fake|Stub|Dummy)(?=[A-Z_]|$)")

# The same marker trailing instead (`UserStoreFake`).
_DOUBLE_SUFFIX_RE = re.compile(r"(?:InMemory|Mock|Fake|Stub|Dummy)$")

# Tokens that name a persistence port. Case-sensitive CamelCase tails, so `Storage`,
# `Restore` and `Bookstore` do not match `Store`. `Cache`, `Storage`, `Table`,
# `Client`, `Service`, `Api` and `Publisher` are excluded — see the module docstring.
_PORT_TAIL_RE = re.compile(r"(?:Store|Repository|Repo|DAO|Dao|Database|DB|Db)$")

# A base class that already IS the real implementation: subclassing it to inject one
# fault is the practice this rule is asking for, not the one it is complaining about.
_REAL_BACKEND_RE = re.compile(
    r"^(?:Psql|Postgres|Postgresql|Pg|Sql|Sqlite|MySql|MariaDb|ClickHouse|Redis|Mongo|Dynamo|Gcs|S3|BigQuery|Elastic)",
    re.IGNORECASE,
)

# Bases that make the class the port rather than an implementation of it.
_ABSTRACT_BASES = frozenset({"ABC", "ABCMeta", "Protocol", "TypedDict"})

# Callables that build an empty (or seeded) container to keep rows in.
_CONTAINER_FACTORIES = frozenset(
    {
        "dict",
        "list",
        "set",
        "frozenset",
        "tuple",
        "defaultdict",
        "OrderedDict",
        "Counter",
        "deque",
        "WeakValueDictionary",
        "WeakKeyDictionary",
    }
)

# `@dataclass` fields spell the container as `field(default_factory=dict)`.
_FIELD_FACTORIES = frozenset({"field", "Field"})

# Container methods that mutate. `pop` is counted as a write; it is a delete that
# happens to return the row.
_MUTATORS = frozenset(
    {
        "append",
        "add",
        "extend",
        "insert",
        "update",
        "setdefault",
        "pop",
        "popitem",
        "clear",
        "remove",
        "discard",
        "sort",
        "__setitem__",
    }
)

_CONTAINER_LITERALS = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Directories that hold shared test doubles but are not `tests/`.
_DOUBLE_DIR_NAMES = frozenset({"testing", "fakes", "mocks", "doubles", "test_fakes", "test_doubles", "test_utils"})

# File stems that hold shared test doubles (`fakes.py`, `mock_data_store.py`).
_DOUBLE_STEM_RE = re.compile(r"(?:^|_)(?:fakes?|mocks?|stubs?|doubles?|testing)(?:$|_)")

# Two live methods plus two abandoned ones is the smallest thing that reads as a
# partial second implementation rather than a placeholder.
_MIN_HOLLOW_STUBS = 2


class PreferRealStoreInTests(Rule):
    """A dict-backed fake of a SQL-backed persistence port verifies the fake, not the database."""

    id: str = "prefer-real-store-in-tests"
    code: str = "SARJ055"
    description: str = (
        "Hand-rolled in-memory `Store`/`Repository` double — the test verifies a dict instead of the real store."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag hand-rolled in-memory re-implementations of a persistence port.

        Returns:
            One diagnostic per re-implemented store class, sorted by position.

        """
        if not _is_test_double_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"`{node.name}` re-implements the `{port}` persistence port in memory, so every test "
                    "that uses it verifies a dict rather than the real store — unique and foreign-key "
                    "constraints, `ON CONFLICT` upserts, transaction rollback, `ORDER BY` and NULL "
                    "ordering, pagination and concurrent writes all differ in the backend, and the suite "
                    f"stays green while production breaks. Drive the real `{port}` implementation — the "
                    "one named for its backend, `Psql*` by this codebase's convention — against the test "
                    "database fixture, and subclass it if you need to inject a failure."
                ),
            )
            for node, port in _rehomed_stores(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_test_double_path(path: Path) -> bool:
    """Report whether `path` holds tests or shared test doubles.

    Wider than `is_test_path`: both repos park reusable fakes in `testing/`,
    `test_fakes/` and `mock_*.py` modules that sit inside production packages.

    Returns:
        True when the file is a test or a test-double module.

    """
    if is_test_path(path):
        return True
    if any(part in _DOUBLE_DIR_NAMES for part in path.parts):
        return True
    return bool(_DOUBLE_STEM_RE.search(path.stem))


def _rehomed_stores(tree: ast.Module) -> list[tuple[ast.ClassDef, str]]:
    hits: list[tuple[ast.ClassDef, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_double_name(node.name):
            continue
        bases = [name for base in node.bases if (name := _dotted_tail(base)) is not None]
        port_base = next((b for b in bases if _PORT_TAIL_RE.search(b)), None)
        if port_base is None and not _PORT_TAIL_RE.search(node.name):
            continue
        if _is_abstract(node, bases) or any(_REAL_BACKEND_RE.match(b) for b in bases):
            continue
        if _is_dict_backed(node) or (port_base is not None and _is_hollow_port(node)):
            hits.append((node, port_base or node.name))
    return hits


def _is_double_name(name: str) -> bool:
    return bool(_DOUBLE_PREFIX_RE.search(name) or _DOUBLE_SUFFIX_RE.search(name))


def _dotted_tail(node: ast.expr) -> str | None:
    """Reduce a base-class expression to its final identifier.

    Returns:
        `Store` for `Store`, `stores.Store` and `Store[int]`; None otherwise.

    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _dotted_tail(node.value)
    return None


def _is_abstract(node: ast.ClassDef, bases: list[str]) -> bool:
    if any(base in _ABSTRACT_BASES for base in bases):
        return True
    if any(kw.arg == "metaclass" and _dotted_tail(kw.value) in _ABSTRACT_BASES for kw in node.keywords):
        return True
    return any(_dotted_tail(dec) == "abstractmethod" for method in _methods(node) for dec in method.decorator_list)


def _methods(node: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [stmt for stmt in node.body if isinstance(stmt, _FUNC_NODES)]


def _is_dict_backed(node: ast.ClassDef) -> bool:
    """Report whether the class keeps rows in a container of its own.

    Requires a container-bound attribute that one method writes and a *different*
    method reads, ignoring `__init__`. A spy that appends to `self.calls` and never
    reads it back, or a stub whose only container is seeded in the constructor and
    read by one accessor, is recording calls rather than storing rows.

    Returns:
        True when the class stores and serves its own rows.

    """
    attrs = _container_attrs(node)
    if not attrs:
        return False
    writers: dict[str, set[str]] = {}
    readers: dict[str, set[str]] = {}
    for method in _methods(node):
        if method.name == "__init__":
            continue
        written, read = _self_attr_access(method)
        for attr in written & attrs:
            writers.setdefault(attr, set()).add(method.name)
        for attr in read & attrs:
            readers.setdefault(attr, set()).add(method.name)
    return any(_stores_rows(writers.get(attr, set()), readers.get(attr, set())) for attr in attrs)


def _stores_rows(writers: set[str], readers: set[str]) -> bool:
    """Report whether some method writes the attribute and some *other* method reads it.

    Returns:
        True when a writer and a distinct reader both exist.

    """
    return bool(writers) and bool(readers) and len(writers | readers) > 1


def _container_attrs(node: ast.ClassDef) -> set[str]:
    attrs: set[str] = set()
    for stmt in node.body:
        attrs |= _container_targets(stmt, allow_bare_name=True)
    for method in _methods(node):
        for child in ast.walk(method):
            attrs |= _container_targets(child, allow_bare_name=False)
    return attrs


def _container_targets(stmt: ast.AST, *, allow_bare_name: bool) -> set[str]:
    """Name the attributes a container is being bound to by one statement.

    A bare `rows = {}` only counts at class-body level; inside a method it is a
    local, and treating it as an attribute would couple it to an unrelated
    `self.rows`.

    Returns:
        The attribute names bound to a container by `stmt`.

    """
    if isinstance(stmt, ast.Assign) and _is_container(stmt.value):
        targets: list[ast.expr] = list(stmt.targets)
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and _is_container(stmt.value):
        targets = [stmt.target]
    else:
        return set()
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            if allow_bare_name:
                names.add(target.id)
        elif (attr := _self_attr(target)) is not None:
            names.add(attr)
    return names


def _is_container(value: ast.expr) -> bool:
    if isinstance(value, _CONTAINER_LITERALS):
        return True
    if not isinstance(value, ast.Call):
        return False
    called = _dotted_tail(value.func)
    if called in _CONTAINER_FACTORIES:
        return True
    if called not in _FIELD_FACTORIES:
        return False
    return any(kw.arg == "default_factory" and _dotted_tail(kw.value) in _CONTAINER_FACTORIES for kw in value.keywords)


def _self_attr(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def _self_attr_access(func: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[set[str], set[str]]:
    """Split the `self.<attr>` accesses in one method into writes and reads.

    `ast.walk` is breadth-first, so an assignment target is marked before the
    `self.<attr>` node inside it is reached, and one pass suffices.

    Returns:
        The attribute names written, and the attribute names read.

    """
    write_positions: set[int] = set()
    written: set[str] = set()
    read: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _mark_write(target, write_positions)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            _mark_write(node.target, write_positions)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                _mark_write(target, write_positions)
        elif isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Attribute) and callee.attr in _MUTATORS and _self_attr(callee.value) is not None:
                write_positions.add(id(callee.value))
        elif isinstance(node, ast.Attribute):
            name = _self_attr(node)
            if name is not None:
                (written if id(node) in write_positions else read).add(name)
    return written, read


def _mark_write(target: ast.expr, write_positions: set[int]) -> None:
    if isinstance(target, ast.Subscript):
        if _self_attr(target.value) is not None:
            write_positions.add(id(target.value))
    elif isinstance(target, ast.Attribute):
        if _self_attr(target) is not None:
            write_positions.add(id(target))
    elif isinstance(target, ast.Tuple | ast.List):
        for element in target.elts:
            _mark_write(element, write_positions)


def _is_hollow_port(node: ast.ClassDef) -> bool:
    """Report whether the class implements part of the port and abandons the rest.

    Returns:
        True when at least two non-dunder methods are bare `raise
        NotImplementedError` and at least one method still does something.

    """
    abandoned = 0
    live = 0
    for method in _methods(node):
        if method.name.startswith("__"):
            continue
        if _raises_not_implemented(method):
            abandoned += 1
        else:
            live += 1
    return abandoned >= _MIN_HOLLOW_STUBS and live >= 1


def _raises_not_implemented(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = [stmt for stmt in method.body if not _is_docstring(stmt)]
    if not body:
        return False
    last = body[-1]
    if not isinstance(last, ast.Raise) or last.exc is None:
        return False
    raised = last.exc.func if isinstance(last.exc, ast.Call) else last.exc
    if _dotted_tail(raised) != "NotImplementedError":
        return False
    # `msg = "..."` then `raise NotImplementedError(msg)` is the house style.
    return all(isinstance(stmt, ast.Assign) for stmt in body[:-1])


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)
