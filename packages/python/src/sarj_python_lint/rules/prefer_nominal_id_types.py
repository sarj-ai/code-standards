from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cached_property
from itertools import chain
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, Literal, TypeGuard, final, override

from sarj_python_lint._source import symbol_prefilter_source
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
    is_suppressed,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._annotation_semantics import bit_or_members as _flatten_union
from sarj_python_lint.rules._ast_index import nodes, parent_map, walk as walk_ast
from sarj_python_lint.rules._declared_contracts import MODEL_BASES, SETTINGS_BASES, DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._imports import ABC_SOURCES
from sarj_python_lint.rules._inherited_contract import inherited_contract
from sarj_python_lint.rules._literal_domains import StringDomain
from sarj_python_lint.rules._nominal_project import NominalSource
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._imports import ImportIndex


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_COLLECTION_SOURCES = frozenset({"collections.abc", "typing"})
_BUILTIN_SOURCES = frozenset({"builtins"})
_UUID_SOURCES = frozenset({"uuid"})
_SQLALCHEMY_SOURCES = frozenset({"sqlalchemy.orm"})
_PYDANTIC_SOURCES = frozenset({"pydantic", "pydantic.fields", "pydantic.v1", "pydantic.v1.fields"})
_PYDANTIC_VALIDATOR_SOURCES = _PYDANTIC_SOURCES | {"pydantic.types", "pydantic.functional_validators"}
_PYDANTIC_VALIDATORS = frozenset({"AfterValidator", "BeforeValidator", "PlainValidator", "StringConstraints"})
_FASTAPI_PARAMETER_SOURCES = frozenset({"fastapi", "fastapi.param_functions", "fastapi.params"})
_FASTAPI_PARAMETERS = frozenset({"Body", "Cookie", "Depends", "File", "Form", "Header", "Path", "Query", "Security"})
_VALIDATED_CARRIERS = frozenset({"int", "str"})
_OPERATIONAL_IDS = frozenset(
    {
        "correlation_id",
        "correlation_ids",
        "operation_id",
        "operation_ids",
        "request_id",
        "request_ids",
        "span_id",
        "span_ids",
        "trace_id",
        "trace_ids",
        "unique_id",
        "unique_ids",
    }
)
_OPERATIONAL_PATH_PARTS = frozenset({"audit", "logger", "logging", "observability", "telemetry", "tracing"})
_OPERATIONAL_NAME_PARTS = frozenset({"context", "log", "logger", "logging", "telemetry", "trace", "tracing"})
_MIGRATION_PARTS = frozenset({"alembic", "migrations", "versions"})
_FORMER_SCHEMA_SUFFIXES = ("Config", "Credentials", "Settings")
_TYPED_DICT_BASES = frozenset({"typing.TypedDict", "typing_extensions.TypedDict"})
_TYPED_DICT_WRAPPERS = frozenset({"NotRequired", "ReadOnly", "Required"})
_NESTED_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
_RETURN_ROLE_VERBS = frozenset(
    {"as", "build", "create", "find", "get", "load", "make", "parse", "read", "resolve", "to"}
)
_MIN_SWAPPABLE_ROLES = 2
_SECOND_ARGUMENT = 1
_PAIR_ARITY = 2
_MAX_ALIAS_DEPTH = 8
_SCOPE_CACHE_HISTORY = 7
_COLLECTION_WRAPPERS = frozenset(
    {
        "AbstractSet",
        "AsyncIterable",
        "AsyncIterator",
        "Collection",
        "FrozenSet",
        "Iterable",
        "Iterator",
        "List",
        "Sequence",
        "Set",
        "Tuple",
    }
)
_BUILTIN_COLLECTIONS = frozenset({"frozenset", "list", "set", "tuple"})


@dataclass(frozen=True, slots=True)
class _Carrier:
    shape: str
    raw: bool


@dataclass(frozen=True, slots=True)
class _IdRole:
    name: str
    annotation: ast.expr
    carrier: _Carrier


@dataclass(frozen=True, slots=True)
class _ValidatedDomain:
    name: str
    carrier: str


@dataclass(frozen=True, slots=True)
class _TypeFacts:
    raw_aliases: dict[str, str]
    nominal_aliases: dict[str, str]
    value_roles: dict[str, str] | None = None
    shadowed_names: frozenset[str] = frozenset()
    validated_roles: dict[str, _ValidatedDomain] | None = None
    string_roles: dict[str, list[StringDomain]] | None = None


@dataclass(frozen=True)
class _ScopeFacts:
    sources: dict[str, NominalSource]
    resolved: dict[tuple[str, str | None], _TypeFacts]
    roles: dict[str, str]
    validated_roles: dict[str, _ValidatedDomain]
    string_declarations: Iterable[NominalSource]

    @cached_property
    def string_roles(self) -> dict[str, list[StringDomain]]:
        return _canonical_string_roles(self.string_declarations)


@dataclass(frozen=True, slots=True)
class _BoundaryOwnership:
    classes: dict[ast.ClassDef, set[tuple[str, str]]]
    original_classes: dict[ast.ClassDef, list[_IdRole]]
    constructors: dict[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef]
    original_constructor_roles: dict[ast.ClassDef, set[tuple[str, str]]]

    def redundant(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        roles: list[_IdRole],
        *,
        has_original: bool,
    ) -> bool:
        names = _role_keys(roles)
        if isinstance(node, ast.ClassDef):
            return not has_original and names <= self.original_constructor_roles.get(node, set())
        owner = self.constructors.get(node)
        if owner is None:
            return False
        original_names = _role_keys(self.original_classes.get(owner, []))
        if has_original and not original_names:
            return False
        return names <= (original_names or self.classes.get(owner, set()))


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
type _Boundary = _Function | ast.ClassDef


@dataclass(frozen=True, slots=True)
class _AdditionalBoundary:
    node: _Boundary
    kind: Literal["TypedDict", "wire alias", "class with a settings-like name", "nested route"]
    wire_aliases: frozenset[str] = frozenset()

    def roles(self, imports: ImportIndex, facts: _TypeFacts) -> list[_IdRole]:
        if isinstance(self.node, ast.ClassDef):
            return _class_id_roles(
                self.node, imports, facts, include_wire_aliases=True, typed_dict=self.kind == "TypedDict"
            )
        return _boundary_roles(self.node, imports, facts)


@final
class PreferNominalIdTypes(Rule):
    id: str = "prefer-nominal-id-types"
    code: str = "SARJ093"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Preserve established domain types and distinguish swappable identifier roles.",
        rationale=(
            "Two identifiers with the same primitive or container carrier can be exchanged without a type-checking error. "
            "Erasing an established domain ID has the same problem even when a boundary accepts one identifier. "
            "Nominal types make those role mistakes visible while leaving unlike carriers alone."
        ),
        remediation=(
            "Use `typing.NewType` as the low-runtime-cost default and propagate it from the raw edge through the domain "
            "boundary. Prefer a validated value object when construction must enforce runtime invariants. Preserve established Literal/Enum domains and optionality instead of widening them to primitive carriers."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Local source-proven Literal, NewType and Enum domains propagate through direct calls and rejecting equality guards against a matching typed record field. A relationship and carrier proof are required; a variable name alone does not establish a domain. Raw-input factories returning an established domain retain their construction boundary. Scoped bindings preserve unrelated same-name values. Ambiguous, rebound and type-parameter-shadowed declarations abstain. Dynamic calls, external domain declarations and arbitrary attribute inference are not resolved by this local flow extension. No automatic annotation rewrite is safe, especially for optional values or shadowing names.",
            "A single primitive ID field on a direct Pydantic model receives a warning when an explicit pattern already demonstrates its own identifier domain. Reuse or introduce a nominal ID while retaining the pattern and wire representation; an ID-shaped name alone is insufficient.",
            "The rule checks functions, methods, constructors, and classes for at least two ID-shaped roles with the same proven carrier. Existing coverage remains an error.",
            "A single raw _id/_ids role in an explicitly declared ABC/Protocol contract now receives a warning even when no matching nominal type has been declared. This advisory does not claim two unlike carriers are swappable; operational IDs and external/inherited contracts still apply.",
            "Direct implementations of stable same-file abstract contracts also receive the raw-ID advisory, including overrides. Imported, ambiguous, decorated, mutated and multiple-inheritance bases remain excluded. A contract with an existing swappable-ID error owns that diagnostic instead of repeating its implementation as warnings.",
            "Imported first-party carriers and non-ID roles backed by a unique matching NewType in the owning distribution or a declared local dependency are errors. A single raw ID role also qualifies when that distribution already declares an unambiguous matching nominal type, including optional and collection forms. Ambiguous exports, conditional or relative imports, cycles, and unresolved ownership are skipped.",
            "An exact multi-token role with one import-proven validated Annotated alias in the distribution or a declared local dependency receives a warning when its boundary uses the bare carrier. Ambiguous aliases and FastAPI parameter declarations are excluded. Annotated metadata runs only where the framework applies it.",
            "An exact multi-token parameter or class field annotated with a bare string receives a warning when the owning distribution or a declared local dependency defines one matching StrEnum, str-mixed Enum or string Literal alias. Private declarations apply only in their own module. Duplicate declarations, wire-aliased fields, test code and defaults outside the known domain are excluded.",
            "Non-ID role discovery uses exact snake-case names and proven matching carriers; it does not infer brands from names alone. Dependency discovery respects declared workspace members and exclusions, and excludes optional and transitive dependencies.",
            "Rebound aliases, generic aliases, carrier names shadowed by type parameters, and mutated or escaped canonical provider namespaces are skipped conservatively across the file.",
            "Provider paths and wire models under adapters or integrations are excluded. First-party integration packages use the ordinary boundary checks.",
            "Generated code, migrations, operational context, settings models, SQLAlchemy Mapped fields, ambiguous imports, and unlike carrier shapes are excluded.",
            "TypedDict fields, Pydantic wire-aliased fields, non-settings Config, Credentials, and Settings boundaries, and proven nested FastAPI route parameters can receive warnings for newly visible raw ID roles. A name suffix alone does not establish a settings contract.",
            "Functions and properties receive a warning when a raw return erases a unique matching nominal ID. Return roles match exactly, optionally after one leading verb, and plural roles require a collection carrier.",
            "Canonical object, ABC, Protocol and Generic bases do not hide fields or methods declared by the class. Mutated, escaped or rebound providers remain unknown. Other explicit bases stay excluded from the original boundary checks; their inherited API may prescribe raw carriers. Local custom bases do not prove runtime member ownership remains closed.",
        ),
        examples=(
            RuleExample(
                example_id="erased-domain-argument",
                scenario="domain-flow",
                title="A caller retains the established domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from typing import Literal\nEnvironment = Literal['sandbox', 'live']\ndef save(environment: Environment) -> None: ...\ndef run(value: str) -> None:\n    save(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="preserved-domain-argument",
                scenario="domain-flow",
                title="A typed caller preserves the closed domain",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from typing import Literal\nEnvironment = Literal['sandbox', 'live']\ndef save(environment: Environment) -> None: ...\ndef run(value: Environment) -> None:\n    save(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="established-string-domain",
                scenario="canonical-role",
                title="A matching string role preserves its declared domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from enum import StrEnum\n"
                        "class DeliveryMode(StrEnum):\n"
                        "    IMMEDIATE = 'immediate'\n"
                        "    SCHEDULED = 'scheduled'\n"
                        "def dispatch(delivery_mode: str | None) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="preserved-string-domain",
                scenario="canonical-role",
                title="A typed parameter keeps the declared string domain",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from typing import Literal\n"
                        "type DeliveryMode = Literal['immediate', 'scheduled']\n"
                        "def dispatch(delivery_mode: DeliveryMode | None) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="owned-abstract-contract-id-roles",
                scenario="owned-contract",
                title="Abstract contracts declare their own nominal ID boundary",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/contracts.py",
                        "from abc import ABC, abstractmethod\n"
                        "class FilePort(ABC):\n"
                        "    @abstractmethod\n"
                        "    def move(self, file_id: str, folder_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/contracts.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="owned-abstract-contract-nominal-ids",
                scenario="owned-contract",
                title="Abstract contracts use distinct domain identifiers",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/contracts.py",
                        "from abc import ABC, abstractmethod\n"
                        "from typing import NewType\n"
                        "FileId = NewType('FileId', str)\n"
                        "FolderId = NewType('FolderId', str)\n"
                        "class FilePort(ABC):\n"
                        "    @abstractmethod\n"
                        "    def move(self, file_id: FileId, folder_id: FolderId) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/contracts.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="swappable-primitive-id-roles",
                title="Two domain ID roles share the same primitive carrier",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/files.py",
                        "def move(file_id: str, parent_folder_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/files.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nominal-id-roles",
                title="NewType makes the two domain roles distinct",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/files.py",
                        "from typing import NewType\n\n"
                        "FileId = NewType('FileId', str)\n"
                        "FolderId = NewType('FolderId', str)\n\n"
                        "def move(file_id: FileId, parent_folder_id: FolderId) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/files.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="established-single-id-erased",
                scenario="established-single-id",
                title="A single ID retains its established domain type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/files.py",
                        "from typing import NewType\nFileId = NewType('FileId', str)\n"
                        "def load(file_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/files.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="established-single-id-preserved",
                scenario="established-single-id",
                title="The boundary uses the existing nominal ID",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/files.py",
                        "from typing import NewType\nFileId = NewType('FileId', str)\n"
                        "def load(file_id: FileId) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/files.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="native-canonical-factory",
                scenario="native-symbol-binding",
                title="A normalized canonical NewType proves domain roles",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "import typing\nRoomName = typing.ＮｅｗＴｙｐｅ('RoomName', str)\nCallId = typing.ＮｅｗＴｙｐｅ('CallId', str)\ndef record(room_name: str, call_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="native-factory-data",
                scenario="native-symbol-binding",
                title="Factory spelling in data does not prove identity",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "RoomName = 'ＮｅｗＴｙｐｅ'\ndef record(room_name: str, call_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=False,
            ),
            RuleExample(
                example_id="escaped-canonical-provider",
                scenario="provider-identity",
                title="An escaped factory namespace does not establish canonical domain roles",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "import typing\ndef replace(namespace):\n    namespace.NewType = lambda name, value: value\nreplace(typing)\nRoomName = typing.NewType('RoomName', str)\nCallId = typing.NewType('CallId', str)\ndef record(room_name: str, call_id: str) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description: str = documentation.summary

    def __init__(self) -> None:
        self._scope_cache: list[_ScopeFacts] = []

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if _is_excluded_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None or context.has_wildcard_import:
            return []

        imports = context.imports
        original_facts = _type_facts(tree, imports, node_index=context.node_index)
        boundaries = _boundary_nodes(tree, imports, original_facts)
        facts = (
            self._expanded_facts(context, tree, imports)
            if any(_can_expand(node, imports, original_facts) for node in boundaries)
            else original_facts
        )
        source_lines = context.source_lines
        class_role_names = {
            node: _role_keys(_qualifying_roles(_boundary_roles(node, imports, facts), established=facts.value_roles))
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        constructor_owners = _constructor_owners(tree)
        original_class_roles = {
            node: _qualifying_roles(_boundary_roles(node, imports, original_facts)) for node in class_role_names
        }
        original_constructor_roles = {
            owner: _role_keys(roles)
            for constructor, owner in constructor_owners.items()
            if (roles := _qualifying_roles(_boundary_roles(constructor, imports, original_facts)))
        }

        ownership = _BoundaryOwnership(
            class_role_names, original_class_roles, constructor_owners, original_constructor_roles
        )
        diagnostics: list[Diagnostic] = []

        def collect_boundary_diagnostics() -> None:
            for node in boundaries:
                roles = _qualifying_roles(_boundary_roles(node, imports, facts), established=facts.value_roles)
                if not roles:
                    diagnostics.extend(self._raw_contract_diagnostics(node, context, facts))
                    continue
                old_roles = _qualifying_roles(_boundary_roles(node, imports, original_facts))
                diagnostic_roles = old_roles or roles
                if ownership.redundant(node, diagnostic_roles, has_original=bool(old_roles)):
                    continue
                first_raw = next(role for role in diagnostic_roles if role.carrier.raw)
                if is_suppressed(source_lines, first_raw.annotation.lineno, self.code):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=first_raw.annotation.lineno,
                        col=first_raw.annotation.col_offset + 1,
                        code=self.code,
                        message=_boundary_message(diagnostic_roles, established=bool(old_roles)),
                        severity=Severity.ERROR,
                    )
                )

        collect_boundary_diagnostics()
        for model in tree.body:
            if isinstance(model, ast.ClassDef) and model not in boundaries:
                diagnostics.extend(self._raw_contract_diagnostics(model, context, facts))
        for method in _local_contract_implementations(context, original_facts):
            diagnostics.extend(self._raw_contract_diagnostics(method, context, facts, owned_contract=True))
        diagnostics.extend(self._domain_diagnostics(context, diagnostics))
        diagnostics.extend(self._additional_diagnostics(context, tree, original_facts, facts, diagnostics))
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))

    def _additional_diagnostics(
        self,
        context: PythonFileContext,
        tree: ast.Module,
        original_facts: _TypeFacts,
        facts: _TypeFacts,
        existing: list[Diagnostic],
    ) -> list[Diagnostic]:
        imports = context.imports
        nested_routes = _nested_routes(context)
        boundaries = _additional_class_boundaries(context, tree, original_facts)
        boundaries.extend(_AdditionalBoundary(node, "nested route") for node in nested_routes)
        returns = _named_returns(tree, nested_routes)
        validated_slots = _validated_slots(context, tree, nested_routes, original_facts)
        if facts is original_facts and (
            returns
            or validated_slots
            or any(boundary.wire_aliases or _can_expand(boundary.node, imports, facts) for boundary in boundaries)
        ):
            facts = self._expanded_facts(context, tree, imports)

        diagnostics = self._additional_boundary_warnings(context, boundaries, facts, existing)
        diagnostics.extend(self._return_warnings(context, returns, facts))
        diagnostics.extend(self._canonical_role_diagnostics(context, validated_slots, facts, existing + diagnostics))
        return diagnostics

    def _additional_boundary_warnings(
        self,
        context: PythonFileContext,
        boundaries: list[_AdditionalBoundary],
        facts: _TypeFacts,
        existing: list[Diagnostic],
    ) -> list[Diagnostic]:
        imports = context.imports
        reported_lines = {diagnostic.line for diagnostic in existing}
        diagnostics: list[Diagnostic] = []
        for boundary in boundaries:
            roles = _qualifying_roles(boundary.roles(imports, facts), established=facts.value_roles)
            raw = next(
                (
                    role
                    for role in roles
                    if role.carrier.raw
                    and role.annotation.lineno not in reported_lines
                    and (boundary.kind != "wire alias" or role.name in boundary.wire_aliases)
                ),
                None,
            )
            if raw is not None and not context.suppressions.is_suppressed(raw.annotation.lineno, self.code):
                diagnostics.append(
                    Diagnostic(
                        context.path,
                        raw.annotation.lineno,
                        raw.annotation.col_offset + 1,
                        self.code,
                        f"This {boundary.kind} exposes raw identifiers. {_boundary_message(roles, established=True)}",
                        severity=Severity.WARNING,
                    )
                )

        return diagnostics

    def _return_warnings(
        self, context: PythonFileContext, returns: list[tuple[_Function, str]], facts: _TypeFacts
    ) -> list[Diagnostic]:
        imports = context.imports
        diagnostics: list[Diagnostic] = []
        for function, name in returns:
            prefix, _, remainder = name.partition("_")
            role = _established_return_role(name, function.returns, imports, facts)
            if role is None and prefix in _RETURN_ROLE_VERBS:
                role = _established_return_role(remainder, function.returns, imports, facts)
            if role is None or context.suppressions.is_suppressed(role.annotation.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    context.path,
                    role.annotation.lineno,
                    role.annotation.col_offset + 1,
                    self.code,
                    f"`{function.name}` returns a raw carrier for the established `{role.name}` identifier. "
                    "Preserve the nominal ID in its return annotation.",
                    severity=Severity.WARNING,
                )
            )
        return diagnostics

    def _canonical_role_diagnostics(
        self,
        context: PythonFileContext,
        slots: list[_IdRole],
        facts: _TypeFacts,
        existing: list[Diagnostic],
    ) -> list[Diagnostic]:
        domains = facts.validated_roles or {}
        string_roles = facts.string_roles or {}
        focus_path = context.path.resolve() if string_roles else context.path
        occupied = {(finding.line, finding.col) for finding in existing}
        diagnostics: list[Diagnostic] = []
        for slot in slots:
            line, col = slot.annotation.lineno, slot.annotation.col_offset + 1
            if (line, col) in occupied or context.suppressions.is_suppressed(line, self.code):
                continue
            domain = domains.get(slot.name)
            if domain is not None and slot.carrier.shape == domain.carrier:
                message = (
                    f"`{slot.name}` has the validated domain `{domain.name}`. Use it on model fields, "
                    "and wrap a `NewType` if functions must not accept unvalidated values."
                )
            elif slot.carrier.shape == "str":
                message = _closed_string_message(slot, string_roles.get(slot.name, []), focus_path, context)
                if message is None:
                    continue
            else:
                continue
            diagnostics.append(
                Diagnostic(
                    context.path,
                    line,
                    col,
                    self.code,
                    message,
                    severity=Severity.WARNING,
                )
            )
        return diagnostics

    def _domain_diagnostics(self, context: PythonFileContext, existing: list[Diagnostic]) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        path = context.path
        for argument, domains in context.domain_boundaries.required.items():
            if (
                len(domains) != 1
                or argument.annotation is None
                or context.suppressions.is_suppressed(argument.lineno, self.code)
            ):
                continue
            domain = next(iter(domains))
            if any(
                diagnostic.line == argument.annotation.lineno and diagnostic.code == self.code
                for diagnostic in existing
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    path,
                    argument.annotation.lineno,
                    argument.annotation.col_offset + 1,
                    self.code,
                    f"`{argument.arg}` is compared with or passed to the established `{domain.name}` domain; preserve that type instead of erasing it to a primitive. Preserve optionality and rename shadowing value bindings if necessary.",
                    severity=Severity.ERROR,
                )
            )
        return diagnostics

    def _raw_contract_diagnostics(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        context: PythonFileContext,
        facts: _TypeFacts,
        *,
        owned_contract: bool = False,
    ) -> list[Diagnostic]:
        explicit = owned_contract or _explicit_contract(node, context)
        raw_roles = [
            role
            for role in _boundary_roles(node, context.imports, facts)
            if role.carrier.raw
            and role.name.endswith(("_id", "_ids"))
            and (explicit or _pattern_identifier(node, role, context))
        ]
        return [
            Diagnostic(
                context.path,
                role.annotation.lineno,
                role.annotation.col_offset + 1,
                self.code,
                f"`{role.name}` crosses this owned boundary as a raw identifier; declare or reuse a nominal ID type and validate it at the input boundary.",
                severity=Severity.WARNING,
            )
            for role in raw_roles
            if not context.suppressions.is_suppressed(role.annotation.lineno, self.code)
        ]

    def _expanded_facts(self, context: PythonFileContext, tree: ast.Module, imports: ImportIndex) -> _TypeFacts:
        scope = (
            context.session.nominal_project.scope(
                context.path, context.session.first_party, project=context.session.project
            )
            if context.path.is_file()
            else None
        )
        sources = scope.sources if scope is not None else {}
        declarations = scope.declaration_sources if scope is not None else {}
        current = declarations.get(context.path.resolve()) if declarations else None
        if current is not None and current.text != context.source:
            updated = NominalSource(current.path, context.source, tree)
            sources = {module: updated if source is current else source for module, source in sources.items()}
            declarations = {**declarations, current.path: updated}
        if not sources:
            sources = {"__local__": NominalSource(context.path, context.source, tree)}
        cached = next((entry for entry in self._scope_cache if entry.sources is sources), None)
        if cached is None:
            cached = _scope_facts(sources, (declarations or sources).values())
            self._scope_cache = [*self._scope_cache[-_SCOPE_CACHE_HISTORY:], cached]
        seed = _imported_facts(
            imports, sources, cached.resolved, (), tree, include_annotations=True, node_index=context.node_index
        )
        facts = _type_facts(tree, imports, seed, node_index=context.node_index)
        string_roles = None if is_test_path(context.path) or is_test_support_path(context.path) else cached.string_roles
        return replace(
            facts, value_roles=cached.roles, validated_roles=cached.validated_roles, string_roles=string_roles
        )


def _explicit_contract(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, context: PythonFileContext) -> bool:
    owner = node if isinstance(node, ast.ClassDef) else context.parents.get(node)
    if not isinstance(owner, ast.ClassDef):
        return False
    if any(context.imports.resolved_symbol(base, sources=_TYPING_SOURCES) == "Protocol" for base in owner.bases):
        return True
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
        context.imports.resolves(decorator, sources=ABC_SOURCES, symbol="abstractmethod")
        for decorator in node.decorator_list
    )


def _local_contract_implementations(
    context: PythonFileContext, facts: _TypeFacts
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    if context.tree is None:
        return []
    contracts = _local_abstract_methods(context, facts)
    if not contracts:
        return []
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for owner in context.tree.body:
        if (
            not isinstance(owner, ast.ClassDef)
            or owner.decorator_list
            or owner.keywords
            or owner.type_params
            or len(owner.bases) != 1
        ):
            continue
        base = owner.bases[0]
        if not isinstance(base, ast.Name):
            continue
        provenance = context.static_resource_provenance
        binding = provenance.binding(base.id, base)
        if not isinstance(binding, ast.ClassDef) or base.id in provenance.mutated | provenance.external_bindings:
            continue
        declared = contracts.get(binding, set())
        methods.extend(method for method in _boundary_methods(owner) if method.name in declared)
    return methods


def _local_abstract_methods(context: PythonFileContext, facts: _TypeFacts) -> dict[ast.ClassDef, set[str]]:
    if context.tree is None:
        return {}
    contracts: dict[ast.ClassDef, set[str]] = {}
    for owner in context.tree.body:
        if not isinstance(owner, ast.ClassDef) or not _has_only_marker_bases(
            owner, context.imports, facts.shadowed_names
        ):
            continue
        declared = {
            method.name
            for method in _boundary_methods(owner)
            if _explicit_contract(method, context)
            and not _qualifying_roles(_boundary_roles(method, context.imports, facts))
        }
        if declared:
            contracts[owner] = declared
    return contracts


def _is_excluded_path(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    path_tokens = {token for part in path.parts for token in part.lower().removesuffix(".py").split("_")}
    return (
        not _MIGRATION_PARTS.isdisjoint(lowered)
        or bool((lowered | path_tokens) & _OPERATIONAL_PATH_PARTS)
        or _is_external_adapter_path(path)
    )


def _boundary_nodes(
    tree: ast.Module,
    imports: ImportIndex,
    facts: _TypeFacts,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    result: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_operational_function(statement):
                result.append(statement)
            continue
        if not isinstance(statement, ast.ClassDef):
            continue
        if inherited_contract(statement) and not _has_only_marker_bases(statement, imports, facts.shadowed_names):
            continue
        if _name_parts(statement.name) & _OPERATIONAL_NAME_PARTS:
            continue
        if statement.name.endswith(_FORMER_SCHEMA_SUFFIXES):
            continue
        result.append(statement)
        result.extend(_boundary_methods(statement))
    return result


def _additional_class_boundaries(
    context: PythonFileContext, tree: ast.Module, facts: _TypeFacts
) -> list[_AdditionalBoundary]:
    imports = context.imports
    boundaries: list[_AdditionalBoundary] = []
    contracts: DeclaredContracts | None = None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or _name_parts(node.name) & _OPERATIONAL_NAME_PARTS:
            continue
        suffix = node.name.endswith(_FORMER_SCHEMA_SUFFIXES)
        fields = _effective_fields(node)
        aliases = frozenset(name for name, field in fields.items() if _has_pydantic_wire_alias(field, imports))
        if _has_only_marker_bases(node, imports, facts.shadowed_names):
            boundaries.extend(_marker_class_boundaries(node, suffix=suffix, aliases=aliases))
        elif fields:
            if contracts is None:
                contracts = DeclaredContracts(context)
            boundary = _framework_field_boundary(node, contracts, suffix=suffix, aliases=aliases)
            if boundary is not None:
                boundaries.append(boundary)
    return boundaries


def _marker_class_boundaries(node: ast.ClassDef, *, suffix: bool, aliases: frozenset[str]) -> list[_AdditionalBoundary]:
    if suffix:
        return [
            _AdditionalBoundary(node, "class with a settings-like name", aliases),
            *(_AdditionalBoundary(method, "class with a settings-like name") for method in _boundary_methods(node)),
        ]
    if aliases:
        return [_AdditionalBoundary(node, "wire alias", aliases)]
    return []


def _framework_field_boundary(
    node: ast.ClassDef, contracts: DeclaredContracts, *, suffix: bool, aliases: frozenset[str]
) -> _AdditionalBoundary | None:
    if contracts.unit is None:
        return None
    model = DeclaredClass(contracts.unit, node)
    if contracts.inherits(model, SETTINGS_BASES):
        return None
    if contracts.inherits(model, _TYPED_DICT_BASES):
        return _AdditionalBoundary(node, "TypedDict")
    if (suffix or aliases) and contracts.inherits(model, MODEL_BASES):
        return _AdditionalBoundary(node, "class with a settings-like name" if suffix else "wire alias", aliases)
    return None


def _effective_fields(node: ast.ClassDef) -> dict[str, ast.AnnAssign]:
    return {
        field.target.id: field
        for field in node.body
        if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)
    }


def _nested_routes(context: PythonFileContext) -> list[_Function]:
    if "APIRouter" not in context.symbol_source and "FastAPI" not in context.symbol_source:
        return []
    return [
        node
        for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
        if node.decorator_list
        and isinstance(context.parents.get(node), ast.FunctionDef | ast.AsyncFunctionDef)
        and not _is_operational_function(node)
        and any(route.method in _NESTED_ROUTE_METHODS for route in context.fastapi.routes(node))
    ]


def _named_returns(tree: ast.Module, nested_routes: list[_Function]) -> list[tuple[_Function, str]]:
    functions = list(nested_routes)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not _is_operational_function(node):
            functions.append(node)
        elif isinstance(node, ast.ClassDef) and not _name_parts(node.name) & _OPERATIONAL_NAME_PARTS:
            functions.extend(_boundary_methods(node))
    return [
        (function, name)
        for function in functions
        if function.returns is not None
        and (name := function.name.removeprefix("_")).endswith(("_id", "_ids"))
        and name not in _OPERATIONAL_IDS
    ]


def _validated_slots(
    context: PythonFileContext, tree: ast.Module, nested_routes: list[_Function], facts: _TypeFacts
) -> list[_IdRole]:
    imports = context.imports
    primitives = _TypeFacts({}, {}, shadowed_names=facts.shadowed_names)
    boundaries = _boundary_nodes(tree, imports, facts)
    boundaries.extend(nested_routes)
    return [
        role
        for node in boundaries
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for argument in _parameters(node)
        if (role := _validated_slot(argument.arg, argument.annotation, imports, primitives)) is not None
    ] + _validated_field_slots(context, tree, primitives)


def _validated_field_slots(context: PythonFileContext, tree: ast.Module, primitives: _TypeFacts) -> list[_IdRole]:
    imports = context.imports
    slots: list[_IdRole] = []
    contracts: DeclaredContracts | None = None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or _name_parts(node.name) & _OPERATIONAL_NAME_PARTS:
            continue
        fields = _validated_class_fields(node, imports, primitives)
        if not fields:
            continue
        if _has_only_marker_bases(node, imports, primitives.shadowed_names):
            slots.extend(fields)
            continue
        if contracts is None:
            contracts = DeclaredContracts(context)
        if _validated_model(node, contracts):
            slots.extend(fields)
    return slots


def _validated_class_fields(node: ast.ClassDef, imports: ImportIndex, primitives: _TypeFacts) -> list[_IdRole]:
    return [
        role
        for name, field in _effective_fields(node).items()
        if (role := _validated_slot(name, field.annotation, imports, primitives)) is not None
    ]


def _validated_model(node: ast.ClassDef, contracts: DeclaredContracts) -> bool:
    if contracts.unit is None:
        return False
    model = DeclaredClass(contracts.unit, node)
    return not contracts.inherits(model, SETTINGS_BASES) and contracts.inherits(model, MODEL_BASES | _TYPED_DICT_BASES)


def _validated_slot(
    name: str, annotation: ast.expr | None, imports: ImportIndex, primitives: _TypeFacts
) -> _IdRole | None:
    if annotation is None or "_" not in name.strip("_") or name in _OPERATIONAL_IDS:
        return None
    expression = _stringized_annotation(annotation) or annotation
    if any(
        imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Annotated")
        for node in walk_ast(expression)
        if isinstance(node, ast.Subscript)
    ):
        return None
    carrier = _carrier(expression, imports, primitives)
    if carrier is None or carrier.shape not in _VALIDATED_CARRIERS:
        return None
    return _IdRole(name, annotation, carrier)


def _has_only_marker_bases(node: ast.ClassDef, imports: ImportIndex, shadowed_names: frozenset[str]) -> bool:
    for expression in node.bases:
        base = expression.value if isinstance(expression, ast.Subscript) else expression
        if _expression_is_shadowed(base, shadowed_names):
            return False
        if isinstance(base, ast.Name) and base.id == "object" and imports.builtin_is_unshadowed("object"):
            continue
        if imports.resolves(base, sources=_BUILTIN_SOURCES, symbol="object"):
            continue
        if imports.resolves(base, sources=ABC_SOURCES, symbol="ABC"):
            continue
        if imports.resolved_symbol(base, sources=_TYPING_SOURCES) in {"Generic", "Protocol"}:
            continue
        return False
    return True


def _is_operational_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return bool(_name_parts(node.name) & _OPERATIONAL_NAME_PARTS)


def _name_parts(name: str) -> set[str]:
    parts: list[str] = []
    current = ""
    for index, character in enumerate(name):
        if not character.isalnum():
            if current:
                parts.append(current.lower())
                current = ""
            continue
        starts_word = (
            character.isupper()
            and bool(current)
            and (name[index - 1].islower() or (index + 1 < len(name) and name[index + 1].islower()))
        )
        if starts_word:
            parts.append(current.lower())
            current = character
        else:
            current += character
    if current:
        parts.append(current.lower())
    return set(parts)


def _parameters(node: _Function) -> list[ast.arg]:
    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    return arguments


def _boundary_roles(
    node: ast.AST,
    imports: ImportIndex,
    facts: _TypeFacts,
) -> list[_IdRole]:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return [
                role
                for argument in _parameters(node)
                if (role := _role(argument.arg, argument.annotation, imports, facts, allow_bare_id=True)) is not None
            ]
        case ast.ClassDef():
            return _class_id_roles(node, imports, facts)
        case _:
            pass
    return []


def _role(
    name: str,
    annotation: ast.expr | None,
    imports: ImportIndex,
    facts: _TypeFacts,
    *,
    allow_bare_id: bool,
) -> _IdRole | None:
    if annotation is None or name in _OPERATIONAL_IDS:
        return None
    is_id = name.endswith(("_id", "_ids")) or (allow_bare_id and name == "id")
    carrier = _carrier(annotation, imports, facts)
    if carrier is None:
        return None
    if not is_id and (facts.value_roles is None or facts.value_roles.get(name) != carrier.shape):
        return None
    return _IdRole(name=name, annotation=annotation, carrier=carrier)


def _qualifying_roles(roles: list[_IdRole], *, established: dict[str, str] | None = None) -> list[_IdRole]:
    by_shape: dict[str, list[_IdRole]] = {}
    for role in roles:
        by_shape.setdefault(role.carrier.shape, []).append(role)
    qualifying_shapes = {
        shape
        for shape, same_shape in by_shape.items()
        if len({role.name for role in same_shape}) >= _MIN_SWAPPABLE_ROLES
        and any(role.carrier.raw for role in same_shape)
    }
    return [role for role in roles if role.carrier.shape in qualifying_shapes or _established_raw_id(role, established)]


def _established_raw_id(role: _IdRole, established: dict[str, str] | None) -> bool:
    if not role.carrier.raw or established is None or not role.name.endswith(("_id", "_ids")):
        return False
    if established.get(role.name) == role.carrier.shape:
        return True
    if not role.name.endswith("_ids"):
        return False
    shape = role.carrier.shape
    while "[" in shape and shape.endswith("]"):
        shape = shape.partition("[")[2][:-1]
    name = role.name.removesuffix("s")
    return established.get(name) == shape


def _established_return_role(
    name: str, annotation: ast.expr | None, imports: ImportIndex, facts: _TypeFacts
) -> _IdRole | None:
    role = _role(name, annotation, imports, facts, allow_bare_id=False)
    if (
        role is None
        or (name.endswith("_ids") and "[" not in role.carrier.shape)
        or not _established_raw_id(role, facts.value_roles)
    ):
        return None
    return role


def _role_keys(roles: list[_IdRole]) -> set[tuple[str, str]]:
    return {(role.name, role.carrier.shape) for role in roles}


def _class_id_roles(
    node: ast.ClassDef,
    imports: ImportIndex,
    facts: _TypeFacts,
    *,
    include_wire_aliases: bool = False,
    typed_dict: bool = False,
) -> list[_IdRole]:
    roles: dict[str, _IdRole | None] = {}
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue
        name = statement.target.id
        annotation = statement.annotation
        if typed_dict:
            annotation = _typed_dict_annotation(annotation, imports)
        role = (
            None
            if not include_wire_aliases and _has_pydantic_wire_alias(statement, imports)
            else _role(name, annotation, imports, facts, allow_bare_id=True)
        )
        if role is not None and annotation is not statement.annotation:
            role = replace(role, annotation=statement.annotation)
        previous = roles.get(name)
        if not include_wire_aliases and role is not None and previous is not None and role.carrier == previous.carrier:
            continue
        roles[name] = role
    return [role for role in roles.values() if role is not None]


def _typed_dict_annotation(annotation: ast.expr, imports: ImportIndex) -> ast.expr:
    annotation = _stringized_annotation(annotation) or annotation
    while (
        isinstance(annotation, ast.Subscript)
        and imports.resolved_symbol(annotation.value, sources=_TYPING_SOURCES) in _TYPED_DICT_WRAPPERS
    ):
        annotation = annotation.slice
    return annotation


def _has_pydantic_wire_alias(statement: ast.AnnAssign, imports: ImportIndex) -> bool:
    if _is_pydantic_wire_alias_call(statement.value, imports):
        return True
    annotation = _stringized_annotation(statement.annotation) or statement.annotation
    if not isinstance(annotation, ast.Subscript):
        return False
    if not imports.resolves(annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        return False
    if not isinstance(annotation.slice, ast.Tuple):
        return False
    return any(_is_pydantic_wire_alias_call(metadata, imports) for metadata in annotation.slice.elts[1:])


def _is_pydantic_wire_alias_call(value: ast.expr | None, imports: ImportIndex) -> bool:
    return (
        isinstance(value, ast.Call)
        and imports.resolves(value.func, sources=_PYDANTIC_SOURCES, symbol="Field")
        and any(keyword.arg in {"alias", "serialization_alias", "validation_alias"} for keyword in value.keywords)
    )


def _closed_string_message(
    slot: _IdRole, candidates: list[StringDomain], focus_path: Path, context: PythonFileContext
) -> str | None:
    visible = [
        domain for domain in candidates if not domain.name.startswith("_") or domain.path in {context.path, focus_path}
    ]
    if len(visible) != 1 or visible[0].rebound:
        return None
    domain = visible[0]
    owner = context.parents.get(slot.annotation)
    if isinstance(owner, ast.AnnAssign) and _has_pydantic_wire_alias(owner, context.imports):
        return None
    default = _slot_default(owner, context)
    if (
        domain.members is not None
        and isinstance(default, ast.Constant)
        and isinstance(default.value, str)
        and default.value not in domain.members
    ):
        return None
    return (
        f"`{slot.name}` has the established string domain `{domain.name}`. "
        "Preserve that type and its optionality at this boundary."
    )


def _slot_default(owner: ast.AST | None, context: PythonFileContext) -> ast.expr | None:
    match owner:
        case ast.AnnAssign(value=ast.Call(func=func, args=arguments, keywords=keywords)) if context.imports.resolves(
            func, sources=_PYDANTIC_SOURCES, symbol="Field"
        ):
            return arguments[0] if arguments else next((item.value for item in keywords if item.arg == "default"), None)
        case ast.AnnAssign(value=value):
            return value
        case ast.arg() if isinstance(params := context.parents.get(owner), ast.arguments):
            positional = [*params.posonlyargs, *params.args]
            first_default = len(positional) - len(params.defaults)
            defaults = chain(
                zip(positional[first_default:], params.defaults, strict=True),
                zip(params.kwonlyargs, params.kw_defaults, strict=True),
            )
            return next((default for parameter, default in defaults if parameter is owner), None)
        case _:
            return None


def _type_facts(
    tree: ast.Module,
    imports: ImportIndex,
    seed: _TypeFacts | None = None,
    *,
    node_index: NodeIndex | None = None,
) -> _TypeFacts:
    raw_aliases: dict[str, str] = dict(seed.raw_aliases) if seed is not None else {}
    nominal_aliases: dict[str, str] = dict(seed.nominal_aliases) if seed is not None else {}
    aliases: dict[str, ast.expr] = {}
    nominal_targets: set[str] = set()
    shadowed = _carrier_shadowed_names(tree, imports, node_index=node_index)

    _collect_type_aliases(tree, imports, aliases, nominal_targets, shadowed, node_index=node_index)
    for _round in range(len(aliases)):
        grew = False
        facts = _TypeFacts(raw_aliases, nominal_aliases, shadowed_names=shadowed)
        for name, value in aliases.items():
            if name in raw_aliases or name in nominal_aliases:
                continue
            carrier = _carrier(value, imports, facts)
            if carrier is None:
                continue
            destination = raw_aliases if carrier.raw and name not in nominal_targets else nominal_aliases
            destination[name] = carrier.shape
            grew = True
        if not grew:
            break
    return _TypeFacts(raw_aliases, nominal_aliases, shadowed_names=shadowed)


def _collect_type_aliases(
    tree: ast.Module,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    nominal_targets: set[str],
    shadowed: frozenset[str],
    *,
    node_index: NodeIndex | None = None,
) -> None:
    bindings = _binding_counts(tree, node_index=node_index)
    for statement in tree.body:
        assignment = _alias_assignment(statement)
        if assignment is None or bindings[assignment.target] != 1:
            continue
        target = assignment.target
        value = assignment.value
        if isinstance(value, ast.Call) and _expression_is_shadowed(value.func, shadowed):
            continue
        if _is_new_type_call(value, imports):
            if (
                len(value.args) == _PAIR_ARITY
                and not value.keywords
                and isinstance(value.args[0], ast.Constant)
                and value.args[0].value == target
            ):
                aliases[target] = value.args[_SECOND_ARGUMENT]
                nominal_targets.add(target)
            continue
        aliases[target] = _type_alias_type_value(value, imports, target) or value


@dataclass(frozen=True, slots=True)
class _AliasAssignment:
    target: str
    value: ast.expr


def _alias_assignment(statement: ast.stmt) -> _AliasAssignment | None:
    if isinstance(statement, ast.TypeAlias):
        return None if statement.type_params else _AliasAssignment(target=statement.name.id, value=statement.value)
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return _AliasAssignment(target=statement.targets[0].id, value=statement.value)
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
        return _AliasAssignment(target=statement.target.id, value=statement.value)
    return None


def _is_new_type_call(value: ast.expr, imports: ImportIndex) -> TypeGuard[ast.Call]:
    return isinstance(value, ast.Call) and imports.resolves(value.func, sources=_TYPING_SOURCES, symbol="NewType")


def _type_alias_type_value(value: ast.expr, imports: ImportIndex, target: str) -> ast.expr | None:
    if not isinstance(value, ast.Call):
        return None
    if not imports.resolves(value.func, sources=_TYPING_SOURCES, symbol="TypeAliasType"):
        return None
    if len(value.args) > _PAIR_ARITY or any(isinstance(argument, ast.Starred) for argument in value.args):
        return None
    arguments: dict[str, ast.expr] = dict(zip(("name", "value"), value.args, strict=False))
    for keyword in value.keywords:
        if keyword.arg not in {"name", "value", "type_params"} or keyword.arg in arguments:
            return None
        arguments[keyword.arg] = keyword.value
    name = arguments.get("name")
    if not isinstance(name, ast.Constant) or name.value != target:
        return None
    parameters = arguments.get("type_params")
    if parameters is not None and (not isinstance(parameters, ast.Tuple) or parameters.elts):
        return None
    return arguments.get("value")


def _carrier(annotation: ast.expr, imports: ImportIndex, facts: _TypeFacts) -> _Carrier | None:
    if (parsed := _stringized_annotation(annotation)) is not None:
        return _carrier(parsed, imports, facts)
    if _expression_is_shadowed(annotation, facts.shadowed_names):
        return None
    if isinstance(annotation, (ast.Name, ast.Attribute)):
        name = ast.unparse(annotation)
        if name in facts.raw_aliases:
            return _Carrier(facts.raw_aliases[name], raw=True)
        if name in facts.nominal_aliases:
            return _Carrier(facts.nominal_aliases[name], raw=False)
    if primitive := _primitive_carrier(annotation, imports):
        return _Carrier(primitive, raw=True)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _union_carrier(_flatten_union(annotation), imports, facts)
    if not isinstance(annotation, ast.Subscript):
        return None

    return _subscript_carrier(annotation, imports, facts)


def _carrier_shadowed_names(
    tree: ast.Module, imports: ImportIndex, *, node_index: NodeIndex | None = None
) -> frozenset[str]:
    shadowed = _escaped_provider_names(tree, imports, node_index=node_index)
    for node in nodes(tree, ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple, ast.Attribute, ast.Call, index=node_index):
        match node:
            case ast.TypeVar() | ast.ParamSpec() | ast.TypeVarTuple():
                shadowed.add(node.name)
            case ast.Attribute():
                shadowed.update(_attribute_provider_shadowed_names(node, imports))
            case ast.Call():
                shadowed.update(_call_provider_shadowed_names(node, imports))
    return frozenset(shadowed)


def _attribute_provider_shadowed_names(node: ast.Attribute, imports: ImportIndex) -> set[str]:
    if not isinstance(node.ctx, (ast.Store, ast.Del)) and node.attr not in {
        "__dict__",
        "__setattr__",
        "__delattr__",
        "__getattribute__",
    }:
        return set()
    shadowed = {ast.unparse(node).partition(".")[0]}
    if isinstance(node.value, ast.Name):
        shadowed.update(_mutated_builtin_names(node.value, node.attr, imports))
    return shadowed


def _call_provider_shadowed_names(node: ast.Call, imports: ImportIndex) -> set[str]:
    if not node.args or not _is_builtin_namespace_call(node, imports):
        return set()
    shadowed = {ast.unparse(node.args[0]).partition(".")[0]}
    member = (
        node.args[1].value
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
        else None
    )
    shadowed.update(_mutated_builtin_names(node.args[0], member, imports))
    return shadowed


def _is_builtin_namespace_call(node: ast.Call, imports: ImportIndex) -> bool:
    return any(
        (isinstance(node.func, ast.Name) and node.func.id == symbol and imports.builtin_is_unshadowed(symbol))
        or imports.resolves(node.func, sources=_BUILTIN_SOURCES, symbol=symbol)
        for symbol in ("setattr", "delattr", "vars")
    )


def _escaped_provider_names(tree: ast.Module, imports: ImportIndex, *, node_index: NodeIndex | None) -> set[str]:
    providers = _TYPING_SOURCES | _BUILTIN_SOURCES | _UUID_SOURCES | ABC_SOURCES
    namespaces = {
        name: binding.module
        for name, binding in imports.bindings.items()
        if binding.module in providers and binding.symbol is None
    }
    if not namespaces:
        return set()
    parents = parent_map(tree, index=node_index)
    shadowed: set[str] = set()
    for node in nodes(tree, ast.Name, index=node_index):
        if not isinstance(node.ctx, ast.Load) or node.id not in namespaces:
            continue
        if _direct_provider_access(node, parents.get(node), imports):
            continue
        provider = namespaces[node.id]
        shadowed.update(name for name, binding in imports.bindings.items() if binding.module == provider)
        shadowed.update(_mutated_builtin_names(node, None, imports))
    return shadowed


def _direct_provider_access(node: ast.Name, parent: ast.AST | None, imports: ImportIndex) -> bool:
    if isinstance(parent, ast.Attribute) and parent.value is node:
        return True
    return (
        isinstance(parent, ast.Call)
        and bool(parent.args)
        and parent.args[0] is node
        and _is_builtin_namespace_call(parent, imports)
    )


def _mutated_builtin_names(node: ast.expr, member: str | None, imports: ImportIndex) -> set[str]:
    if not isinstance(node, ast.Name):
        return set()
    binding = imports.bindings.get(node.id)
    if binding is None or binding.module != "builtins" or binding.symbol is not None:
        return set()
    carriers = {"str", "int", "object"} | _BUILTIN_COLLECTIONS
    changed = carriers if member is None or member.startswith("__") else carriers & {member}
    if not changed:
        return set()
    return changed | {
        name
        for name, imported in imports.bindings.items()
        if imported.module == "builtins" and (imported.symbol is None or imported.symbol in changed)
    }


def _expression_is_shadowed(expression: ast.expr, names: frozenset[str]) -> bool:
    return bool(names) and any(isinstance(node, ast.Name) and node.id in names for node in walk_ast(expression))


def _primitive_carrier(annotation: ast.expr, imports: ImportIndex) -> str | None:
    if isinstance(annotation, ast.Name) and annotation.id in {"int", "str"}:
        if imports.builtin_is_unshadowed(annotation.id):
            return annotation.id
        return None
    for symbol in ("int", "str"):
        if imports.resolves(annotation, sources=_BUILTIN_SOURCES, symbol=symbol):
            return symbol
    if imports.resolves(annotation, sources=_UUID_SOURCES, symbol="UUID"):
        return "UUID"
    return None


def _subscript_carrier(annotation: ast.Subscript, imports: ImportIndex, facts: _TypeFacts) -> _Carrier | None:
    target = annotation.value
    if imports.resolves(target, sources=_SQLALCHEMY_SOURCES, symbol="Mapped"):
        return None
    if imports.resolves(target, sources=_TYPING_SOURCES, symbol="Annotated"):
        if not isinstance(annotation.slice, ast.Tuple) or not annotation.slice.elts:
            return None
        return _carrier(annotation.slice.elts[0], imports, facts)
    if imports.resolves(target, sources=_TYPING_SOURCES, symbol="Optional"):
        return _carrier(annotation.slice, imports, facts)
    if imports.resolves(target, sources=_TYPING_SOURCES, symbol="Union"):
        members = list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return _union_carrier(members, imports, facts)

    wrapper = _collection_wrapper(target, imports)
    if wrapper is None:
        return None
    element = _collection_element(annotation.slice, wrapper)
    if element is None:
        return None
    nested = _carrier(element, imports, facts)
    if nested is None:
        return None
    return _Carrier(f"{wrapper}[{nested.shape}]", raw=nested.raw)


def _collection_wrapper(target: ast.expr, imports: ImportIndex) -> str | None:
    if isinstance(target, ast.Name) and target.id in _BUILTIN_COLLECTIONS:
        return target.id if imports.builtin_is_unshadowed(target.id) else None
    for symbol in _BUILTIN_COLLECTIONS:
        if imports.resolves(target, sources=_BUILTIN_SOURCES, symbol=symbol):
            return symbol
    for symbol in _COLLECTION_WRAPPERS:
        if imports.resolves(target, sources=_COLLECTION_SOURCES, symbol=symbol):
            return symbol.lower()
    return None


def _collection_element(slice_node: ast.expr, wrapper: str) -> ast.expr | None:
    if wrapper != "tuple":
        return slice_node
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != _PAIR_ARITY:
        return None
    element, marker = slice_node.elts
    if isinstance(marker, ast.Constant) and marker.value is Ellipsis:
        return element
    return None


def _union_carrier(members: list[ast.expr], imports: ImportIndex, facts: _TypeFacts) -> _Carrier | None:
    carriers: list[_Carrier] = []
    for member in members:
        if _is_none(member):
            continue
        carrier = _carrier(member, imports, facts)
        if carrier is None:
            return None
        carriers.append(carrier)
    if not carriers:
        return None
    if len({carrier.shape for carrier in carriers}) != 1:
        return None
    return _Carrier(carriers[0].shape, raw=any(carrier.raw for carrier in carriers))


def _is_none(annotation: ast.expr) -> bool:
    return (isinstance(annotation, ast.Constant) and annotation.value is None) or (
        isinstance(annotation, ast.Name) and annotation.id == "None"
    )


def _stringized_annotation(annotation: ast.expr) -> ast.expr | None:
    if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
        return None
    try:
        return ast.parse(annotation.value, mode="eval").body
    except SyntaxError, RecursionError, UnicodeError:
        return None


def _is_external_adapter_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return (
        "providers" in parts
        or ("adapters" in parts and ("models" in parts or path.name.lower() == "models.py"))
        or ("integrations" in parts and ("models" in parts or path.name.lower() == "models.py"))
    )


def _constructor_owners(tree: ast.Module) -> dict[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef]:
    return {
        member: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
    }


def _boundary_methods(statement: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        member
        for member in statement.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not _is_operational_function(member)
    ]


def _module_facts(
    module: str,
    sources: dict[str, NominalSource],
    resolved: dict[tuple[str, str | None], _TypeFacts],
    visiting: tuple[str, ...],
    requested: str | None,
) -> _TypeFacts:
    if module in visiting or len(visiting) >= _MAX_ALIAS_DEPTH or module not in sources:
        return _TypeFacts({}, {})
    key = (module, requested)
    if key in resolved:
        return resolved[key]
    local = resolved.get((module, None))
    if (
        local is not None
        and requested is not None
        and (requested in local.raw_aliases or requested in local.nominal_aliases)
    ):
        return local
    source = sources[module]
    if source.tree is None:
        return _TypeFacts({}, {})
    if requested is not None and any(
        isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == requested
        for statement in source.tree.body
    ):
        resolved[key] = _TypeFacts({}, {})
        return resolved[key]
    seed = _imported_facts(
        source.imports,
        sources,
        resolved,
        (*visiting, module),
        source.tree,
        requested=requested,
        node_index=source.node_index,
    )
    facts = _type_facts(source.tree, source.imports, seed, node_index=source.node_index)
    result = _unambiguous_exports(source.tree, source.imports, facts, node_index=source.node_index)
    resolved[key] = result
    return result


def _unambiguous_exports(
    tree: ast.Module, imports: ImportIndex, facts: _TypeFacts, *, node_index: NodeIndex | None = None
) -> _TypeFacts:
    assignments: dict[str, list[_AliasAssignment]] = {}
    for statement in tree.body:
        if (assignment := _alias_assignment(statement)) is not None:
            assignments.setdefault(assignment.target, []).append(assignment)
    bindings: Counter[str] = _binding_counts(tree, node_index=node_index) if assignments else Counter()
    unique = {name for name, values in assignments.items() if len(values) == 1 and bindings.get(name, 0) == 1}
    allowed = unique | set(imports.bindings)
    return _TypeFacts(
        {name: shape for name, shape in facts.raw_aliases.items() if name in allowed},
        {name: shape for name, shape in facts.nominal_aliases.items() if name in allowed},
    )


def _binding_counts(tree: ast.Module, *, node_index: NodeIndex | None = None) -> Counter[str]:
    bindings: Counter[str] = Counter()
    for node in nodes(
        tree,
        ast.Name,
        ast.arg,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.ExceptHandler,
        ast.MatchAs,
        ast.MatchStar,
        ast.MatchMapping,
        ast.TypeVar,
        ast.ParamSpec,
        ast.TypeVarTuple,
        ast.alias,
        index=node_index,
    ):
        match node:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.ExceptHandler(name=str() as name)
                | ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
                | ast.TypeVar(name=name)
                | ast.ParamSpec(name=name)
                | ast.TypeVarTuple(name=name)
            ):
                bindings[name] += 1
            case ast.alias(name=name, asname=alias):
                bindings[alias or name.partition(".")[0]] += 1
            case _:
                continue
    return bindings


def _imported_facts(
    imports: ImportIndex,
    sources: dict[str, NominalSource],
    resolved: dict[tuple[str, str | None], _TypeFacts],
    visiting: tuple[str, ...],
    tree: ast.Module,
    *,
    requested: str | None = None,
    include_annotations: bool = False,
    node_index: NodeIndex | None = None,
) -> _TypeFacts:
    raw: dict[str, str] = {}
    nominal: dict[str, str] = {}
    needed = _needed_carrier_names(tree, imports, include_annotations=include_annotations, node_index=node_index)
    if requested is not None:
        needed.add(requested)
    mutated = {
        ast.unparse(node).partition(".")[0]
        for node in nodes(tree, ast.Attribute, index=node_index)
        if isinstance(node.ctx, (ast.Store, ast.Del))
    }
    for local, binding in imports.bindings.items():
        if local in mutated:
            continue
        targets = _requested_imports(local, binding.symbol, needed)
        for symbol, alias in targets.items():
            facts = _module_facts(binding.module, sources, resolved, visiting, symbol)
            if symbol in facts.raw_aliases:
                raw[alias] = facts.raw_aliases[symbol]
            if symbol in facts.nominal_aliases:
                nominal[alias] = facts.nominal_aliases[symbol]
    return _TypeFacts(raw, nominal)


def _requested_imports(local: str, symbol: str | None, needed: set[str]) -> dict[str, str]:
    if symbol is not None:
        return {symbol: local} if local in needed else {}
    return {name.removeprefix(f"{local}."): name for name in needed if name.startswith(f"{local}.")}


def _needed_carrier_names(
    tree: ast.Module, imports: ImportIndex, *, include_annotations: bool, node_index: NodeIndex | None = None
) -> set[str]:
    expressions: list[ast.expr] = []
    for statement in tree.body:
        assignment = _alias_assignment(statement)
        if assignment is None:
            continue
        value = assignment.value
        if _is_new_type_call(value, imports) and len(value.args) >= _PAIR_ARITY:
            expressions.append(value.args[_SECOND_ARGUMENT])
        elif (alias_value := _type_alias_type_value(value, imports, assignment.target)) is not None:
            expressions.append(alias_value)
        elif not isinstance(value, ast.Call):
            expressions.append(value)
    if include_annotations:
        expressions.extend(_annotations(tree, node_index=node_index))
    names: set[str] = set()
    for expression in expressions:
        parsed = _stringized_annotation(expression) or expression
        names.update(ast.unparse(node) for node in walk_ast(parsed) if isinstance(node, (ast.Name, ast.Attribute)))
    return names


def _annotations(tree: ast.Module, *, node_index: NodeIndex | None = None) -> list[ast.expr]:
    return [
        node.annotation for node in nodes(tree, ast.arg, ast.AnnAssign, index=node_index) if node.annotation is not None
    ] + [
        node.returns
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, index=node_index)
        if node.returns is not None and node.name.endswith(("_id", "_ids"))
    ]


def _can_expand(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, imports: ImportIndex, facts: _TypeFacts
) -> bool:
    if _qualifying_roles(_boundary_roles(node, imports, facts)):
        return False
    if any(role.carrier.raw and role.name.endswith(("_id", "_ids")) for role in _boundary_roles(node, imports, facts)):
        return True
    annotations = _boundary_annotations(node)
    carriers = [carrier for annotation in annotations if (carrier := _carrier(annotation, imports, facts)) is not None]
    if len(carriers) < len(annotations):
        return len(annotations) >= _MIN_SWAPPABLE_ROLES
    return any(
        carrier.raw and sum(other.shape == carrier.shape for other in carriers) >= _MIN_SWAPPABLE_ROLES
        for carrier in carriers
    )


def _boundary_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[ast.expr]:
    if isinstance(node, ast.ClassDef):
        annotations = [member.annotation for member in node.body if isinstance(member, ast.AnnAssign)]
    else:
        annotations = [argument.annotation for argument in _parameters(node) if argument.annotation is not None]
    return annotations


def _boundary_message(roles: list[_IdRole], *, established: bool) -> str:
    names = ", ".join(f"`{name}`" for name in dict.fromkeys(role.name for role in roles))
    if len(roles) == 1:
        return (
            f"{names} uses a raw carrier despite an established matching nominal identifier; "
            "reuse that domain type and propagate it through this boundary."
        )
    if established:
        return (
            f"{names} are swappable ID-shaped roles with the same carrier; introduce or reuse "
            "`typing.NewType` or nominal value-object identifiers and propagate them through this boundary."
        )
    return (
        f"{names} are swappable domain roles with the same carrier; introduce or reuse "
        "`typing.NewType` or nominal value-object types and propagate them through this boundary."
    )


def _scope_facts(sources: dict[str, NominalSource], declarations: Iterable[NominalSource]) -> _ScopeFacts:
    resolved: dict[tuple[str, str | None], _TypeFacts] = {}
    for module, source in sources.items():
        if _canonical_source(source):
            _module_facts(module, sources, resolved, (), None)
    roles = _canonical_roles(sources, resolved)
    return _ScopeFacts(sources, resolved, roles, _canonical_validated_roles(sources, roles), declarations)


def _canonical_source(source: NominalSource, *, symbol: str = "NewType") -> bool:
    return (
        symbol in symbol_prefilter_source(source.text)
        and not _is_excluded_path(source.path)
        and {"tests", "test", "fixtures", "fakes"}.isdisjoint(source.path.parts)
        and not source.path.name.startswith("test_")
        and not source.path.name.endswith("_test.py")
        and source.path.name != "conftest.py"
        and source.tree is not None
    )


def _canonical_roles(
    sources: dict[str, NominalSource], resolved: dict[tuple[str, str | None], _TypeFacts]
) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for module, source in sources.items():
        if not _canonical_source(source) or source.tree is None:
            continue
        facts = resolved.get((module, None), _TypeFacts({}, {}))
        for statement in source.tree.body:
            assignment = _alias_assignment(statement)
            if assignment is None or not _is_new_type_call(assignment.value, source.imports):
                continue
            name = assignment.target
            value = assignment.value
            if (
                len(value.args) != _PAIR_ARITY
                or value.keywords
                or not isinstance(value.args[0], ast.Constant)
                or value.args[0].value != name
            ):
                continue
            if name not in facts.nominal_aliases:
                continue
            candidates.setdefault(_canonical_role_name(name), []).append(facts.nominal_aliases[name])
    return {name: shapes[0] for name, shapes in candidates.items() if len(shapes) == 1}


def _canonical_role_name(name: str) -> str:
    words = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", words).lower()


def _canonical_string_roles(sources: Iterable[NominalSource]) -> dict[str, list[StringDomain]]:
    candidates: dict[str, list[StringDomain]] = {}
    for source in sources:
        if _is_excluded_path(source.path) or is_test_path(source.path) or is_test_support_path(source.path):
            continue
        for domain in source.closed_string_domains:
            role = _canonical_role_name(domain.name.lstrip("_"))
            if "_" in role.strip("_"):
                candidates.setdefault(role, []).append(domain)
    return candidates


def _canonical_validated_roles(
    sources: dict[str, NominalSource], nominal_roles: dict[str, str]
) -> dict[str, _ValidatedDomain]:
    candidates: dict[str, list[_ValidatedDomain | None]] = {}
    for source in sources.values():
        for role, domain in _validated_declarations(source, nominal_roles):
            candidates.setdefault(role, []).append(domain)
    return {
        role: domain for role, options in candidates.items() if len(options) == 1 and (domain := options[0]) is not None
    }


def _validated_declarations(
    source: NominalSource, nominal_roles: dict[str, str]
) -> list[tuple[str, _ValidatedDomain | None]]:
    if not _has_validation_source(source) or source.tree is None:
        return []
    bindings = _binding_counts(source.tree, node_index=source.node_index)
    shadowed = _carrier_shadowed_names(source.tree, source.imports, node_index=source.node_index)
    declarations: list[tuple[str, _ValidatedDomain | None]] = []
    for statement in source.tree.body:
        assignment = _alias_assignment(statement)
        if assignment is None:
            continue
        name = assignment.target
        role = _canonical_role_name(name)
        if "_" not in role.strip("_") or role in nominal_roles:
            continue
        carrier = _validated_alias_carrier(assignment.value, source.imports, shadowed)
        if carrier is not None:
            domain = _ValidatedDomain(name, carrier) if bindings[name] == 1 else None
            declarations.append((role, domain))
    return declarations


def _has_validation_source(source: NominalSource) -> bool:
    text = symbol_prefilter_source(source.text)
    return (
        "Annotated" in text
        and "pydantic" in text
        and ("pattern" in text or any(validator in text for validator in _PYDANTIC_VALIDATORS))
        and _canonical_source(source, symbol="Annotated")
    )


def _validated_alias_carrier(value: ast.expr, imports: ImportIndex, shadowed: frozenset[str]) -> str | None:
    if (
        not isinstance(value, ast.Subscript)
        or not imports.resolves(value.value, sources=_TYPING_SOURCES, symbol="Annotated")
        or not isinstance(value.slice, ast.Tuple)
        or len(value.slice.elts) < _PAIR_ARITY
        or _expression_is_shadowed(value, shadowed)
    ):
        return None
    base, *metadata = value.slice.elts
    carrier = _primitive_carrier(base, imports)
    if carrier is None or carrier not in _VALIDATED_CARRIERS:
        return None
    if any(
        isinstance(item, ast.Call)
        and imports.resolved_symbol(item.func, sources=_FASTAPI_PARAMETER_SOURCES) in _FASTAPI_PARAMETERS
        for item in metadata
    ):
        return None
    return carrier if any(_validating_metadata(item, imports) for item in metadata) else None


def _validating_metadata(item: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(item, ast.Call):
        return False
    symbol = imports.resolved_symbol(item.func, sources=_PYDANTIC_VALIDATOR_SOURCES)
    return symbol in _PYDANTIC_VALIDATORS or (
        symbol == "Field" and any(keyword.arg == "pattern" and not _is_none(keyword.value) for keyword in item.keywords)
    )


def _pattern_identifier(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    role: _IdRole,
    context: PythonFileContext,
) -> bool:
    if not isinstance(node, ast.ClassDef) or role.carrier.shape != "str":
        return False
    origins = AnnotationOrigins(context)
    if not any(
        origins.qualified(base, base) in {"pydantic.BaseModel", "pydantic.main.BaseModel"} for base in node.bases
    ):
        return False
    return any(
        isinstance(field, ast.AnnAssign)
        and isinstance(field.target, ast.Name)
        and field.target.id == role.name
        and isinstance(field.value, ast.Call)
        and origins.qualified(field.value.func, field.value) in {"pydantic.Field", "pydantic.fields.Field"}
        and any(
            keyword.arg == "pattern"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
            and bool(keyword.value.value)
            for keyword in field.value.keywords
        )
        for field in node.body
    )
