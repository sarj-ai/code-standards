from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
import tokenize
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit

from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_PROFILE_NAME_COUNT = 5


@dataclass(frozen=True, slots=True)
class _Profile:
    port: ast.ClassDef
    store: ast.ClassDef
    service: ast.ClassDef
    factory: ast.FunctionDef
    test: ast.FunctionDef


def fixes(context: PythonFileContext, diagnostic: Diagnostic) -> list[TextEdit]:
    if (
        diagnostic.code != "SARJ526"
        or context.generated
        or not is_test_path(context.path)
        or is_test_support_path(context.path)
        or context.tree is None
    ):
        return []
    if any(
        part.type == tokenize.COMMENT
        for part in tokenize.generate_tokens(StringIO(context.source, newline="").readline)
    ):
        return []
    profile = _profile(context.tree)
    if profile is None or not _closed_classes(profile) or not _existing_factory(profile):
        return []
    called = _guarded_constructor(profile)
    if called is None or (called.lineno, called.col_offset + 1) != (diagnostic.line, diagnostic.col):
        return []
    if (
        not isinstance(called.func, ast.Name)
        or ast.get_source_segment(context.source, called.func) != profile.store.name
    ):
        return []
    lines = StringIO(context.source, newline="").readlines()
    line = lines[called.func.lineno - 1]
    prefix = line.encode("utf-8")[: called.func.col_offset].decode("utf-8")
    start = sum(map(len, lines[: called.func.lineno - 1])) + len(prefix)
    return [TextEdit(start, start + len(profile.store.name), profile.factory.name)]


def _profile(tree: ast.Module) -> _Profile | None:
    match tree.body:
        case [
            ast.Import(names=[ast.alias(name="pytest", asname=None)]),
            ast.ImportFrom(module="typing", names=[ast.alias(name="Protocol", asname=None)], level=0),
            ast.ClassDef() as port,
            ast.ClassDef() as store,
            ast.ClassDef() as service,
            ast.FunctionDef() as factory,
            ast.FunctionDef() as test,
        ]:
            names = {port.name, store.name, service.name, factory.name, test.name}
            if len(names) != _PROFILE_NAME_COUNT or names & {"pytest", "Protocol", "int", "type"}:
                return None
            if not all(name.isascii() and name.isidentifier() and not name.startswith("__") for name in names):
                return None
            return _Profile(port, store, service, factory, test)
        case _:
            return None


def _plain_function(owner: ast.FunctionDef, arguments: list[str]) -> bool:
    parameters = owner.args
    return (
        not owner.decorator_list
        and not owner.type_params
        and owner.type_comment is None
        and not parameters.posonlyargs
        and not parameters.kwonlyargs
        and parameters.vararg is None
        and parameters.kwarg is None
        and not parameters.defaults
        and not parameters.kw_defaults
        and [argument.arg for argument in parameters.args] == arguments
        and all(argument.annotation is None for argument in parameters.args if argument.arg == "self")
    )


def _returns_int(owner: ast.FunctionDef) -> bool:
    return isinstance(owner.returns, ast.Name) and owner.returns.id == "int"


def _closed_classes(profile: _Profile) -> bool:
    port, store, service = profile.port, profile.store, profile.service
    if not all(_plain_class(owner) for owner in (port, store, service)) or store.bases or service.bases:
        return False
    if len(port.bases) != 1 or not isinstance(port.bases[0], ast.Name) or port.bases[0].id != "Protocol":
        return False
    match port.body, store.body, service.body:
        case [ast.FunctionDef() as abstract], [ast.FunctionDef() as concrete], [
            ast.FunctionDef() as initializer,
            ast.FunctionDef() as reader,
        ]:
            return (
                _port_method(abstract)
                and _store_method(concrete)
                and _service_initializer(initializer, port.name)
                and _service_reader(reader)
            )
        case _:
            return False


def _plain_class(owner: ast.ClassDef) -> bool:
    return not (owner.decorator_list or owner.keywords or owner.type_params)


def _port_method(method: ast.FunctionDef) -> bool:
    match method.body:
        case [ast.Expr(value=ast.Constant(value=value))]:
            return (
                value is Ellipsis
                and method.name == "read"
                and _plain_function(method, ["self"])
                and _returns_int(method)
            )
        case _:
            return False


def _store_method(method: ast.FunctionDef) -> bool:
    match method.body:
        case [ast.Return(value=ast.Constant(value=value))]:
            return (
                type(value) is int
                and method.name == "read"
                and _plain_function(method, ["self"])
                and _returns_int(method)
            )
        case _:
            return False


def _service_initializer(method: ast.FunctionDef, port: str) -> bool:
    if not _plain_function(method, ["self", "store"]) or method.name != "__init__":
        return False
    annotation = method.args.args[1].annotation
    if not isinstance(annotation, ast.Name) or annotation.id != port:
        return False
    match method.body, method.returns:
        case [
            ast.Assign(targets=[ast.Attribute(value=ast.Name(id="self"), attr="store")], value=ast.Name(id="store"))
        ], ast.Constant(value=None):
            return True
        case _:
            return False


def _service_reader(method: ast.FunctionDef) -> bool:
    if method.name != "read" or not _plain_function(method, ["self"]) or not _returns_int(method):
        return False
    match method.body:
        case [
            ast.Return(
                value=ast.Call(
                    func=ast.Attribute(value=ast.Attribute(value=ast.Name(id="self"), attr="store"), attr="read"),
                    args=[],
                    keywords=[],
                )
            )
        ]:
            return True
        case _:
            return False


def _factory_annotation(annotation: ast.expr | None, store: str) -> bool:
    return (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == "type"
        and isinstance(annotation.slice, ast.Name)
        and annotation.slice.id == store
    )


def _existing_factory(profile: _Profile) -> bool:
    factory = profile.factory
    match factory.decorator_list, factory.body:
        case [ast.Attribute(value=ast.Name(id="pytest"), attr="fixture")], [ast.Return(value=ast.Name(id=returned))]:
            # The canonical fixture decorator is the only permitted decoration.
            undecorated = ast.FunctionDef(
                name=factory.name,
                args=factory.args,
                body=factory.body,
                decorator_list=[],
                returns=factory.returns,
                type_comment=factory.type_comment,
                type_params=factory.type_params,
            )
            return (
                not factory.name.startswith("test_")
                and returned == profile.store.name
                and _plain_function(undecorated, [])
                and _factory_annotation(factory.returns, profile.store.name)
            )
        case _:
            return False


def _guarded_constructor(profile: _Profile) -> ast.Call | None:
    test = profile.test
    if not test.name.startswith("test_") or not _plain_function(test, [profile.factory.name]):
        return None
    if not _factory_annotation(test.args.args[0].annotation, profile.store.name):
        return None
    if not isinstance(test.returns, ast.Constant) or test.returns.value is not None:
        return None
    match test.body:
        case [
            ast.If(
                test=ast.Compare(left=ast.Name(id=factory), ops=[ast.Is()], comparators=[ast.Name(id=store)]),
                body=body,
                orelse=[],
            )
        ]:
            if factory != profile.factory.name or store != profile.store.name:
                return None
            return _first_constructor(body, profile)
        case _:
            return None


def _first_constructor(statements: list[ast.stmt], profile: _Profile) -> ast.Call | None:
    match statements:
        case [
            ast.Assign(
                targets=[ast.Name(id=receiver)],
                value=ast.Call(
                    func=ast.Name(id=service),
                    args=[ast.Call(func=ast.Name(id=store), args=[], keywords=[]) as called],
                    keywords=[],
                ),
            ),
            ast.Assert(
                test=ast.Compare(
                    left=ast.Call(func=ast.Attribute(value=ast.Name(id=observed), attr="read"), args=[], keywords=[]),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value=expected)],
                ),
                msg=None,
            ),
        ]:
            if receiver in {profile.factory.name, profile.store.name, profile.service.name, profile.port.name}:
                return None
            if (
                service == profile.service.name
                and store == profile.store.name
                and receiver == observed
                and type(expected) is int
            ):
                return called
        case _:
            return None
    return None
