from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, Final, Literal, NamedTuple, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path


_THRESHOLD = 5

_MOCK_MODULE = "unittest.mock"
_MOCK_BACKPORT = "mock"

# Constructors that mint a stand-in for a collaborator.
_MOCK_FACTORIES = frozenset(
    {"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock", "create_autospec"}
)

type _PatchSubform = Literal["patch", "object", "multiple", "dict"]

_PATCH: Final = "patch"

# `patch.object` / `patch.multiple` / `patch.dict` — the sub-forms of `patch`.
_PATCH_SUBFORMS: Final[frozenset[_PatchSubform]] = frozenset({"object", "multiple", "dict"})

# `patch.multiple(target, spec=..., a=Mock())`: everything that is NOT one of
# these keywords names an attribute being replaced.
_PATCH_CONFIG_KWARGS = frozenset(
    {"target", "spec", "spec_set", "autospec", "new_callable", "create", "instance", "unsafe"}
)

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

_PYTEST = "pytest"

_PARAMETRIZE = "parametrize"

# `monkeypatch.setenv`/`delenv` are environment, not substitution; `setitem`/
# `delitem` edit a config dict; `syspath_prepend`/`chdir` are process state.
_MONKEYPATCH_SUBSTITUTION = "setattr"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test"

# The receiver of an attribute chain that is the test case rather than a double.
_TEST_CASE_RECEIVERS = frozenset({"self", "cls"})

# `self.client` is a collaborator hung off the test case; `self` alone is not.
_TEST_CASE_DEPTH = 2


class _MockReceiver(NamedTuple):
    target: str
    owner: str


class _SubstitutionKey(NamedTuple):
    target: str
    owner: str


class _OverMockedFunction(NamedTuple):
    function: ast.FunctionDef | ast.AsyncFunctionDef
    substitution_count: int


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

# Documentation suites sometimes execute every published example under one
# deliberately broad boundary harness.  Requiring both tokens distinguishes
# that role from an ordinary docs renderer or an ordinary examples test.
_DOCUMENTATION_HARNESS_TOKENS = frozenset({"docs", "examples"})

# Words inside a name, however it is cased: `MAX_RETRIES`, `RequestTimeout`,
# `test_main_wiring.py` and `TestAppStartup` all have to yield their words.
_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


class OverMockedTest(Rule):
    id: str = "over-mocked-test"
    code: str = "SARJ062"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tests should not use more than five independently rooted test doubles or collaborator substitutions.",
        rationale="Broad double setup obscures the behavior under test and often couples tests to implementation wiring.",
        remediation=(
            "Prefer real in-process dependencies, a component harness, or purpose-built fakes; keep mocks at true "
            "external boundaries."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only maintained, collected tests are analyzed; generated files and nested lexical scopes are excluded.",
            "The warning counts independently rooted doubles and inferred collaborator owners, including mock-named fixtures.",
            (
                "Class-level patches, configuration and process-state knobs, and identified composition-root or "
                "documentation harnesses are excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="six-patched-collaborators",
                title="Test patches six collaborators",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        'from unittest.mock import patch\n\n@patch("shop.inventory.reserve")\n@patch("shop.payments.charge")\n@patch("shop.shipping.quote")\n@patch("shop.tax.calculate")\n@patch("shop.email.send_receipt")\n@patch("shop.risk.approve")\ndef test_checkout(risk, email, tax, shipping, payments, inventory):\n    assert checkout() == "confirmed"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="external-boundary-only",
                title="Component test keeps one external boundary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        'from unittest.mock import patch\n\n@patch("shop.payment_gateway.charge")\ndef test_checkout(gateway, test_database, inventory_service):\n    result = checkout(test_database, inventory_service)\n    assert result.status == "confirmed"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
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
                    f"`{node.name}` uses {count} independently rooted test doubles or substitutions. "
                    "Consider real in-process dependencies, a component harness, or purpose-built fakes, keeping "
                    "mocks at true external boundaries."
                ),
                severity=Severity.WARNING,
            )
            for node, count in _over_mocked_tests(path, tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _over_mocked_tests(path: Path, tree: ast.Module, threshold: int = _THRESHOLD) -> list[_OverMockedFunction]:
    names = _MockNames.from_tree(tree)
    path_tokens = _seam_path_tokens(path)
    hits: list[_OverMockedFunction] = []
    for owner, func in _test_functions(tree):
        if _is_seam_test(func, owner, path_tokens):
            continue
        count = len(_substitutions(func, owner, names))
        if count > threshold:
            hits.append(_OverMockedFunction(func, count))
    return hits


def _test_functions(
    tree: ast.Module,
) -> Iterator[tuple[ast.ClassDef | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for stmt in tree.body:
        if isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
            yield None, stmt
        elif isinstance(stmt, ast.ClassDef):
            for inner in stmt.body:
                if isinstance(inner, _FUNC_NODES) and inner.name.startswith(_TEST_PREFIX):
                    yield stmt, inner


def _tokens(text: str) -> frozenset[str]:
    return frozenset(word[0].lower() for word in _TOKEN_RE.finditer(text))


class _BindingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    @override
    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)


def _bound_names(statements: Iterable[ast.stmt]) -> frozenset[str]:
    visitor = _BindingVisitor()
    for statement in statements:
        visitor.visit(statement)
    return frozenset(visitor.names)


def _parameter_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    args = func.args
    names = {
        *(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)),
        *((args.vararg.arg,) if args.vararg is not None else ()),
        *((args.kwarg.arg,) if args.kwarg is not None else ()),
    }
    return frozenset(names)


# The directory a test suite is rooted at.
_TEST_ROOT_NAMES = frozenset({"t", "test", "tests"})


def _seam_path_tokens(path: Path) -> frozenset[str]:
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
    return bool(own & _SEAM_TOKENS) or own >= _DOCUMENTATION_HARNESS_TOKENS


class _MockNames:
    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.symbols: dict[str, str] = {}
        self.qualified: dict[str, str] = {}
        self.pytest_modules: set[str] = set()
        self.pytest_parametrize: set[str] = set()
        self.fixture_handles: set[str] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _MockNames:
        found = cls()
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                found._add_plain_import(stmt)
            elif isinstance(stmt, ast.ImportFrom):
                found._add_from_import(stmt)
            else:
                found._remove_bound_names(_bound_names((stmt,)))
        return found

    def _add_plain_import(self, node: ast.Import) -> None:
        for alias in node.names:
            # `import unittest.mock` binds `unittest`; `import mock` is the backport.
            if alias.name == _MOCK_MODULE:
                self.modules.add(alias.asname or "unittest")
            elif alias.name == _MOCK_BACKPORT:
                self.modules.add(alias.asname or _MOCK_BACKPORT)
            elif alias.name == _PYTEST:
                self.pytest_modules.add(alias.asname or _PYTEST)
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
        elif node.module == "pytest.mark":
            for alias in node.names:
                if alias.name == _PARAMETRIZE:
                    self.pytest_parametrize.add(alias.asname or alias.name)
        # A relative import has no absolute path to resolve a bare name onto.
        if node.module is not None and node.level == 0:
            for alias in node.names:
                self.qualified[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def _remove_bound_names(self, bound: frozenset[str]) -> None:
        self.modules.difference_update(bound)
        self.pytest_modules.difference_update(bound)
        self.pytest_parametrize.difference_update(bound)
        for name in bound:
            self.symbols.pop(name, None)
            self.qualified.pop(name, None)

    def scoped(
        self,
        blocked: frozenset[str],
        *,
        allow_mocker: bool,
        allow_monkeypatch: bool,
    ) -> _MockNames:
        scoped = _MockNames()
        scoped.modules = self.modules - blocked
        if allow_mocker:
            scoped.modules.add(_MOCKER)
        scoped.symbols = {name: symbol for name, symbol in self.symbols.items() if name not in blocked}
        scoped.qualified = {name: source for name, source in self.qualified.items() if name not in blocked}
        scoped.pytest_modules = self.pytest_modules - blocked
        scoped.pytest_parametrize = self.pytest_parametrize - blocked
        if allow_mocker:
            scoped.fixture_handles.add(_MOCKER)
        if allow_monkeypatch:
            scoped.fixture_handles.add(_MONKEYPATCH)
        return scoped

    def qualify(self, owner: str) -> str:
        head, dot, rest = owner.partition(".")
        full = self.qualified.get(head)
        if full is None:
            return owner
        return f"{full}.{rest}" if dot else full

    def is_mock_module(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.modules
        # `unittest.mock.patch(...)` — the receiver is itself an attribute chain.
        if isinstance(node, ast.Attribute) and node.attr == _MOCK_BACKPORT:
            return isinstance(node.value, ast.Name) and node.value.id in self.modules
        return False

    def patch_subform(self, func: ast.expr) -> _PatchSubform | None:
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
        if isinstance(func, ast.Name):
            symbol = self.symbols.get(func.id)
            return symbol if symbol in _MOCK_FACTORIES else None
        if isinstance(func, ast.Attribute) and func.attr in _MOCK_FACTORIES and self.is_mock_module(func.value):
            return func.attr
        return None

    def is_parametrize(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.pytest_parametrize
        return (
            isinstance(func, ast.Attribute)
            and func.attr == _PARAMETRIZE
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "mark"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id in self.pytest_modules
        )

    def is_fixture_handle(self, node: ast.expr, name: str) -> bool:
        return isinstance(node, ast.Name) and node.id == name and name in self.fixture_handles


class _BodyScan(NamedTuple):
    subs: set[_SubstitutionKey]
    facets: dict[str, str]


def _substitutions(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    names: _MockNames,
) -> frozenset[str]:
    subs: set[_SubstitutionKey] = set()
    injected: list[str | None] = []
    for dec in reversed(func.decorator_list):
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                subs.update(_patch_keys(dec, subform, names))
                injected += _injected_owners(dec, subform, names)
    # Count class-level patch decorators once as shared TestCase fixtures.
    injected += _class_injected_owners(owner, names)

    scan = _body_substitutions(func, names)
    subs |= scan.subs
    parametrized = _parametrized_arguments(func, names)
    subs.update(_SubstitutionKey(name, name) for name in _mock_parameters(func, len(injected), parametrized))
    facets = scan.facets | _injected_facets(func, injected)
    return frozenset(names.qualify(_resolve(owning, facets)) for target, owning in subs if not _is_infra_target(target))


def _is_infra_target(key: str) -> bool:
    return bool(_tokens(key) & _INFRA_TOKENS)


def _resolve(name: str, facets: Mapping[str, str]) -> str:
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


def _injected_owners(call: ast.Call, subform: _PatchSubform, names: _MockNames) -> list[str | None]:
    if subform in {_PATCH, "object"}:
        if _has_replacement(call, subform):
            return []
        keys = _patch_keys(call, subform, names)
        return [keys[0][1] if len(keys) == 1 else None]
    if subform == "multiple":
        return [None] * len(_replaced_attributes(call))
    return []


def _has_replacement(call: ast.Call, subform: _PatchSubform) -> bool:
    # `patch(target, new)` / `patch.object(target, attr, new)` supply the
    # replacement themselves, so nothing is injected into the signature.
    positional = _PATCH_REPLACEMENT_ARITY if subform == _PATCH else _PATCH_OBJECT_REPLACEMENT_ARITY
    return len(call.args) >= positional or any(kw.arg == "new" for kw in call.keywords)


def _injected_facets(func: ast.FunctionDef | ast.AsyncFunctionDef, injected: list[str | None]) -> dict[str, str]:
    positional = [
        name for arg in (*func.args.posonlyargs, *func.args.args) if (name := arg.arg) not in _TEST_CASE_RECEIVERS
    ]
    return {param: owning for param, owning in zip(positional, injected, strict=False) if owning is not None}


def _body_substitutions(func: ast.FunctionDef | ast.AsyncFunctionDef, names: _MockNames) -> _BodyScan:
    local_bindings = _bound_names(func.body)
    parameters = _parameter_names(func)
    scoped_names = names.scoped(
        local_bindings | parameters,
        allow_mocker=_MOCKER in parameters and _MOCKER not in local_bindings,
        allow_monkeypatch=_MONKEYPATCH in parameters and _MONKEYPATCH not in local_bindings,
    )
    scan = _BodyScan(subs=set(), facets={})
    for node in _lexical_body_nodes(func):
        if isinstance(node, ast.Call):
            scan.subs.update(_call_substitutions(node, scoped_names))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                scan.subs.update(_binding_keys(target, node.value, scoped_names))
            _record_facets(node.targets, node.value, scoped_names, scan.facets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            scan.subs.update(_binding_keys(node.target, node.value, scoped_names))
            _record_facets([node.target], node.value, scoped_names, scan.facets)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            scan.subs.update(_binding_keys(node.optional_vars, node.context_expr, scoped_names))
            _record_handle_facet([node.optional_vars], node.context_expr, scoped_names, scan.facets)
    return scan


def _lexical_body_nodes(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(func.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, (*_FUNC_NODES, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _record_facets(targets: list[ast.expr], value: ast.expr, names: _MockNames, facets: dict[str, str]) -> None:
    roots = list(
        dict.fromkeys(
            root for target in targets if isinstance(target, ast.Attribute) and (root := _object_of(target, names))
        )
    )
    if roots:
        sources = [*_assigned_names(value), *(t.id for t in targets if isinstance(t, ast.Name))]
        for root in roots:
            for source in sources:
                if source != root:
                    facets.setdefault(source, root)
    _record_handle_facet(targets, value, names, facets)


def _assigned_names(value: ast.expr) -> list[str]:
    match value:
        case ast.Name(id=name):
            return [name]
        case ast.List() | ast.Tuple():
            return [element.id for element in value.elts if isinstance(element, ast.Name)]
        case ast.Call(args=args, keywords=keywords):
            return [
                *(arg.id for arg in args if isinstance(arg, ast.Name)),
                *(item.id for keyword in keywords if isinstance(item := keyword.value, ast.Name)),
            ]
        case _:
            return []


def _record_handle_facet(targets: list[ast.expr], value: ast.expr, names: _MockNames, facets: dict[str, str]) -> None:
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


def _call_substitutions(node: ast.Call, names: _MockNames) -> list[_SubstitutionKey]:
    subform = names.patch_subform(node.func)
    if subform is not None:
        return _patch_keys(node, subform, names)
    return _monkeypatch_keys(node, names)


def _binding_keys(target: ast.expr, value: ast.expr, names: _MockNames) -> list[_SubstitutionKey]:
    if not isinstance(value, ast.Call) or names.factory(value.func) is None:
        return []
    bound = _bound_name(target, names)
    return [_SubstitutionKey(bound, bound)] if bound is not None else []


def _bound_name(target: ast.expr, names: _MockNames) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    # `self.client = MagicMock()` inside a unittest method.
    return _object_of(target, names) if isinstance(target, ast.Attribute) else None


def _object_of(node: ast.expr, names: _MockNames) -> str | None:
    root = _collaborator_of(node)
    return None if root is None else names.qualify(root)


def _collaborator_of(node: ast.expr) -> str | None:
    dotted = _dotted(node)
    if dotted is None:
        return None
    parts = dotted.split(".")
    if parts[0] in _TEST_CASE_RECEIVERS:
        return ".".join(parts[:_TEST_CASE_DEPTH])
    return parts[0]


def _patch_keys(call: ast.Call, subform: _PatchSubform, names: _MockNames) -> list[_SubstitutionKey]:
    if subform == "dict":
        return []
    if subform in {"object", "multiple"}:
        target = _call_argument(call, 0, "target")
        if target is None:
            return []
        receiver = _receiver(target, names)
        attribute = _call_argument(call, 1, "attribute")
        if subform == "object":
            attrs = [] if attribute is None else [_target_text(attribute)]
        else:
            attrs = _replaced_attributes(call)
        return (
            [_SubstitutionKey(f"{receiver.target}.{attr}", receiver.owner) for attr in attrs]
            if attrs
            else [_SubstitutionKey(receiver.target, receiver.owner)]
        )
    target = _call_argument(call, 0, "target")
    if target is None:
        return []
    target_text = _target_text(target)
    return [_SubstitutionKey(target_text, _owner_of(target_text))]


def _call_argument(call: ast.Call, position: int, name: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _receiver(node: ast.expr, names: _MockNames) -> _MockReceiver:
    text = _target_text(node)
    if isinstance(node, ast.Constant):
        return _MockReceiver(text, _owner_of(text))
    return _MockReceiver(text, _object_of(node, names) or text)


def _owner_of(target: str) -> str:
    head, dot, _ = target.rpartition(".")
    return head if dot else target


def _replaced_attributes(call: ast.Call) -> list[str]:
    return [arg for kw in call.keywords if (arg := kw.arg) is not None and arg not in _PATCH_CONFIG_KWARGS]


def _monkeypatch_keys(call: ast.Call, names: _MockNames) -> list[_SubstitutionKey]:
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != _MONKEYPATCH_SUBSTITUTION:
        return []
    if not names.is_fixture_handle(func.value, _MONKEYPATCH):
        return []
    if not call.args:
        return []
    receiver = _receiver(call.args[0], names)
    # `monkeypatch.setattr(mod, "attr", value)` vs `setattr("mod.attr", value)`:
    # in the two-argument form the second argument is the replacement, and
    # reading it as an attribute name would key the target off the stub.
    if len(call.args) >= _SETATTR_SPLIT_ARITY:
        return [_SubstitutionKey(f"{receiver.target}.{_target_text(call.args[1])}", receiver.owner)]
    return [_SubstitutionKey(receiver.target, _owner_of(receiver.target))]


def _parametrized_arguments(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    names: _MockNames,
) -> frozenset[str]:
    parametrized: set[str] = set()
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call) or not names.is_parametrize(decorator.func):
            continue
        argnames = _call_argument(decorator, 0, "argnames")
        if isinstance(argnames, ast.Constant) and isinstance(argnames.value, str):
            parametrized.update(
                stripped_name for name in argnames.value.split(",") if (stripped_name := name.strip())
            )
        elif isinstance(argnames, (ast.List, ast.Tuple)):
            parametrized.update(
                element.value
                for element in argnames.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    return frozenset(parametrized)


def _mock_parameters(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    injected: int,
    parametrized: frozenset[str],
) -> list[str]:
    args = func.args
    positional = [name for arg in (*args.posonlyargs, *args.args) if (name := arg.arg) not in _TEST_CASE_RECEIVERS]
    candidates = [*positional[injected:], *(arg.arg for arg in args.kwonlyargs)]
    return [name for name in candidates if name not in parametrized and _is_mock_fixture(name)]


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
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append(_dotted(value.value) or "?")
    return "".join(parts)


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
