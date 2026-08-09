"""SARJ058 — A hand-rolled in-memory store makes the test verify a dict, not the database.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_real_store_in_tests.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# A test-double marker leading the class name (`InMemoryUserStore`, `StubUserStore`).
_DOUBLE_PREFIX_RE = re.compile(r"^_*(?:InMemory|Mock|Fake|Stub|Dummy)(?=[A-Z_]|$)")

# The same marker trailing instead (`UserStoreFake`).
_DOUBLE_SUFFIX_RE = re.compile(r"(?:InMemory|Mock|Fake|Stub|Dummy)$")

# Tokens that name a persistence port.
_PORT_TAIL = r"(?:Store|Repository|Repo|DAO|Dao|Database|DB|Db)"
_PORT_TAIL_RE = re.compile(rf"{_PORT_TAIL}$")

# Qualifiers exclude ports for non-relational stores from this relational-store rule.
_NON_RELATIONAL_RE = re.compile(rf"(?:Vector|Redis|Blob|Doc|Graph|Lock|Memory|State|Artifact|Trace){_PORT_TAIL}$")

# `AbstractStore` -> `abstract_store`, for spotting `test_<port>.py`.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")

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

# Container methods that mutate.
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

# The middle of the diagnostic, shared by both spellings of its opening clause.
_DIVERGENCE = (
    " persistence port in memory, so every test that uses it verifies a dict rather than the real store — "
    "unique and foreign-key constraints, `ON CONFLICT` upserts, transaction rollback, `ORDER BY` and NULL "
    "ordering, pagination and concurrent writes all differ in the backend, and the suite stays green while "
    "production breaks. Drive the real "
)

_ADVICE = (
    "implementation — the one named for its backend, `Psql*` by this codebase's convention — against the "
    "test database fixture, and subclass it if you need to inject a failure."
)


class PreferRealStoreInTests(Rule):
    id: str = "prefer-real-store-in-tests"
    code: str = "SARJ058"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tests should exercise the real persistence implementation instead of an in-memory reimplementation.",
        rationale="Container-backed store doubles omit database constraints, transactions, ordering, and concurrency semantics.",
        remediation="Run the real store against a test database and subclass it only when a test must inject a failure.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test and shared-double paths are analyzed.",
            "The class must resemble a relational persistence double backed by a mutable container or hollow methods.",
        ),
        examples=(
            RuleExample(
                example_id="container-backed-store-double",
                title="Test reimplements a store with a dictionary",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/user_store.py",
                        "class FakeUserStore(UserStore):\n    def __init__(self):\n        self.rows = {}\n\n    def add(self, user):\n        self.rows[user.id] = user\n\n    def get(self, user_id):\n        return self.rows.get(user_id)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/user_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="real-store-subclass",
                title="Test subclasses the real store to inject a failure",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/user_store.py",
                        'class FailingUserStore(PsqlUserStore):\n    def add(self, user):\n        raise OSError("database unavailable")\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/user_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag hand-rolled in-memory re-implementations of a persistence port."""
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
                message=_message(node.name, port),
            )
            for node, port in _rehomed_stores(tree, path.stem)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _message(name: str, port: str | None) -> str:
    """Word the diagnostic around the port, or around nothing when no base names one."""
    subject = f"the `{port}`" if port is not None else "a"
    real = f"`{port}` " if port is not None else ""
    return f"`{name}` re-implements {subject}{_DIVERGENCE}{real}{_ADVICE}"


def _is_test_double_path(path: Path) -> bool:
    """Report whether `path` holds tests or shared test doubles."""
    if is_test_path(path):
        return True
    if any(part in _DOUBLE_DIR_NAMES for part in path.parts):
        return True
    return bool(_DOUBLE_STEM_RE.search(path.stem))


def _rehomed_stores(tree: ast.Module, stem: str) -> list[tuple[ast.ClassDef, str | None]]:
    hits: list[tuple[ast.ClassDef, str | None]] = []
    for node in nodes(tree, ast.ClassDef):
        if not _is_double_name(node.name):
            continue
        bases = [name for base in node.bases if (name := _dotted_tail(base)) is not None]
        port_base = next((b for b in bases if _PORT_TAIL_RE.search(b)), None)
        if port_base is None and not _PORT_TAIL_RE.search(node.name):
            continue
        if _is_abstract(node, bases) or any(_REAL_BACKEND_RE.match(b) for b in bases):
            continue
        if _is_non_relational(node.name, port_base) or _is_port_under_test(stem, node.name, port_base):
            continue
        if _is_dict_backed(node) or (port_base is not None and _is_hollow_port(node)):
            hits.append((node, port_base))
    return hits


def _is_double_name(name: str) -> bool:
    return bool(_DOUBLE_PREFIX_RE.search(name) or _DOUBLE_SUFFIX_RE.search(name))


def _undoubled(name: str) -> str:
    """Strip the test-double marker, leaving the port the class is a double of."""
    return _DOUBLE_SUFFIX_RE.sub("", _DOUBLE_PREFIX_RE.sub("", name))


def _is_non_relational(name: str, port_base: str | None) -> bool:
    """Report whether the port names a backend that is not a relational database."""
    if port_base is not None and _NON_RELATIONAL_RE.search(port_base):
        return True
    return bool(_NON_RELATIONAL_RE.search(_undoubled(name)))


def _is_port_under_test(stem: str, name: str, port_base: str | None) -> bool:
    """Report whether the file exists to test the port this class subclasses."""
    subject = _snake(port_base if port_base is not None else _undoubled(name))
    return stem in {f"test_{subject}", f"{subject}_test"}


def _snake(name: str) -> str:
    return _CAMEL_BOUNDARY_RE.sub("_", name).lower()


def _dotted_tail(node: ast.expr) -> str | None:
    """Reduce a base-class expression to its final identifier."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attr):
            return attr
        case ast.Subscript(value=value):
            return _dotted_tail(value)
        case _:
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
    """Report whether the class keeps rows in a container of its own."""
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
    """Report whether some method writes the attribute and some *other* method reads it."""
    return bool(writers) and bool(readers) and len(writers | readers) > 1


def _container_attrs(node: ast.ClassDef) -> set[str]:
    attrs: set[str] = set()
    for stmt in node.body:
        attrs |= _container_targets(stmt, allow_bare_name=True)
    for method in _methods(node):
        for child in walk(method):
            attrs |= _container_targets(child, allow_bare_name=False)
    return attrs


def _container_targets(stmt: ast.AST, *, allow_bare_name: bool) -> set[str]:
    """Name the attributes a container is being bound to by one statement."""
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
    """Split the `self.<attr>` accesses in one method into writes and reads."""
    write_positions: set[int] = set()
    written: set[str] = set()
    read: set[str] = set()
    for node in walk(func):
        match node:
            case ast.Assign(targets=targets):
                for target in targets:
                    _mark_write(target, write_positions)
            case ast.AugAssign() | ast.AnnAssign():
                _mark_write(node.target, write_positions)
            case ast.Delete(targets=targets):
                for target in targets:
                    _mark_write(target, write_positions)
            case ast.Call(func=ast.Attribute(attr=attribute, value=value)):
                if attribute in _MUTATORS and _self_attr(value) is not None:
                    write_positions.add(id(value))
            case ast.Attribute():
                name = _self_attr(node)
                if name is not None:
                    (written if id(node) in write_positions else read).add(name)
            case _:
                pass
    return written, read


def _mark_write(target: ast.expr, write_positions: set[int]) -> None:
    match target:
        case ast.Subscript(value=value):
            if _self_attr(value) is not None:
                write_positions.add(id(value))
        case ast.Attribute():
            if _self_attr(target) is not None:
                write_positions.add(id(target))
        case ast.Tuple() | ast.List():
            for element in target.elts:
                _mark_write(element, write_positions)
        case _:
            pass


def _is_hollow_port(node: ast.ClassDef) -> bool:
    """Report whether the class implements part of the port and abandons the rest."""
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
