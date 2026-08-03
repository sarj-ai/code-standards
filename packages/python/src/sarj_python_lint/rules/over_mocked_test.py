"""SARJ062 — A test that substitutes six collaborators exercises the mock wiring, not the code.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_over_mocked_test.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, NamedTuple, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path


_THRESHOLD = 5

_MOCK_MODULE = "unittest.mock"
_MOCK_BACKPORT = "mock"

# Constructors that mint a stand-in for a collaborator.
_MOCK_FACTORIES = frozenset(
    {"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock", "create_autospec"}
)

_PATCH = "patch"

# `patch.object` / `patch.multiple` / `patch.dict` — the sub-forms of `patch`.
_PATCH_SUBFORMS = frozenset({"object", "multiple", "dict"})

# `patch.multiple(target, spec=..., a=Mock())`: everything that is NOT one of
# these keywords names an attribute being replaced.
_PATCH_CONFIG_KWARGS = frozenset({"spec", "spec_set", "autospec", "new_callable", "create", "instance", "unsafe"})

# `patch(target, new)` supplies the replacement itself and injects no parameter;
# `patch.object(target, attribute, new)` needs one more positional to say so.
_PATCH_REPLACEMENT_ARITY = 2
_PATCH_OBJECT_REPLACEMENT_ARITY = 3

# `monkeypatch.setattr(target, name, value)` names the attribute separately;
# the two-argument form spells it into the dotted target instead.
_SETATTR_SPLIT_ARITY = 3

# pytest-mock's fixture.
_MOCKER = "mocker"

_MONKEYPATCH = "monkeypatch"

# `monkeypatch.setenv`/`delenv` are environment, not substitution; `setitem`/
# `delitem` edit a config dict; `syspath_prepend`/`chdir` are process state.
_MONKEYPATCH_SUBSTITUTION = "setattr"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test"

# The receiver of an attribute chain that is the test case rather than a double.
_TEST_CASE_RECEIVERS = frozenset({"self", "cls"})

# `self.client` is a collaborator hung off the test case; `self` alone is not.
_TEST_CASE_DEPTH = 2

# Tokens naming test-infrastructure knobs rather than collaborators: the
# environment, configuration, logging, the clock, and the retry/timeout dials.
_INFRA_TOKENS = frozenset(
    {
        "argv",
        "backoff",
        "cfg",
        "clock",
        "conf",
        "config",
        "configs",
        "cwd",
        "date",
        "datetime",
        "delay",
        "delays",
        "env",
        "environ",
        "environment",
        "envs",
        "freeze",
        "getenv",
        "interval",
        "intervals",
        "log",
        "logger",
        "logging",
        "logs",
        "monotonic",
        "now",
        "poll",
        "random",
        "retries",
        "retry",
        "seed",
        "setenv",
        "setting",
        "settings",
        "sleep",
        "stderr",
        "stdout",
        "time",
        "timeout",
        "timeouts",
        "timezone",
        "today",
        "tz",
        "utcnow",
        "uuid",
        "uuid4",
        "uuid7",
    }
)

# A test whose name or location says it is the composition-root test: stubbing
# every adapter is the point of it.
_SEAM_TOKENS = frozenset(
    {
        "bootstrap",
        "container",
        "containers",
        "di",
        "lifespan",
        "smoke",
        "startup",
        "wiring",
    }
)

# Words inside a name, however it is cased: `MAX_RETRIES`, `RequestTimeout`,
# `test_main_wiring.py` and `TestAppStartup` all have to yield their words.
_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


class OverMockedTest(Rule):
    id: str = "over-mocked-test"
    code: str = "SARJ062"
    description: str = "Test substitutes too many collaborators — it exercises the mock wiring, not the code."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag test functions that substitute more collaborators than the threshold."""
        if not is_test_path(path):
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
                    f"`{node.name}` substitutes {count} collaborators — at that ratio it exercises the "
                    "mock wiring, not the code. Prefer a real dependency (a test database, an in-process "
                    "app, `respx` for HTTP) and mock only the true external boundary."
                ),
            )
            for node, count in _over_mocked_tests(path, tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _over_mocked_tests(
    path: Path, tree: ast.Module, threshold: int = _THRESHOLD
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, int]]:
    """Find the test functions whose substitution count exceeds `threshold`."""
    names = _MockNames.from_tree(tree)
    path_tokens = _seam_path_tokens(path)
    hits: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, int]] = []
    for owner, func in _test_functions(tree):
        if _is_seam_test(func, owner, path_tokens):
            continue
        count = len(_substitutions(func, owner, names))
        if count > threshold:
            hits.append((func, count))
    return hits


def _test_functions(
    tree: ast.Module,
) -> Iterator[tuple[ast.ClassDef | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield the `test*` callables pytest and unittest actually collect."""
    for stmt in tree.body:
        if isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
            yield None, stmt
        elif isinstance(stmt, ast.ClassDef):
            for inner in stmt.body:
                if isinstance(inner, _FUNC_NODES) and inner.name.startswith(_TEST_PREFIX):
                    yield stmt, inner


def _tokens(text: str) -> frozenset[str]:
    return frozenset(word[0].lower() for word in _TOKEN_RE.finditer(text))


# The directory a test suite is rooted at.
_TEST_ROOT_NAMES = frozenset({"t", "test", "tests"})


def _seam_path_tokens(path: Path) -> frozenset[str]:
    """Tokenise the part of `path` that the author chose, not the whole checkout."""
    parts = path.parts
    start = next((i for i, part in enumerate(parts) if part in _TEST_ROOT_NAMES), len(parts) - 1)
    tokens: set[str] = set()
    for part in parts[start:]:
        tokens |= _tokens(part)
    return frozenset(tokens)


def _is_seam_test(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    path_tokens: frozenset[str],
) -> bool:
    own = _tokens(func.name) | path_tokens
    if owner is not None:
        own |= _tokens(owner.name)
    return bool(own & _SEAM_TOKENS)


def _is_infra_target(key: str) -> bool:
    return bool(_tokens(key) & _INFRA_TOKENS)


class _MockNames:
    """The local names through which `unittest.mock` and the imports are reachable."""

    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.symbols: dict[str, str] = {}
        self.qualified: dict[str, str] = {}

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _MockNames:
        """Collect every local binding that resolves to `unittest.mock`, and the import table."""
        found = cls()
        for node in nodes(tree, ast.Import, ast.ImportFrom):
            if isinstance(node, ast.Import):
                found._add_plain_import(node)
            else:
                found._add_from_import(node)
        return found

    def _add_plain_import(self, node: ast.Import) -> None:
        for alias in node.names:
            # `import unittest.mock` binds `unittest`; `import mock` is the backport.
            if alias.name == _MOCK_MODULE:
                self.modules.add(alias.asname or "unittest")
            elif alias.name == _MOCK_BACKPORT:
                self.modules.add(alias.asname or _MOCK_BACKPORT)
            if alias.asname is not None:
                self.qualified[alias.asname] = alias.name

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest":
            for alias in node.names:
                if alias.name == _MOCK_BACKPORT:
                    self.modules.add(alias.asname or _MOCK_BACKPORT)
        elif node.module in {_MOCK_MODULE, _MOCK_BACKPORT}:
            for alias in node.names:
                if alias.name == _PATCH or alias.name in _MOCK_FACTORIES:
                    self.symbols[alias.asname or alias.name] = alias.name
        # A relative import has no absolute path to resolve a bare name onto.
        if node.module is not None and node.level == 0:
            for alias in node.names:
                self.qualified[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def qualify(self, owner: str) -> str:
        """Rewrite a bare-name collaborator to the dotted path it was imported from."""
        head, dot, rest = owner.partition(".")
        full = self.qualified.get(head)
        if full is None:
            return owner
        return f"{full}.{rest}" if dot else full

    def is_mock_module(self, node: ast.expr) -> bool:
        """Report whether `node` names the mock module (or pytest-mock's fixture)."""
        if isinstance(node, ast.Name):
            return node.id in self.modules or node.id == _MOCKER
        # `unittest.mock.patch(...)` — the receiver is itself an attribute chain.
        if isinstance(node, ast.Attribute) and node.attr == _MOCK_BACKPORT:
            return isinstance(node.value, ast.Name) and node.value.id in self.modules
        return False

    def patch_subform(self, func: ast.expr) -> str | None:
        """Map a callee onto the `patch` form it invokes."""
        if isinstance(func, ast.Name):
            return _PATCH if self.symbols.get(func.id) == _PATCH else None
        if not isinstance(func, ast.Attribute):
            return None
        if func.attr in _PATCH_SUBFORMS:
            return func.attr if self._is_patch_ref(func.value) else None
        if func.attr == _PATCH:
            return _PATCH if self.is_mock_module(func.value) else None
        return None

    def _is_patch_ref(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return self.symbols.get(node.id) == _PATCH
        return isinstance(node, ast.Attribute) and node.attr == _PATCH and self.is_mock_module(node.value)

    def factory(self, func: ast.expr) -> str | None:
        """Map a callee onto the mock constructor it invokes."""
        if isinstance(func, ast.Name):
            symbol = self.symbols.get(func.id)
            return symbol if symbol in _MOCK_FACTORIES else None
        if isinstance(func, ast.Attribute) and func.attr in _MOCK_FACTORIES and self.is_mock_module(func.value):
            return func.attr
        return None


class _BodyScan(NamedTuple):
    """One pass over a test body: what it substituted, and how the names are wired."""

    subs: set[tuple[str, str]]
    facets: dict[str, str]


def _substitutions(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    names: _MockNames,
) -> frozenset[str]:
    """Collect the distinct collaborators this test replaces with a double."""
    subs: set[tuple[str, str]] = set()
    injected: list[str | None] = []
    for dec in reversed(func.decorator_list):
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                subs.update(_patch_keys(dec, subform, names))
                injected += _injected_owners(dec, subform, names)
    # A class-level `@patch` is the TestCase's shared fixture, not something
    injected += _class_injected_owners(owner, names)

    scan = _body_substitutions(func, names)
    subs |= scan.subs
    subs.update((name, name) for name in _mock_parameters(func, len(injected)))
    facets = scan.facets | _injected_facets(func, injected)
    return frozenset(names.qualify(_resolve(owning, facets)) for target, owning in subs if not _is_infra_target(target))


def _resolve(name: str, facets: Mapping[str, str]) -> str:
    """Follow the wiring edges from `name` to the object it is a facet of."""
    seen = {name}
    while (nxt := facets.get(name)) is not None and nxt not in seen:
        seen.add(nxt)
        name = nxt
    return name


def _class_injected_owners(owner: ast.ClassDef | None, names: _MockNames) -> list[str | None]:
    if owner is None:
        return []
    injected: list[str | None] = []
    for dec in reversed(owner.decorator_list):
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                injected += _injected_owners(dec, subform, names)
    return injected


def _injected_owners(call: ast.Call, subform: str, names: _MockNames) -> list[str | None]:
    """Say which collaborator each parameter this decorator prepends stands for."""
    if subform in {_PATCH, "object"}:
        if _has_replacement(call, subform):
            return []
        keys = _patch_keys(call, subform, names)
        return [keys[0][1] if len(keys) == 1 else None]
    if subform == "multiple":
        return [None] * len(_replaced_attributes(call))
    return []


def _has_replacement(call: ast.Call, subform: str) -> bool:
    # `patch(target, new)` / `patch.object(target, attr, new)` supply the
    # replacement themselves, so nothing is injected into the signature.
    positional = _PATCH_REPLACEMENT_ARITY if subform == _PATCH else _PATCH_OBJECT_REPLACEMENT_ARITY
    return len(call.args) >= positional or any(kw.arg == "new" for kw in call.keywords)


def _injected_facets(func: ast.FunctionDef | ast.AsyncFunctionDef, injected: list[str | None]) -> dict[str, str]:
    """Alias each `@patch`-injected parameter onto the collaborator it replaced."""
    positional = [
        name for arg in (*func.args.posonlyargs, *func.args.args) if (name := arg.arg) not in _TEST_CASE_RECEIVERS
    ]
    return {param: owning for param, owning in zip(positional, injected, strict=False) if owning is not None}


def _body_substitutions(func: ast.AST, names: _MockNames) -> _BodyScan:
    """Walk a test body once, collecting substitutions and the wiring between them."""
    scan = _BodyScan(subs=set(), facets={})
    for node in walk(func):
        if isinstance(node, ast.Call):
            scan.subs.update(_call_substitutions(node, names))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                scan.subs.update(_binding_keys(target, node.value, names))
            _record_facets(node.targets, node.value, names, scan.facets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            scan.subs.update(_binding_keys(node.target, node.value, names))
            _record_facets([node.target], node.value, names, scan.facets)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            scan.subs.update(_binding_keys(node.optional_vars, node.context_expr, names))
            _record_handle_facet([node.optional_vars], node.context_expr, names, scan.facets)
    return scan


def _record_facets(targets: list[ast.expr], value: ast.expr, names: _MockNames, facets: dict[str, str]) -> None:
    """Note that a name assigned into another object's attribute is part of that object."""
    roots = {root for target in targets if isinstance(target, ast.Attribute) and (root := _object_of(target, names))}
    if roots:
        sources = [*_assigned_names(value), *(t.id for t in targets if isinstance(t, ast.Name))]
        for root in roots:
            for source in sources:
                if source != root:
                    facets.setdefault(source, root)
    _record_handle_facet(targets, value, names, facets)


def _assigned_names(value: ast.expr) -> list[str]:
    """List the names the assigned expression places inside the target's object graph."""
    if isinstance(value, ast.Name):
        return [value.id]
    if isinstance(value, ast.List | ast.Tuple):
        return [elt.id for elt in value.elts if isinstance(elt, ast.Name)]
    if isinstance(value, ast.Call):
        return [
            *(arg.id for arg in value.args if isinstance(arg, ast.Name)),
            *(val.id for kw in value.keywords if isinstance(val := kw.value, ast.Name)),
        ]
    return []


def _record_handle_facet(targets: list[ast.expr], value: ast.expr, names: _MockNames, facets: dict[str, str]) -> None:
    """Note that a `patch(...)` handle names the collaborator that patch replaced."""
    if not isinstance(value, ast.Call):
        return
    subform = names.patch_subform(value.func)
    if subform is None:
        return
    keys = _patch_keys(value, subform, names)
    if len(keys) != 1:
        return
    owning = keys[0][1]
    for target in targets:
        if isinstance(target, ast.Name) and target.id != owning:
            facets.setdefault(target.id, owning)


def _call_substitutions(node: ast.Call, names: _MockNames) -> list[tuple[str, str]]:
    subform = names.patch_subform(node.func)
    if subform is not None:
        return _patch_keys(node, subform, names)
    return _monkeypatch_keys(node, names)


def _binding_keys(target: ast.expr, value: ast.expr, names: _MockNames) -> list[tuple[str, str]]:
    """Key a `x = MagicMock()` binding by the name the double is bound to."""
    if not isinstance(value, ast.Call) or names.factory(value.func) is None:
        return []
    bound = _bound_name(target, names)
    return [(bound, bound)] if bound is not None else []


def _bound_name(target: ast.expr, names: _MockNames) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    # `self.client = MagicMock()` inside a unittest method.
    return _object_of(target, names) if isinstance(target, ast.Attribute) else None


def _object_of(node: ast.expr, names: _MockNames) -> str | None:
    """Name the collaborator an expression reaches into, resolved through imports."""
    root = _collaborator_of(node)
    return None if root is None else names.qualify(root)


def _collaborator_of(node: ast.expr) -> str | None:
    """Name the collaborator an attribute chain reaches into."""
    dotted = _dotted(node)
    if dotted is None:
        return None
    parts = dotted.split(".")
    if parts[0] in _TEST_CASE_RECEIVERS:
        return ".".join(parts[:_TEST_CASE_DEPTH])
    return parts[0]


def _patch_keys(call: ast.Call, subform: str, names: _MockNames) -> list[tuple[str, str]]:
    """Name the collaborator(s) a `patch`-family call replaces."""
    if subform == "dict":
        return []
    if subform in {"object", "multiple"}:
        if not call.args:
            return []
        base, owning = _receiver(call.args[0], names)
        attrs = (
            [_target_text(call.args[1]) if len(call.args) > 1 else _keyword_text(call, "attribute")]
            if subform == "object"
            else _replaced_attributes(call)
        )
        return [(f"{base}.{attr}", owning) for attr in attrs] if attrs else [(base, owning)]
    if not call.args:
        return []
    target = _target_text(call.args[0])
    return [(target, _owner_of(target))]


def _receiver(node: ast.expr, names: _MockNames) -> tuple[str, str]:
    """Render the object a `patch.object` / `monkeypatch.setattr` call targets."""
    text = _target_text(node)
    if isinstance(node, ast.Constant):
        return text, _owner_of(text)
    return text, _object_of(node, names) or text


def _owner_of(target: str) -> str:
    """Reduce a dotted patch target to the object whose attribute is replaced."""
    head, dot, _ = target.rpartition(".")
    return head if dot else target


def _replaced_attributes(call: ast.Call) -> list[str]:
    return [arg for kw in call.keywords if (arg := kw.arg) is not None and arg not in _PATCH_CONFIG_KWARGS]


def _monkeypatch_keys(call: ast.Call, names: _MockNames) -> list[tuple[str, str]]:
    """Name the target of a `monkeypatch.setattr(...)` call."""
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != _MONKEYPATCH_SUBSTITUTION:
        return []
    if not (isinstance(func.value, ast.Name) and func.value.id == _MONKEYPATCH):
        return []
    if not call.args:
        return []
    base, owning = _receiver(call.args[0], names)
    # `monkeypatch.setattr(mod, "attr", value)` vs `setattr("mod.attr", value)`:
    # in the two-argument form the second argument is the replacement, and
    # reading it as an attribute name would key the target off the stub.
    if len(call.args) >= _SETATTR_SPLIT_ARITY:
        return [(f"{base}.{_target_text(call.args[1])}", owning)]
    return [(base, _owner_of(base))]


def _mock_parameters(func: ast.FunctionDef | ast.AsyncFunctionDef, injected: int) -> list[str]:
    """List the mock-shaped fixtures this test asks pytest to build for it."""
    args = func.args
    positional = [name for arg in (*args.posonlyargs, *args.args) if (name := arg.arg) not in _TEST_CASE_RECEIVERS]
    candidates = [*positional[injected:], *(arg.arg for arg in args.kwonlyargs)]
    return [name for name in candidates if _is_mock_fixture(name)]


def _is_mock_fixture(name: str) -> bool:
    # `mocker` itself is pytest-mock's handle, not a collaborator: what it
    # patches is counted at the `mocker.patch(...)` call site.
    return name.startswith("mock_") or name.endswith(("_mock", "_mocks"))


def _target_text(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return _joined_text(node)
    return _dotted(node) or "?"


def _joined_text(node: ast.JoinedStr) -> str:
    """Rebuild an f-string patch target as a dotted name."""
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append(_dotted(value.value) or "?")
    return "".join(parts)


def _keyword_text(call: ast.Call, name: str) -> str:
    for kw in call.keywords:
        if kw.arg == name:
            return _target_text(kw.value)
    return "?"


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))
