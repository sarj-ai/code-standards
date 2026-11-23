from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._sdk_prerequisite import sdk_prerequisite_diagnostics


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_TYPING = frozenset({"typing", "typing_extensions"})
_BUILTIN_VALUES = frozenset(
    {
        "bool",
        "int",
        "float",
        "complex",
        "str",
        "bytes",
        "bytearray",
        "memoryview",
        "object",
        "list",
        "dict",
        "set",
        "frozenset",
        "tuple",
        "range",
    }
)
_VALUE_TYPES = frozenset(
    {f"builtins.{name}" for name in _BUILTIN_VALUES}
    | {
        f"{module}.{name}"
        for module in _TYPING
        for name in ("Any", "Literal", "List", "Dict", "Set", "FrozenSet", "Tuple")
    }
    | {
        f"{module}.{name}"
        for module in (*_TYPING, "collections.abc")
        for name in (
            "Collection",
            "Container",
            "Iterable",
            "Iterator",
            "Mapping",
            "MutableMapping",
            "Sequence",
            "MutableSequence",
            "Set",
            "MutableSet",
        )
    }
)
_MAX_ANNOTATION_MEMBERS = 64
_MESSAGE_AND_RAISE = 2
_OPTIONAL_TYPES = frozenset(f"{module}.Optional" for module in _TYPING)
_UNION_TYPES = frozenset(f"{module}.Union" for module in _TYPING)
_ANNOTATED_TYPES = frozenset(f"{module}.Annotated" for module in _TYPING)
_OVERLOAD_TYPES = frozenset(f"{module}.overload" for module in _TYPING)


@final
class PreferRequiredPrerequisite(ProjectRule):
    id = "prefer-required-prerequisite"
    code = "SARJ584"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Require complete SDK dependencies and review nullable execution prerequisites.",
        rationale=(
            "A nullable object parameter admits calls that can fail later with ValueError when an execution path "
            "needs the object. A stored nullable SDK client or partial finite-provider registry similarly admits "
            "missing dependencies that an operation rejects. Reviewing that relationship can move prerequisites into a callable or variant "
            "contract that typed callers can check. A successful omission path can still be intentional."
        ),
        remediation=(
            "Review a non-null execution helper, a required parameter when every call needs it, or overloads "
            "and typed variants using an existing discriminator. Preserve valid omission paths, side-effect "
            "order, falsy-object constraints, runtime validation and public compatibility. A non-null annotation "
            "does not validate untyped callers. Keep an explained exact-code exception for intentional boundaries "
            "or conditional protocols; splitting a helper alone may leave the wrapper's warning."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "A proven SDK dependency rejected by a method is an error: a simple constructor stores an optional "
                "import-proven OpenAI/httpx/httpx2 client or copies a finite Enum/Literal-keyed client mapping, and an "
                "operation immediately raises on an absent client before calling it. Require named clients or a "
                "complete typed variant at construction. This does not prove that all entries of an arbitrary dict exist."
            ),
            (
                "The SDK branch abstains for constructor validation, registry mutation or escape, decorators, opaque "
                "SDK types, open-ended keys, and conditional or complex guards. Required non-null client annotations "
                "remain valid. Preserve meaningful absence/fallback and external input validation."
            ),
            (
                "This warning requests architectural review; a match is not proof of an invalid signature or trusted "
                "internal callers. Undecorated boundary conversions, public compatibility and lazy/idempotent protocols "
                "can match and legitimately retain their nullable contract with an explained local exception."
            ),
            (
                "Checks undecorated module-level sync/async functions with explicit outer nullable object annotations "
                "and unchanged parameters. Direct top-level is-None or truthiness rejection must raise the unshadowed "
                "builtin ValueError, optionally after one simple message assignment. Prior successful returns remain "
                "eligible unless an earlier direct absence guard already terminates that parameter's None path: "
                "the requirement belongs to this path, not necessarily every invocation. Truthiness also "
                "rejects non-None falsy objects; never delete those constraints merely by narrowing an annotation."
            ),
            (
                "The module-level warning excludes known primitive, raw object and container annotations, pure direct narrowing adapters, methods, "
                "constructors, decorators, overload groups, generic/variadic functions, observed local non-call "
                "references, non-None defaults, rebound parameters, complex predicates and rejection bodies abstain. "
                "No absence of observed escapes proves that all callers are typed or internal."
            ),
            (
                "PEP 604, import-proven Optional/Union/Annotated, quoted annotations and stable explicit local type "
                "aliases share existing source facts with a fixed work budget. Imported aliases and opaque nominal "
                "types are not expanded; an opaque name may itself represent a primitive value. Ambiguous binding, "
                "dynamic namespaces, shadowed builtin errors, malformed/generated/test/stub files abstain. Aliased "
                "exception constructors, nested guards and cross-module caller contracts are not inferred."
            ),
        ),
        examples=(
            RuleExample(
                example_id="conditional-prerequisite",
                title="Review the execution contract while preserving a valid skip path",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "async def execute(service: Service | None = None, *, skip: bool = False):\n"
                        "    if skip:\n        return\n"
                        "    if not service:\n        msg = 'service required for execution'\n"
                        "        raise ValueError(msg)\n    await service.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="non-null-execution",
                title="An execution helper declares its required object",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "async def execute(service: Service):\n    await service.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="nullable-sdk",
                scenario="sdk-dependency",
                title="A nullable SDK field defers a required construction choice",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/send.py",
                        "from openai import AsyncOpenAI\n"
                        "class Sender:\n    def __init__(self, endpoint: AsyncOpenAI | None):\n"
                        "        self._endpoint = endpoint\n"
                        "    async def send(self):\n        if self._endpoint is None:\n"
                        "            raise RuntimeError('endpoint required')\n"
                        "        return await self._endpoint.get('/ready', cast_to=str)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="required-sdk",
                scenario="sdk-dependency",
                title="The SDK client is required at construction",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/send.py",
                        "from openai import AsyncOpenAI\n"
                        "class Sender:\n    def __init__(self, endpoint: AsyncOpenAI):\n"
                        "        self._endpoint = endpoint\n"
                        "    async def send(self):\n        return await self._endpoint.get('/ready', cast_to=str)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/send.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="narrowing-boundary",
                title="A boundary narrows a nullable input and returns the checked object",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "def require_service(value: Service | None) -> Service:\n"
                        "    if value is None:\n        raise ValueError('missing service')\n"
                        "    return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or _excluded_source(context):
            return []
        facts = AnnotationOrigins(context)
        provenance = facts.provenance
        if provenance.wildcard or provenance.dynamic_namespace or not provenance.builtin_namespace_untouched:
            return []
        functions = [node for node in context.tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
        overloaded = _overloaded_names(functions, facts)
        findings = [
            finding
            for function in functions
            if "ValueError" not in provenance.bindings.get(context.tree, {})
            and "ValueError" not in provenance.external_bindings
            if function.name not in overloaded
            for finding in _function_diagnostics(function, facts, self.code)
        ]
        return [*findings, *sdk_prerequisite_diagnostics(facts, self.code)]


def _excluded_source(context: PythonFileContext) -> bool:
    return (
        context.generated
        or context.path.suffix == ".pyi"
        or is_test_path(context.path)
        or is_test_support_path(context.path)
        or "raise" not in context.symbol_source
    )


def _overloaded_names(functions: list[ast.FunctionDef | ast.AsyncFunctionDef], facts: AnnotationOrigins) -> set[str]:
    return {
        function.name
        for function in functions
        if any(facts.qualified(decorator, decorator) in _OVERLOAD_TYPES for decorator in function.decorator_list)
    }


def _function_diagnostics(
    function: ast.FunctionDef | ast.AsyncFunctionDef, facts: AnnotationOrigins, code: str
) -> list[Diagnostic]:
    if function.decorator_list or function.type_params or function.args.vararg or function.args.kwarg:
        return []
    if facts.provenance.bindings.get(facts.context.tree, {}).get(function.name) != (function,):
        return []
    if "ValueError" in facts.provenance.bindings.get(function, {}) or _observed_escape(function, facts):
        return []
    guards = _candidate_guards(function, facts)
    if not guards or _narrowing_adapter(function, facts):
        return []
    parameters = _nullable_parameters(function, facts)
    context = facts.context
    reported: set[str] = set()
    findings: list[Diagnostic] = []
    for parameter in guards:
        if parameter.id not in parameters or parameter.id in reported:
            continue
        if context.suppressions.is_suppressed(parameter.lineno, code):
            continue
        reported.add(parameter.id)
        findings.append(_diagnostic(parameter, context, code))
    return findings


def _nullable_parameters(function: ast.FunctionDef | ast.AsyncFunctionDef, facts: AnnotationOrigins) -> set[str]:
    excluded = _non_none_defaults(function.args) | facts.provenance.external_bindings
    bindings = facts.provenance.bindings.get(function, {})
    return {
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if argument.arg not in excluded
        and bindings.get(argument.arg) == (argument,)
        and argument.annotation is not None
        and _nullable_object(argument.annotation, facts)
    }


def _diagnostic(parameter: ast.Name, context: PythonFileContext, code: str) -> Diagnostic:
    truthiness = isinstance(context.parents.get(parameter), ast.UnaryOp)
    message = (
        f"Nullable parameter '{parameter.id}' is rejected with ValueError on this path; "
        "review a non-null execution contract or valid parameter combinations, preserving "
        "legitimate omission and boundary validation."
    )
    if truthiness:
        message += " This truthiness guard also rejects other falsy objects."
    return Diagnostic(
        path=context.path,
        line=parameter.lineno,
        col=parameter.col_offset + 1,
        code=code,
        message=message,
        severity=Severity.WARNING,
    )


def _nullable_object(annotation: ast.expr, facts: AnnotationOrigins) -> bool:
    pending = [(annotation, annotation)]
    nullable = False
    objects = 0
    for _ in range(_MAX_ANNOTATION_MEMBERS):
        if not pending:
            return nullable and objects > 0
        node, at = pending.pop()
        resolved = facts.resolve_annotation(node, at=at)
        if resolved is None:
            return False
        node, at = resolved.expression, resolved.at
        if isinstance(node, ast.Constant) and node.value is None:
            nullable = True
            continue
        children = _annotation_children(node, at, facts)
        if children is not None:
            if not children:
                return False
            pending.extend((child, at) for child in children)
            continue
        if not _object_type(node, at, facts):
            return False
        objects += 1
    return False


def _annotation_children(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [node.left, node.right]
    if not isinstance(node, ast.Subscript):
        return None
    qualified = facts.qualified(node.value, at)
    members = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
    if qualified in _OPTIONAL_TYPES:
        return [ast.Constant(value=None), members[0]] if len(members) == 1 else []
    if qualified in _UNION_TYPES:
        return members
    if qualified in _ANNOTATED_TYPES:
        return members[:1] if len(members) > 1 else []
    return None


def _object_type(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> bool:
    target = node.value if isinstance(node, ast.Subscript) else node
    if not isinstance(target, ast.Name | ast.Attribute) or facts.qualified(target, at) in _VALUE_TYPES:
        return False
    return not (isinstance(target, ast.Name) and target.id in _BUILTIN_VALUES and facts.builtin(target, target.id, at))


def _rejection(statement: ast.stmt, facts: AnnotationOrigins) -> ast.Name | None:
    if not isinstance(statement, ast.If) or statement.orelse or not _raises_value_error(statement.body, facts):
        return None
    return _absence_parameter(statement.test)


def _candidate_guards(function: ast.FunctionDef | ast.AsyncFunctionDef, facts: AnnotationOrigins) -> list[ast.Name]:
    present: set[str] = set()
    guards: list[ast.Name] = []
    for statement in function.body:
        if isinstance(statement, ast.Return | ast.Raise):
            break
        parameter = _rejection(statement, facts)
        if parameter is not None and parameter.id not in present:
            guards.append(parameter)
        if not isinstance(statement, ast.If) or not isinstance(statement.body[-1], ast.Return | ast.Raise):
            continue
        rejected = _absence_parameter(statement.test)
        if rejected is not None:
            present.add(rejected.id)
    return guards


def _absence_parameter(test: ast.expr) -> ast.Name | None:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
        return test.operand
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return None
    if not isinstance(test.ops[0], ast.Is):
        return None
    left, right = test.left, test.comparators[0]
    if isinstance(left, ast.Name) and isinstance(right, ast.Constant) and right.value is None:
        return left
    if isinstance(right, ast.Name) and isinstance(left, ast.Constant) and left.value is None:
        return right
    return None


def _raises_value_error(body: list[ast.stmt], facts: AnnotationOrigins) -> bool:
    if len(body) == _MESSAGE_AND_RAISE:
        assignment = body[0]
        if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1:
            return False
        if not isinstance(assignment.targets[0], ast.Name):
            return False
    elif len(body) != 1:
        return False
    last = body[-1]
    if not isinstance(last, ast.Raise) or last.cause is not None:
        return False
    error = last.exc
    return (
        isinstance(error, ast.Call)
        and len(error.args) == 1
        and not error.keywords
        and not isinstance(error.args[0], ast.Starred)
        and facts.builtin(error.func, "ValueError", error)
    )


def _non_none_defaults(arguments: ast.arguments) -> set[str]:
    positional = (*arguments.posonlyargs, *arguments.args)
    defaulted = positional[-len(arguments.defaults) :] if arguments.defaults else ()
    return {
        argument.arg
        for argument, default in (
            *zip(defaulted, arguments.defaults, strict=True),
            *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True),
        )
        if default is not None and not (isinstance(default, ast.Constant) and default.value is None)
    }


def _observed_escape(function: ast.FunctionDef | ast.AsyncFunctionDef, facts: AnnotationOrigins) -> bool:
    return any(
        not (isinstance(parent := facts.context.parents.get(read), ast.Call) and parent.func is read)
        for read in facts.provenance.reads.get(function.name, ())
        if facts.provenance.binding(read.id, read) is function or isinstance(facts.provenance.scope(read), ast.ClassDef)
    )


def _narrowing_adapter(function: ast.FunctionDef | ast.AsyncFunctionDef, facts: AnnotationOrigins) -> bool:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    last = body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Name):
        return False
    result = last.value.id
    return all(
        (parameter := _rejection(statement, facts)) is not None and parameter.id == result for statement in body[:-1]
    )
