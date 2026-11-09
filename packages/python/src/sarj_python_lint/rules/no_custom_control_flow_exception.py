from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_BUILTIN_BASES = frozenset({"Exception", "ValueError"})
_VALIDATOR_DECORATORS = frozenset(
    {
        "pydantic.field_validator",
        "pydantic.model_validator",
        "pydantic.validator",
        "pydantic.root_validator",
        "pydantic.functional_validators.field_validator",
        "pydantic.functional_validators.model_validator",
        "pydantic.v1.validator",
        "pydantic.v1.root_validator",
        "pydantic.class_validators.validator",
        "pydantic.class_validators.root_validator",
        "pydantic.deprecated.class_validators.validator",
        "pydantic.deprecated.class_validators.root_validator",
        "pydantic.v1.class_validators.validator",
        "pydantic.v1.class_validators.root_validator",
    }
)
_FUNCTIONAL_VALIDATORS = frozenset(
    f"{module}.{name}"
    for module in ("pydantic", "pydantic.functional_validators")
    for name in ("AfterValidator", "BeforeValidator", "PlainValidator", "WrapValidator")
)
_MAX_VALIDATOR_DEPTH = 32
_MAX_BASE_DEPTH = 8
_MAX_IMPORTED_MODULES = 32
_MAX_MESSAGE_DEPTH = 16
_RESULT_TYPES = """from typing import Annotated, Literal
from pydantic import BaseModel, Field
class Success[T](BaseModel):
    kind: Literal['success'] = 'success'
    value: T
class Error[E](BaseModel):
    kind: Literal['error'] = 'error'
    error: E
type Result[T, E] = Annotated[Success[T] | Error[E], Field(discriminator='kind')]
"""
_DENIED_SERVICE = """from typing import Literal, assert_never
from pydantic import BaseModel, TypeAdapter
from app.outcomes import Error, Result, Success
class Denied(BaseModel):
    code: Literal['denied'] = 'denied'
    name: str
def save(name: str, allowed: bool) -> Result[str, Denied]:
    return Success[str](value=name) if allowed else Error[Denied](error=Denied(name=name))
def format_result(result: Result[str, Denied]) -> str:
    if result.kind == 'success':
        return result.value
    if result.kind == 'error':
        return f'Denied {result.error.name}'
    assert_never(result)
codec = TypeAdapter[Result[str, Denied]](Result[str, Denied])
def decode_result(data: str) -> Result[str, Denied]:
    return codec.validate_json(data, strict=True)
"""


@final
class NoCustomControlFlowException(Rule):
    id = "no-custom-control-flow-exception"
    code = "SARJ542"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return coded typed outcomes for expected domain failures instead of exception-only contracts.",
        rationale=(
            "A marker, fixed-message or payload-bearing custom exception creates another control-flow type without declaring failure data in "
            "the function's return contract. Expected domain outcomes can often use tagged result variants "
            "that callers handle explicitly. A caller may need error identifiers for an access check before "
            "reporting a rejected record; preserve that handling context. Exceptional failures and framework "
            "rejection still need exceptions."
        ),
        remediation=(
            "Review direct raises of this exception. If the condition is an expected domain outcome, reuse an established Result[T, E] "
            "or a generic Success[T] | Error[E] union with a shared Literal discriminator, a stable domain error code and the handling context. "
            "Update callers to handle, propagate or translate each relevant variant; use the native type checker's assert_never "
            "for exhaustiveness. Extend an existing outcome union rather than wrapping it again. "
            "For a serializable contract, wrap the successful payload too; avoid a raw scalar | Error union. "
            "Use the project's established codec and validate incoming tags and payloads; Pydantic models with an Annotated "
            "Field(discriminator=...) union and TypeAdapter are one option. Format the message at the consumer. Preserve true exceptional failures, "
            "validation rejection, transport/framework protocols, cancellation, unwinding and useful cause context. "
            "A class name or a raise does not prove the condition is expected."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This review warning checks stable module-level Exception/ValueError markers and fixed-message subclasses with a source-visible direct raise. It also reviews typed payload constructors limited to assignments and super().__init__ argument formatting, when raised by a simple rejection guard in an explicitly annotated function. Constructor parameters must be typed and nonvariadic, with at least one used; calls must supply their required arguments. Base ancestry must be source-proven; an opaque external base is not inferred from its name or message.",
            "Payload guards can prepare one literal or simple formatted message before raising. Guards under try/except/finally, with, loops and match are excluded, as are generators, decorated or special-method functions, quoted return annotations and import-proven NoReturn/Never functions, including simple nongeneric module aliases. Constructor calls, arbitrary computations, extra methods or behavior, decorated/generic constructors and unknown argument expansion abstain. Source-visible formatting is not a purity proof and never authorizes an automatic rewrite.",
            "Direct module-level from-imports, including renamed and relative imports, are followed to stable first-party exception definitions using the existing bounded local-source resolver. An imported raise must be a simple guard in an explicitly annotated ordinary function, with source-proven Exception/ValueError ancestry and compatible constructor arguments. Import-proven typing.final/typing_extensions.final class decorators preserve this proof. The rule reports once per function and originating exception, at an unsuppressed raise. Source-definition suppressions are also respected.",
            "Imported discovery does not follow re-exports, module-attribute raises, local imports, aliases, unknown or inherited constructors, custom allocation or inherited subclass hooks (including assigned bindings), external source, generated/test/vendor definitions, registrations or namespace mutations. Source ancestry is bounded to eight classes and imported definition modules to 32 per file. A guarded raise is evidence to review, not proof of business expectedness. Preserve genuine infrastructure failure contracts even when a warning matches. Never convert a transaction rejection to a return without reviewing rollback, cleanup, logging, retries and side-effect order. Optional absence and independent outcomes remain valid.",
            "Raising a ValueError-derived marker from an import-proven Pydantic field/model validator or legacy validator preserves that rejection protocol. Direct synchronous module callbacks used only as Annotated validator metadata on plain direct BaseModel fields, and stable nonescaping direct nested helpers, also preserve rejection; lexical helper ownership is bounded to 32 levels. Unknown external bases and visible mutations or escapes of the class or a local base to registrations, callbacks or other value consumers abstain; HTTPException and other framework-required exception types remain valid.",
            "Expectedness is not inferred from a name, message or prefix. Genuine exceptional markers may also match and require review rather than conversion. Cross-module callers and registrations, indirect raises, dynamically mutated namespaces and class aliases are not inferred. Only simple stable module assignment aliases and nongeneric annotation aliases consumed directly by model fields are followed. Explicit string annotations, custom model hooks, async/generator callbacks, escaped helpers and broader call graphs are not followed. Generic lexical resolution can miss a module marker shadowed only in a method's class namespace.",
            "Tests, generated and vendor code are excluded. No automatic rewrite is safe: a result return must preserve failure handling and transaction/resource unwinding. SARJ435 separately reviews joined-string reason identities.",
            "The examples illustrate an existing project Result abstraction; do not introduce another Result library or require these class/tag names. SARJ510 owns explicit data discriminators and SARJ548 reviews discarded tagged outcomes; the native type checker owns exhaustive handling. A tag alone cannot guarantee JSON support for arbitrary T/E: qualify the concrete payloads with their codec. Keep established wire discriminators, legitimate absence and independent outcomes. This warning does not mechanically ban scalar unions or require every function to return Result.",
        ),
        examples=(
            RuleExample(
                example_id="empty-domain-exception",
                title="A local marker hides a domain outcome outside the return contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "class UnsupportedContent(ValueError):\n    pass\n"
                        "def read_content(known: bool) -> str:\n"
                        "    if not known:\n        raise UnsupportedContent('Unsupported content')\n    return 'content'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="tagged-domain-result",
                title="The return contract represents the expected unsupported outcome",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "from dataclasses import dataclass\nfrom typing import Literal\n"
                        "@dataclass(frozen=True)\nclass Content:\n    value: str\n    kind: Literal['content'] = 'content'\n"
                        "@dataclass(frozen=True)\nclass Unsupported:\n    kind: Literal['unsupported'] = 'unsupported'\n"
                        "def read_content(known: bool) -> Content | Unsupported:\n"
                        "    return Content('content') if known else Unsupported()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="typed-context-hidden-in-exception",
                scenario="typed-payload",
                title="A guarded rejection hides typed context in its exception contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "class Denied(Exception):\n"
                        "    def __init__(self, name: str) -> None:\n"
                        "        self.name = name\n"
                        "        super().__init__(f'Denied {name}')\n"
                        "def load(name: str, allowed: bool) -> str:\n"
                        "    if not allowed:\n        raise Denied(name)\n    return name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="code-context-and-consumer-formatting",
                scenario="typed-payload",
                title="A typed outcome retains the code and formatting context",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/outcomes.py", _RESULT_TYPES),
                    ExampleFile.python("app/content.py", _DENIED_SERVICE.replace("def save(", "def load(")),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="imported-rejection-contract",
                scenario="imported-outcome",
                title="An imported rejection is absent from the successful return contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/errors.py", "class Rejected(Exception):\n    pass\n"),
                    ExampleFile.python(
                        "app/service.py",
                        "from app.errors import Rejected\n"
                        "def save(name: str, allowed: bool) -> str:\n"
                        "    if not allowed:\n        raise Rejected(f'Denied {name}')\n    return name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="generic-success-failure-union",
                scenario="imported-outcome",
                title="An established tagged generic union supports explicit handling and JSON decoding",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/outcomes.py", _RESULT_TYPES),
                    ExampleFile.python("app/service.py", _DENIED_SERVICE),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="guard-prepares-a-message",
                scenario="prepared-message",
                title="A local message variable still hides a typed rejection",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Denied(Exception):\n"
                        "    def __init__(self, detail: str) -> None:\n        self.detail = detail\n"
                        "        super().__init__(detail)\n"
                        "def save(name: str, allowed: bool) -> str:\n"
                        "    if not allowed:\n        message = f'Denied {name}'\n"
                        "        raise Denied(message)\n    return name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-domain-outcome-union",
                scenario="prepared-message",
                title="Both success and rejection carry a stable discriminator",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/outcomes.py", _RESULT_TYPES),
                    ExampleFile.python("app/service.py", _DENIED_SERVICE),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="final-imported-payload",
                scenario="final-payload",
                title="A final imported exception can still hide an expected outcome",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from typing import final\n@final\nclass Missing(Exception):\n"
                        "    def __init__(self, record_id: str) -> None:\n"
                        "        self.record_id = record_id\n        super().__init__(f'Missing {record_id}')\n",
                    ),
                    ExampleFile.python(
                        "app/service.py",
                        "from app.errors import Missing\n"
                        "def load(record_id: str, exists: bool) -> str:\n"
                        "    if not exists:\n        raise Missing(record_id)\n    return record_id\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="finite-contextual-missing-outcome",
                scenario="final-payload",
                title="The error variant retains the identifier needed by its caller",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/outcomes.py", _RESULT_TYPES),
                    ExampleFile.python(
                        "app/service.py",
                        _DENIED_SERVICE.replace("Denied", "Missing")
                        .replace("denied", "missing")
                        .replace("name", "record_id")
                        .replace("allowed", "exists")
                        .replace("def save(", "def load("),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="imported-validator-rejection",
                scenario="validator-boundary",
                title="A validator keeps its native exception rejection protocol",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/errors.py", "class Rejected(ValueError):\n    pass\n"),
                    ExampleFile.python(
                        "app/model.py",
                        "from pydantic import BaseModel, field_validator\nfrom app.errors import Rejected\n"
                        "class Model(BaseModel):\n    name: str\n"
                        "    @field_validator('name')\n    @classmethod\n"
                        "    def validate_name(cls, value: str) -> str:\n"
                        "        if not value:\n            raise Rejected('name required')\n        return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/model.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="protected-transaction-rejection",
                scenario="resource-boundary",
                title="A rejection under a resource protocol needs separate migration review",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/errors.py", "class Rejected(Exception):\n    pass\n"),
                    ExampleFile.python(
                        "app/service.py",
                        "from collections.abc import Generator\nfrom contextlib import contextmanager\n"
                        "from app.errors import Rejected\n"
                        "@contextmanager\ndef transaction() -> Generator[None]:\n    yield None\n"
                        "def save(name: str, allowed: bool) -> str:\n"
                        "    with transaction():\n        if not allowed:\n            raise Rejected(name)\n"
                        "    return name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="ordinary-value-error-guard",
                scenario="validator-boundary",
                title="An ordinary guard has no validator rejection protocol",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/errors.py", "class Rejected(ValueError):\n    pass\n"),
                    ExampleFile.python(
                        "app/service.py",
                        "from app.errors import Rejected\n"
                        "def save(value: str) -> str:\n"
                        "    if not value:\n        raise Rejected('name required')\n    return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guard-after-resource-exit",
                scenario="resource-boundary",
                title="A rejection after resource exit has an ordinary return contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/errors.py", "class Rejected(Exception):\n    pass\n"),
                    ExampleFile.python(
                        "app/service.py",
                        "from collections.abc import Generator\nfrom contextlib import contextmanager\n"
                        "from app.errors import Rejected\n"
                        "@contextmanager\ndef transaction() -> Generator[None]:\n    yield None\n"
                        "def save(name: str, allowed: bool) -> str:\n"
                        "    with transaction():\n        pass\n"
                        "    if not allowed:\n        raise Rejected(name)\n    return name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        if not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts):
            return []
        provenance = context.static_resource_provenance
        if (
            provenance.wildcard
            or provenance.dynamic_namespace
            or (not provenance.builtin_namespace_untouched and not _builtin_namespace_safe(context))
        ):
            return []
        contexts = {context.path: context}
        markers = _markers(context, provenance, contexts)
        raised_markers = _direct_raises(markers, context, provenance)
        findings: list[Diagnostic] = []
        for marker in markers.values():
            if marker not in raised_markers:
                continue
            if context.suppressions.is_suppressed(marker.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    marker.lineno,
                    marker.col_offset + 1,
                    self.code,
                    f"Review `{marker.name}`: its identity, message or typed context is communicated only through an exception. "
                    "If this is an expected domain outcome, return a typed tagged result with a stable error code and the required context, and "
                    "format the message at the consumer; preserve exceptional failures, validation, framework contracts "
                    "and transaction/resource unwinding.",
                    severity=Severity.WARNING,
                )
            )
        for raised, marker in _imported_raises(context, contexts):
            if context.suppressions.is_suppressed(raised.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    raised.lineno,
                    raised.col_offset + 1,
                    self.code,
                    f"Review the return contract for imported `{marker.name}`: this guard communicates rejection only through an exception. "
                    "If this is an expected domain outcome, return a typed tagged success/failure union with a stable error code "
                    "and the required context; update callers to handle, propagate or translate each variant and format messages "
                    "at the consumer. Preserve public adapters, cancellation and transaction/resource unwinding.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _markers(
    context: PythonFileContext, provenance: ResourceProvenance, contexts: dict[Path, PythonFileContext]
) -> dict[str, ast.ClassDef]:
    if (
        context.tree is None
        or context.generated
        or is_test_path(context.path)
        or not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts)
    ):
        return {}
    if (
        provenance.wildcard
        or provenance.dynamic_namespace
        or (not provenance.builtin_namespace_untouched and not _builtin_namespace_safe(context))
    ):
        return {}
    markers: dict[str, ast.ClassDef] = {}
    for node in context.tree.body:
        if not isinstance(node, ast.ClassDef) or not _marker_body(node, context):
            continue
        if not _stable_marker(node, context, provenance):
            continue
        base = node.bases[0]
        has_initializer = any(isinstance(member, ast.FunctionDef) for member in node.body)
        payload = _payload_constructor(node) is not None
        if not _marker_base(base, markers, context, payload=payload, contexts=contexts):
            continue
        if has_initializer and not context.imports.builtin_is_unshadowed("super"):
            continue
        markers[node.name] = node
    return markers


def _stable_marker(marker: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    return (
        provenance.binding(marker.name, marker) is marker
        and marker.name not in provenance.mutated | provenance.external_bindings
        and not _escapes(marker, context, provenance)
    )


def _marker_base(
    base: ast.expr,
    markers: dict[str, ast.ClassDef],
    context: PythonFileContext,
    *,
    payload: bool,
    contexts: dict[Path, PythonFileContext],
) -> bool:
    provenance = context.static_resource_provenance
    local = isinstance(base, ast.Name) and base.id in markers and provenance.binding(base.id, base) is markers[base.id]
    if payload:
        return _payload_exception_base(base, context, contexts, frozenset())
    return local or _payload_exception_base(base, context, contexts, frozenset())


def _payload_exception_base(
    base: ast.expr,
    context: PythonFileContext,
    contexts: dict[Path, PythonFileContext],
    seen: frozenset[tuple[Path, str]],
    *,
    allow_initializer: bool = True,
    allowed: frozenset[str] = _BUILTIN_BASES,
) -> bool:
    provenance = context.static_resource_provenance
    if provenance.wildcard or provenance.dynamic_namespace:
        return False
    if not provenance.builtin_namespace_untouched and not _builtin_namespace_safe(context):
        return False
    if _builtin_base(base, context, provenance, allowed=allowed):
        return True
    if not isinstance(base, ast.Name) or len(seen) >= _MAX_BASE_DEPTH:
        return False
    binding = provenance.binding(base.id, base)
    owner = context
    if isinstance(binding, ast.alias):
        imported = _imported_base_context(binding, context, contexts)
        if imported is None:
            return False
        owner = imported
        binding = _module_class(owner, binding.name)
    if not isinstance(binding, ast.ClassDef) or len(binding.bases) != 1:
        return False
    key = (owner.path, binding.name)
    facts = owner.static_resource_provenance
    if key in seen or owner.generated or binding.name in facts.mutated | facts.external_bindings:
        return False
    if not _plain_exception_class(binding, owner):
        return False
    if not _base_construction_known(binding, owner, allow_initializer=allow_initializer):
        return False
    if _escapes(binding, owner, facts):
        return False
    return _payload_exception_base(
        binding.bases[0], owner, contexts, seen | {key}, allow_initializer=allow_initializer, allowed=allowed
    )


def _base_construction_known(node: ast.ClassDef, context: PythonFileContext, *, allow_initializer: bool) -> bool:
    members = context.binding_inventory.bindings.get(node, {})
    return not {"__new__", "__init_subclass__"}.intersection(members) and (
        allow_initializer or "__init__" not in members
    )


def _imported_base_context(
    binding: ast.alias, context: PythonFileContext, contexts: dict[Path, PythonFileContext]
) -> PythonFileContext | None:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- resolve source contexts only after registry initialization.

    statement = context.parents.get(binding)
    if not isinstance(statement, ast.ImportFrom) or context.parents.get(statement) is not context.tree:
        return None
    path = context.session.local_source.resolve_module(
        context.path, statement.module, statement.level, facts=context.session.first_party
    )
    module = context.session.local_source.read_module(path) if path is not None else None
    if module is None:
        return None
    if module.path not in contexts:
        contexts[module.path] = PythonFileContext(module.path, module.source, context.session)
    return contexts[module.path]


def _module_class(context: PythonFileContext, name: str) -> ast.ClassDef | None:
    if context.tree is None:
        return None
    declarations = [node for node in context.tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    return declarations[0] if len(declarations) == 1 else None


def _plain_exception_class(node: ast.ClassDef, context: PythonFileContext) -> bool:
    return not (node.keywords or node.type_params) and all(
        context.static_resource_provenance.runtime_import_name(decorator) in {"typing.final", "typing_extensions.final"}
        for decorator in node.decorator_list
    )


def _marker_body(node: ast.ClassDef, context: PythonFileContext) -> bool:
    payload = _payload_constructor(node)
    return (
        len(node.bases) == 1
        and _plain_exception_class(node, context)
        and all(
            isinstance(member, ast.Pass)
            or (isinstance(member, ast.FunctionDef) and (_fixed_message_initializer(member) or member is payload))
            or (
                payload is not None
                and isinstance(member, ast.AnnAssign)
                and isinstance(member.target, ast.Name)
                and member.value is None
            )
            or (
                isinstance(member, ast.Expr)
                and isinstance(member.value, ast.Constant)
                and (isinstance(member.value.value, str) or member.value.value is Ellipsis)
            )
            for member in node.body
        )
    )


def _payload_constructor(node: ast.ClassDef) -> ast.FunctionDef | None:
    constructors = [member for member in node.body if isinstance(member, ast.FunctionDef) and member.name == "__init__"]
    if len(constructors) != 1:
        return None
    constructor = constructors[0]
    return constructor if _payload_initializer(constructor) else None


def _payload_initializer(node: ast.FunctionDef) -> bool:
    names = _payload_parameters(node)
    if names is None:
        return False
    fields: set[str] = set()
    used = False
    self_name = [*node.args.posonlyargs, *node.args.args][0].arg
    for statement in node.body:
        value = _payload_statement(statement, names, fields, self_name)
        if value is None:
            return False
        used = used or any(isinstance(child, ast.Name) and child.id in names for child in ast.walk(value))
    return used


def _payload_parameters(node: ast.FunctionDef) -> set[str] | None:
    arguments = [*node.args.posonlyargs, *node.args.args]
    parameters = [*arguments[1:], *node.args.kwonlyargs]
    if node.name != "__init__" or not arguments or not parameters or node.decorator_list or node.type_params:
        return None
    if (
        node.args.vararg
        or node.args.kwarg
        or not isinstance(node.returns, ast.Constant)
        or node.returns.value is not None
    ):
        return None
    if any(parameter.annotation is None for parameter in parameters):
        return None
    if any(not isinstance(default, ast.Constant) for default in node.args.defaults):
        return None
    if any(default is not None and not isinstance(default, ast.Constant) for default in node.args.kw_defaults):
        return None
    return {parameter.arg for parameter in parameters}


def _payload_statement(statement: ast.stmt, names: set[str], fields: set[str], self_name: str) -> ast.expr | None:
    match statement:
        case ast.Assign(targets=[target], value=value) | ast.AnnAssign(target=target, value=ast.expr() as value):
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == self_name
                and not target.attr.startswith("__")
                and _payload_expression(value, names, fields, self_name)
            ):
                return None
            fields.add(target.attr)
            return value
        case ast.Expr(value=value) if _payload_super_call(value, names, fields, self_name):
            return value
        case _:
            return None


def _payload_expression(value: ast.expr, names: set[str], fields: set[str], self_name: str) -> bool:
    match value:
        case ast.Constant(value=constant):
            return constant is not Ellipsis
        case ast.Name(id=name):
            return name in names
        case ast.Attribute(value=ast.Name(id=owner), attr=field):
            return owner == self_name and field in fields
        case ast.JoinedStr(values=parts):
            return all(
                isinstance(part, ast.Constant)
                or (
                    isinstance(part, ast.FormattedValue)
                    and _payload_expression(part.value, names, fields, self_name)
                    and (part.format_spec is None or _payload_expression(part.format_spec, names, fields, self_name))
                )
                for part in parts
            )
        case _:
            return False


def _payload_super_call(value: ast.expr, names: set[str], fields: set[str], self_name: str) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "__init__"
        and isinstance(value.func.value, ast.Call)
        and isinstance(value.func.value.func, ast.Name)
        and value.func.value.func.id == "super"
        and not value.func.value.args
        and not value.func.value.keywords
        and not value.keywords
        and all(_payload_expression(argument, names, fields, self_name) for argument in value.args)
    )


def _fixed_message_initializer(node: ast.FunctionDef) -> bool:
    arguments = [*node.args.posonlyargs, *node.args.args]
    if node.name != "__init__" or node.decorator_list or node.type_params or len(arguments) != 1:
        return False
    if node.args.vararg or node.args.kwarg or node.args.kwonlyargs or node.args.defaults:
        return False
    match node.body:
        case [
            ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(func=ast.Name(id="super"), args=[], keywords=[]), attr="__init__"
                    ),
                    args=[ast.Constant(value=str())],
                    keywords=[],
                )
            )
        ]:
            return True
        case _:
            return False


def _builtin_namespace_safe(context: PythonFileContext) -> bool:
    # Direct exception imports expose immutable class objects.
    for node in context.nodes(ast.Import, ast.ImportFrom, ast.Name):
        if isinstance(node, ast.Import) and any(alias.name == "builtins" for alias in node.names):
            return False
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "builtins"
            and (node.level or any(alias.name not in _BUILTIN_BASES for alias in node.names))
        ):
            return False
        if isinstance(node, ast.Name) and node.id == "__builtins__":
            return False
    return True


def _builtin_base(
    base: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    *,
    allowed: frozenset[str] = _BUILTIN_BASES,
) -> bool:
    if isinstance(base, ast.Name) and base.id in allowed and context.imports.builtin_is_unshadowed(base.id):
        return True
    return any(provenance.imported(base, f"builtins.{name}") for name in allowed)


def _direct_raises(
    markers: dict[str, ast.ClassDef], context: PythonFileContext, provenance: ResourceProvenance
) -> set[ast.ClassDef]:
    candidates = set(markers.values())
    raised_markers: set[ast.ClassDef] = set()
    value_errors: dict[ast.ClassDef, bool] = {}
    validators: dict[ast.AST, bool] = {}
    for raised in context.nodes(ast.Raise):
        target = raised.exc.func if isinstance(raised.exc, ast.Call) else raised.exc
        if not isinstance(target, ast.Name):
            continue
        marker = provenance.binding(target.id, target)
        if not isinstance(marker, ast.ClassDef) or marker not in candidates or marker in raised_markers:
            continue
        constructor = _payload_constructor(marker)
        if constructor is not None and not _payload_guard(raised, constructor, context):
            continue
        if marker not in value_errors:
            value_errors[marker] = _value_error_marker(marker, context, provenance)
        if not (value_errors[marker] and _validation_callback(raised, context, provenance, validators)):
            raised_markers.add(marker)
    return raised_markers


def _payload_guard(raised: ast.Raise, constructor: ast.FunctionDef, context: PythonFileContext) -> bool:
    return _guard_function(raised, context) is not None and _payload_call(raised.exc, constructor.args)


def _guard_function(raised: ast.Raise, context: PythonFileContext) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    guard = context.parents.get(raised)
    if not isinstance(guard, ast.If) or not any(
        _rejection_branch(branch, raised, context) for branch in (guard.body, guard.orelse)
    ):
        return None
    owner = context.parents.get(guard)
    while isinstance(owner, ast.If):
        owner = context.parents.get(owner)
    if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) or owner.returns is None:
        return None
    if isinstance(owner.returns, ast.Constant) and isinstance(owner.returns.value, str):
        return None
    if owner.decorator_list or (owner.name.startswith("__") and owner.name.endswith("__")) or has_own_yield(owner):
        return None
    if _validation_callback(raised, context, context.static_resource_provenance, {}):
        return None
    returns = context.annotation_semantics.resolve_alias(owner.returns)
    if returns is None:
        return None
    if any(
        context.imports.resolves(
            returns,
            sources=frozenset({"typing", "typing_extensions"}),
            symbol=name,
        )
        for name in ("Never", "NoReturn")
    ):
        return None
    return owner


def _rejection_branch(branch: list[ast.stmt], raised: ast.Raise, context: PythonFileContext) -> bool:
    if branch == [raised]:
        return True
    match branch:
        case [ast.Assign(targets=[ast.Name() as target], value=value), last] if last is raised:
            pass
        case _:
            return False
    if not (
        target.id not in context.static_resource_provenance.external_bindings
        and isinstance(value, ast.JoinedStr | ast.Constant)
        and _guard_message(value)
        and raised.exc is not None
    ):
        return False
    return any(
        isinstance(node, ast.Name)
        and node.id == target.id
        and context.static_resource_provenance.binding(node.id, node) is target
        for node in ast.walk(raised.exc)
    )


def _guard_message(value: ast.expr, depth: int = 0) -> bool:
    if depth >= _MAX_MESSAGE_DEPTH:
        return False
    match value:
        case ast.Constant(value=str()) | ast.Name():
            return True
        case ast.Attribute(value=owner):
            return _guard_message(owner, depth + 1)
        case ast.JoinedStr(values=parts):
            return all(
                isinstance(part, ast.Constant)
                or (
                    isinstance(part, ast.FormattedValue)
                    and _guard_message(part.value, depth + 1)
                    and (part.format_spec is None or _guard_message(part.format_spec, depth + 1))
                )
                for part in parts
            )
        case _:
            return False


def _payload_call(expression: ast.expr | None, arguments: ast.arguments) -> bool:
    if not isinstance(expression, ast.Call) or any(isinstance(argument, ast.Starred) for argument in expression.args):
        return False
    positional = [*arguments.posonlyargs, *arguments.args][1:]
    keywords = [keyword.arg for keyword in expression.keywords]
    if len(expression.args) > len(positional) or None in keywords or len(set(keywords)) != len(keywords):
        return False
    supplied = {argument.arg for argument in positional[: len(expression.args)]}
    if not supplied.isdisjoint(keywords):
        return False
    supplied.update(keyword for keyword in keywords if keyword is not None)
    if not {argument.arg for argument in arguments.posonlyargs[1:]}.isdisjoint(keywords):
        return False
    allowed = {argument.arg for argument in (*positional, *arguments.kwonlyargs)}
    required = {argument.arg for argument in positional[: len(positional) - len(arguments.defaults)]}
    required.update(
        argument.arg
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is None
    )
    return supplied <= allowed and required <= supplied


def _value_error_marker(marker: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    seen: set[int] = set()
    current = marker
    while id(current) not in seen:
        seen.add(id(current))
        base = current.bases[0]
        if (
            isinstance(base, ast.Name) and base.id == "ValueError" and context.imports.builtin_is_unshadowed(base.id)
        ) or provenance.imported(base, "builtins.ValueError"):
            return True
        bound = provenance.binding(base.id, base) if isinstance(base, ast.Name) else None
        if isinstance(bound, ast.alias):
            return _imported_value_error_base(bound, context)
        if not isinstance(bound, ast.ClassDef) or len(bound.bases) != 1 or not _plain_exception_class(bound, context):
            return False
        current = bound
    return False


def _imported_value_error_base(binding: ast.alias, context: PythonFileContext) -> bool:
    contexts = {context.path: context}
    owner = _imported_base_context(binding, context, contexts)
    if owner is None:
        return False
    base = _module_class(owner, binding.name)
    if base is None or len(base.bases) != 1:
        return False
    return _payload_exception_base(base.bases[0], owner, contexts, frozenset(), allowed=frozenset({"ValueError"}))


def _validation_callback(
    node: ast.AST,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    cache: dict[ast.AST, bool],
    depth: int = 0,
) -> bool:
    if depth >= _MAX_VALIDATOR_DEPTH:
        return False
    owner = context.parents.get(node)
    while owner is not None and not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        owner = context.parents.get(owner)
    if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    if owner in cache:
        return cache[owner]
    cache[owner] = any(
        provenance.imported(decorator.func if isinstance(decorator, ast.Call) else decorator, qualified)
        for decorator in owner.decorator_list
        for qualified in _VALIDATOR_DECORATORS
    ) or _functional_callback(owner, context, provenance)
    parent = context.parents.get(owner)
    if (
        not cache[owner]
        and isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
        and _local_validator_helper(owner, parent, context, provenance)
    ):
        cache[owner] = _validation_callback(owner, context, provenance, cache, depth + 1)
    return cache[owner]


def _local_validator_helper(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> bool:
    if (
        not isinstance(function, ast.FunctionDef)
        or function.decorator_list
        or has_own_yield(function)
        or function.name in provenance.mutated | provenance.external_bindings
        or provenance.binding(function.name, function) is not function
    ):
        return False
    reads = provenance.reads.get(function.name, ())
    return bool(reads) and all(
        provenance.binding(read.id, read) is function
        and isinstance(parent := context.parents.get(read), ast.Call)
        and parent.func is read
        and provenance.scope(read) in {owner, function}
        for read in reads
    )


def _functional_callback(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> bool:
    if not isinstance(function, ast.FunctionDef) or not isinstance(context.parents.get(function), ast.Module):
        return False
    if (
        function.decorator_list
        or has_own_yield(function)
        or function.name in provenance.mutated | provenance.external_bindings
        or provenance.binding(function.name, function) is not function
    ):
        return False
    return _functional_callback_uses(function, context, provenance)


def _functional_callback_uses(
    function: ast.FunctionDef, context: PythonFileContext, provenance: ResourceProvenance
) -> bool:
    pending: list[ast.FunctionDef | ast.Name] = [function]
    seen: set[ast.AST] = set()
    registered = False
    while pending:
        binding = pending.pop()
        if binding in seen:
            continue
        if len(seen) >= _MAX_VALIDATOR_DEPTH:
            return False
        seen.add(binding)
        name = binding.id if isinstance(binding, ast.Name) else binding.name
        reads = provenance.reads.get(name, ())
        if not reads:
            return False
        for read in reads:
            if provenance.binding(read.id, read) is not binding:
                return False
            if _functional_metadata(read, context, provenance):
                registered = True
            elif (alias := _callback_alias(read, context, provenance)) is not None:
                pending.append(alias)
            else:
                return False
    return registered


def _callback_alias(read: ast.Name, context: PythonFileContext, provenance: ResourceProvenance) -> ast.Name | None:
    statement = context.parents.get(read)
    if not (
        isinstance(statement, ast.Assign)
        and statement.value is read
        and isinstance(context.parents.get(statement), ast.Module)
        and len(statement.targets) == 1
        and isinstance(target := statement.targets[0], ast.Name)
        and target.id not in provenance.mutated | provenance.external_bindings
        and provenance.binding(target.id, target) is target
    ):
        return None
    return target


def _functional_metadata(read: ast.Name, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    parent = context.parents.get(read)
    call = context.parents.get(parent) if isinstance(parent, ast.keyword) else parent
    if not isinstance(call, ast.Call) or not any(
        provenance.imported(call.func, qualified) for qualified in _FUNCTIONAL_VALIDATORS
    ):
        return False
    if call.args:
        if len(call.args) != 1 or call.args[0] is not read or any(keyword.arg == "func" for keyword in call.keywords):
            return False
    elif not isinstance(parent, ast.keyword) or parent.arg != "func":
        return False
    if any(keyword.arg not in {"func", "json_schema_input_type"} for keyword in call.keywords):
        return False
    members = context.parents.get(call)
    if not isinstance(members, ast.Tuple) or call not in members.elts[1:]:
        return False
    annotation = context.parents.get(members)
    if not (
        isinstance(annotation, ast.Subscript)
        and annotation.slice is members
        and any(
            provenance.imported(annotation.value, f"{module}.Annotated") for module in ("typing", "typing_extensions")
        )
    ):
        return False
    return _validation_annotation(annotation, context, provenance)


def _validation_annotation(annotation: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    declaration = context.parents.get(annotation)
    if isinstance(declaration, ast.TypeAlias):
        binding = declaration.name
    elif (
        isinstance(declaration, ast.AnnAssign)
        and isinstance(declaration.target, ast.Name)
        and declaration.value is annotation
    ):
        binding = declaration.target
    else:
        return _validation_field(annotation, context, provenance)
    if not (
        isinstance(context.parents.get(declaration), ast.Module)
        and context.annotation_semantics.aliases.get(binding.id) is annotation
        and binding.id not in provenance.mutated | provenance.external_bindings
        and provenance.binding(binding.id, binding) is binding
    ):
        return False
    reads = provenance.reads.get(binding.id, ())
    return bool(reads) and all(
        provenance.binding(read.id, read) is binding and _validation_field(read, context, provenance) for read in reads
    )


def _validation_field(annotation: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    field = context.parents.get(annotation)
    if not isinstance(field, ast.AnnAssign) or field.annotation is not annotation:
        return False
    model = context.parents.get(field)
    if not (
        isinstance(model, ast.ClassDef)
        and isinstance(context.parents.get(model), ast.Module)
        and len(model.bases) == 1
        and any(provenance.imported(model.bases[0], f"{module}.BaseModel") for module in ("pydantic", "pydantic.main"))
        and not (model.decorator_list or model.keywords or model.type_params)
        and model.name not in provenance.mutated | provenance.external_bindings
        and provenance.binding(model.name, model) is model
    ):
        return False
    return all(
        isinstance(member, ast.Pass)
        or (
            isinstance(member, ast.Expr)
            and isinstance(member.value, ast.Constant)
            and isinstance(member.value.value, str)
        )
        or (
            isinstance(member, ast.AnnAssign)
            and isinstance(member.target, ast.Name)
            and not member.target.id.startswith("__")
            and (member.value is None or isinstance(member.value, ast.Constant))
        )
        for member in model.body
    )


def _escapes(marker: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    return _binding_escapes(marker.name, marker, context, provenance)


def _binding_escapes(name: str, binding: ast.AST, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    for read in provenance.binding_reads(name, binding):
        parent = context.parents.get(read)
        if isinstance(parent, ast.Call) and parent.func is read:
            owner = context.parents.get(parent)
            if isinstance(owner, ast.Raise) and owner.exc is parent:
                continue
            return True
        if isinstance(parent, ast.Raise | ast.ExceptHandler):
            continue
        if isinstance(parent, ast.Tuple) and isinstance(context.parents.get(parent), ast.ExceptHandler):
            continue
        if isinstance(parent, ast.ClassDef) and read in parent.bases:
            continue
        return True
    return False


def _imported_raises(
    context: PythonFileContext, contexts: dict[Path, PythonFileContext]
) -> list[tuple[ast.Raise, ast.ClassDef]]:
    provenance = context.static_resource_provenance
    resolved: dict[ast.alias, ast.ClassDef | None] = {}
    modules: dict[Path, dict[str, ast.ClassDef]] = {}
    seen: set[tuple[ast.AST, ast.ClassDef]] = set()
    findings: list[tuple[ast.Raise, ast.ClassDef]] = []
    for raised in context.nodes(ast.Raise):
        if context.suppressions.is_suppressed(raised.lineno, NoCustomControlFlowException.code):
            continue
        target = raised.exc.func if isinstance(raised.exc, ast.Call) else raised.exc
        if not isinstance(target, ast.Name):
            continue
        binding = provenance.binding(target.id, target)
        if not isinstance(binding, ast.alias) or provenance.runtime_binding(target.id, target) is not binding:
            continue
        owner = _guard_function(raised, context)
        if owner is None:
            continue
        if binding not in resolved:
            resolved[binding] = _imported_marker(binding, target.id, context, contexts, modules)
        marker = resolved[binding]
        if marker is None or (owner, marker) in seen:
            continue
        if not _imported_raise_call(raised.exc, marker):
            continue
        seen.add((owner, marker))
        findings.append((raised, marker))
    return findings


def _imported_raise_call(expression: ast.expr | None, marker: ast.ClassDef) -> bool:
    if isinstance(expression, ast.Call) and (
        any(isinstance(argument, ast.Starred) for argument in expression.args)
        or any(keyword.arg is None for keyword in expression.keywords)
    ):
        return False
    constructor = next(
        (member for member in marker.body if isinstance(member, ast.FunctionDef) and member.name == "__init__"), None
    )
    if constructor is None:
        return not isinstance(expression, ast.Call) or not expression.keywords
    if not isinstance(expression, ast.Call):
        return _fixed_message_initializer(constructor)
    return _payload_call(expression, constructor.args)


def _imported_marker(
    binding: ast.alias,
    name: str,
    context: PythonFileContext,
    contexts: dict[Path, PythonFileContext],
    modules: dict[Path, dict[str, ast.ClassDef]],
) -> ast.ClassDef | None:
    provenance = context.static_resource_provenance
    if name in provenance.mutated | provenance.external_bindings or _binding_escapes(
        name, binding, context, provenance
    ):
        return None
    imported = _imported_base_context(binding, context, contexts)
    if imported is None:
        return None
    if imported.path not in modules:
        if len(modules) >= _MAX_IMPORTED_MODULES:
            return None
        modules[imported.path] = _markers(imported, imported.static_resource_provenance, contexts)
    marker = modules[imported.path].get(binding.name)
    if (
        marker is None
        or imported.suppressions.is_suppressed(marker.lineno, NoCustomControlFlowException.code)
        or not _payload_exception_base(
            marker.bases[0],
            imported,
            contexts,
            frozenset(),
            allow_initializer=any(
                isinstance(member, ast.FunctionDef) and member.name == "__init__" for member in marker.body
            ),
        )
    ):
        return None
    return marker
