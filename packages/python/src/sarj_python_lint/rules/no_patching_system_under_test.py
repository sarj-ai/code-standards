"""SARJ061 — A test that mocks out the unit's own logic verifies the mock, not the unit.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_patching_system_under_test.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ061.md
"""

from __future__ import annotations

import ast
import re
import sys
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MOCK_MODULE = "unittest.mock"
_PATCH = "patch"
_PATCH_OBJECT = "patch.object"
_OBJECT = "object"

# A plain function/method name: snake_case with at most one leading underscore.
# CapWords targets are collaborator *types* being doubled, ALL_CAPS targets are
# config knobs, and dunders are framework hooks — none is the unit's own logic.
_PLAIN_FUNCTION_RE = re.compile(r"^_?[a-z][a-z0-9_]*$")

# Module globals named like this are I/O handles. Replacing one IS the seam.
_BOUNDARY_NAME_RE = re.compile(
    r"(^|_)(client|session|conn|connection|engine|pool|db|api|bus|broker|transport"
    r"|channel|socket|http|requests|redis|s3|bucket|queue|producer|consumer|publisher"
    r"|logger|log|cache|store|repo|repository)s?$",
    re.IGNORECASE,
)

# A `side_effect=` naming one of these installs a mock that raises. That is a
# tripwire or a fault injector, not a stand-in for the real answer.
_EXCEPTION_NAME_RE = re.compile(r"(Error|Exception|Warning|Exit|Interrupt|Timeout|Abort)$")

# Any of these means the author supplied a substitute instead of taking a MagicMock.
_CONCRETE_REPLACEMENT_KEYWORDS = frozenset({"new", "new_callable", "wraps"})

# Positional slot that holds `new` in each signature: `patch(target, new, ...)`,
# `patch.object(target, attribute, new, ...)`.
_REPLACEMENT_ARITY = {_PATCH: 2, _PATCH_OBJECT: 3}

# `patch.object(target, attribute)` — both are needed before there is anything to judge.
_PATCH_OBJECT_MIN_ARGS = 2

_STDLIB_MODULES = frozenset(sys.stdlib_module_names)

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class NoPatchingSystemUnderTest(Rule):
    id: str = "no-patching-system-under-test"
    code: str = "SARJ061"
    has_evidence: bool = True
    description: str = "Test patches a function/method of the unit it exercises — the real code path never runs."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag patches that replace part of the unit the test then exercises."""
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        facts = _ModuleFacts.from_tree(tree)
        if not facts.reaches_mock:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this patches `{target}`, which belongs to the unit this test then exercises, so "
                    "the real code path never runs and the assertions only describe the mock. Adding "
                    "`spec=`/`autospec=` does not address this — the problem is *what* is patched, not "
                    "how faithfully. Patch at the boundary the unit talks to instead, or exercise the "
                    "real method."
                ),
            )
            for node, target in _self_patches(tree, facts)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _ModuleFacts:
    """Whole-file context needed to decide what a patch target belongs to."""

    def __init__(self) -> None:
        self.patch_aliases: set[str] = set()
        self.mock_modules: set[str] = set()
        self.imported_from: dict[str, set[str]] = {}
        self.origin: dict[str, str] = {}
        self.module_aliases: dict[str, str] = {}
        self.local_defs: set[str] = set()
        self.called: set[str] = set()
        self.receivers: set[str] = set()

    @property
    def reaches_mock(self) -> bool:
        """Report whether the file can name `unittest.mock.patch` at all."""
        return bool(self.patch_aliases or self.mock_modules)

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _ModuleFacts:
        """Collect the import, definition and usage tables of one module."""
        found = cls()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found._add_import(node)
            elif isinstance(node, ast.ImportFrom):
                found._add_from_import(node)
            elif isinstance(node, (*_FUNC_NODES, ast.ClassDef)):
                found.local_defs.add(node.name)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                found.called.add(node.func.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                found.receivers.add(node.value.id)
        return found

    def _add_import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == _MOCK_MODULE:
                self.mock_modules.add(alias.asname or "unittest")
            if alias.asname:
                self.module_aliases[alias.asname] = alias.name

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest":
            self.mock_modules.update(a.asname or name for a in node.names if (name := a.name) == "mock")
            return
        if node.module == _MOCK_MODULE:
            self.patch_aliases.update(a.asname or name for a in node.names if (name := a.name) == _PATCH)
            return
        # A relative import cannot be turned into the absolute dotted path a
        # `patch("...")` target string uses, so it is not usable evidence.
        if node.module is None or node.level:
            return
        bound = {a.asname or a.name for a in node.names}
        self.imported_from.setdefault(node.module, set()).update(bound)
        for name in bound:
            self.origin[name] = node.module

    def patcher(self, func: ast.expr) -> str | None:
        """Map a callee onto the `unittest.mock` patcher it invokes."""
        if isinstance(func, ast.Name):
            return _PATCH if func.id in self.patch_aliases else None
        if not isinstance(func, ast.Attribute):
            return None
        if func.attr == _OBJECT:
            return _PATCH_OBJECT if self.patcher(func.value) == _PATCH else None
        if func.attr != _PATCH:
            return None
        return _PATCH if self._is_mock_module(func.value) else None

    def _is_mock_module(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.mock_modules
        # `unittest.mock.patch(...)` — the receiver is itself an attribute chain.
        return isinstance(node, ast.Attribute) and node.attr == "mock" and self._is_mock_module(node.value)

    def is_module_under_test(self, module: str, attr: str, scope: _Scope) -> bool:
        """Report whether `module.attr` is a symbol this file imports and *this function* exercises."""
        names = self.imported_from.get(module)
        if names is None or attr not in names:
            return False
        if (names - {attr}) & scope.calls:
            return True
        return any(self.resolve_module(dotted) == module for dotted in scope.calls_through)

    def resolve_module(self, dotted: str) -> str:
        """Expand a call receiver into the dotted module path it stands for."""
        head, _, rest = dotted.partition(".")
        base = self.module_aliases.get(head)
        if base is None:
            package = self.origin.get(head)
            base = f"{package}.{head}" if package else head
        return f"{base}.{rest}" if rest else base

    def is_module_singleton(self, attr: str) -> bool:
        """Report whether `attr` names an object the file drives rather than a function it calls."""
        return attr in self.receivers and attr not in self.called

    def is_locally_manufactured(self, constructor: str) -> bool:
        """Report whether `constructor` names a class or factory this test file defines."""
        if constructor in self.local_defs:
            return True
        module = self.origin.get(constructor)
        return module is None or module.split(".")[0] in _STDLIB_MODULES


class _Scope:
    """What one function body does with its local names."""

    def __init__(self) -> None:
        self.built_by: dict[str, str] = {}
        self.attr_calls: dict[str, set[str]] = {}
        self.calls: set[str] = set()
        self.calls_through: set[str] = set()

    @classmethod
    def of(cls, func: ast.FunctionDef | ast.AsyncFunctionDef) -> _Scope:
        """Index the constructions and calls inside one function."""
        found = cls()
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                found._bind(node.targets[0], node.value)
            elif isinstance(node, ast.Call):
                found._record_call(node)
        return found

    def _bind(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name) and isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            self.built_by[target.id] = value.func.id

    def _record_call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            self.calls.add(func.id)
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                self.attr_calls.setdefault(func.value.id, set()).add(func.attr)
            receiver = _dotted_name(func.value)
            if receiver is not None:
                self.calls_through.add(receiver)

    def constructor_of(self, name: str) -> str | None:
        """Find the class or factory that produced the object `name` refers to."""
        if name in self.built_by:
            return self.built_by[name]
        return name if name in self.calls else None

    def other_attrs_called_on(self, name: str, patched: str) -> bool:
        """Report whether the function calls some *other* attribute of the patched object."""
        exercised = set(self.attr_calls.get(name, ()))
        for local, constructor in self.built_by.items():
            if constructor == name:
                exercised |= self.attr_calls.get(local, set())
        return bool(exercised - {patched})


def _self_patches(tree: ast.Module, facts: _ModuleFacts) -> list[tuple[ast.Call, str]]:
    hits: list[tuple[ast.Call, str]] = []
    for func in _top_level_functions(tree):
        patches = _patch_calls(func, facts)
        if not patches:
            continue
        # `_Scope` costs a second walk of the body, so it is built only for the
        # minority of functions that actually reach for a patcher.
        scope = _Scope.of(func)
        for node, kind in patches:
            target = (
                _sibling_of_unit_under_test(node, facts, scope)
                if kind == _PATCH
                else _method_of_object_under_test(node, facts, scope)
            )
            if target is not None:
                hits.append((node, target))
    return hits


def _patch_calls(func: ast.FunctionDef | ast.AsyncFunctionDef, facts: _ModuleFacts) -> list[tuple[ast.Call, str]]:
    """Find the `unittest.mock` patcher calls inside one function, decorators included."""
    found: list[tuple[ast.Call, str]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        kind = facts.patcher(node.func)
        if kind is not None:
            found.append((node, kind))
    return found


def _top_level_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the module-level functions and class methods of one module."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    containers: list[ast.Module | ast.ClassDef] = [tree]
    while containers:
        for stmt in containers.pop().body:
            if isinstance(stmt, ast.ClassDef):
                containers.append(stmt)
            elif isinstance(stmt, _FUNC_NODES):
                found.append(stmt)
    return found


def _sibling_of_unit_under_test(node: ast.Call, facts: _ModuleFacts, scope: _Scope) -> str | None:
    """Match shape 1: `patch("<mod>.<attr>")` on a sibling of the symbol being tested."""
    dotted = _string_arg(node.args[0])
    if dotted is None:
        return None
    module, _, attr = dotted.rpartition(".")
    if not _is_own_logic(attr) or facts.is_module_singleton(attr):
        return None
    if _has_concrete_replacement(node, _PATCH, attr) or _raises_instead_of_answering(node):
        return None
    return dotted if facts.is_module_under_test(module, attr, scope) else None


def _method_of_object_under_test(node: ast.Call, facts: _ModuleFacts, scope: _Scope) -> str | None:
    """Match shape 2: `patch.object(X, "m")` on an object this function builds and drives."""
    if len(node.args) < _PATCH_OBJECT_MIN_ARGS or not isinstance(node.args[0], ast.Name):
        return None
    name = node.args[0].id
    attr = _string_arg(node.args[1])
    if attr is None or not _is_own_logic(attr) or _raises_instead_of_answering(node):
        return None
    if _has_concrete_replacement(node, _PATCH_OBJECT, attr, name):
        return None
    constructor = scope.constructor_of(name)
    if constructor is None or facts.is_locally_manufactured(constructor):
        return None
    return f"{constructor}.{attr}" if scope.other_attrs_called_on(name, attr) else None


def _is_own_logic(attr: str) -> bool:
    return bool(_PLAIN_FUNCTION_RE.match(attr)) and not _BOUNDARY_NAME_RE.search(attr)


def _has_concrete_replacement(node: ast.Call, patcher: str, attr: str, receiver: str | None = None) -> bool:
    """Report whether the patch installs an author-written substitute rather than a mock."""
    if any(isinstance(arg, ast.Starred) for arg in node.args) or len(node.args) >= _REPLACEMENT_ARITY[patcher]:
        return True
    return any(
        kw.arg is None
        or kw.arg in _CONCRETE_REPLACEMENT_KEYWORDS
        or (kw.arg == "side_effect" and _delegates_to_real(kw.value, attr, receiver))
        for kw in node.keywords
    )


def _raises_instead_of_answering(node: ast.Call) -> bool:
    """Report whether the patch installs a mock that raises rather than one that answers."""
    return any(kw.arg == "side_effect" and _names_an_exception(kw.value) for kw in node.keywords)


def _names_an_exception(value: ast.expr) -> bool:
    called = value.func if isinstance(value, ast.Call) else value
    name = called.attr if isinstance(called, ast.Attribute) else called.id if isinstance(called, ast.Name) else ""
    return bool(_EXCEPTION_NAME_RE.search(name))


def _delegates_to_real(value: ast.expr, attr: str, receiver: str | None) -> bool:
    # The spy idiom: `side_effect=cursor_iter` alongside
    # `patch("...compiler.cursor_iter")`, or `side_effect=hasher.encode` alongside
    # `patch.object(hasher, "encode")`. Real behaviour is kept; calls are counted.
    if isinstance(value, ast.Name):
        return value.id == attr
    if not isinstance(value, ast.Attribute) or value.attr != attr:
        return False
    return receiver is None or (isinstance(value.value, ast.Name) and value.value.id == receiver)


def _dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _string_arg(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
