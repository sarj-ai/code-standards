from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
from sarj_python_lint.rules._annotation_semantics import bit_or_members as _flatten_union
from sarj_python_lint.rules._declared_contracts import MODEL_BASES, DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from sarj_python_lint._file_context import PythonFileContext


_MIN_BRANCHES = 2
_MIN_REVIEW_BRANCHES = 2
_REVIEW_BASES = MODEL_BASES | {"enum.Enum", "enum.IntEnum", "enum.StrEnum"}
_ISINSTANCE_ARGS = 2
_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "object",
        "range",
        "set",
        "str",
        "tuple",
        "type",
    }
)
_STDLIB_AST_TYPES = frozenset(name for name, value in dict[str, object](vars(ast)).items() if isinstance(value, type))


class _TypeBranch(NamedTuple):
    subject: str
    types: frozenset[str]


class _ReviewBranch(NamedTuple):
    subject: str
    types: frozenset[str]
    model_or_enum: bool


@dataclass(frozen=True, slots=True)
class _ReviewUnit:
    imports: ImportIndex
    unsafe_bindings: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ReviewEvidence:
    imports: ImportIndex
    contracts: DeclaredContracts
    local_classes: frozenset[str]
    unsafe_bindings: frozenset[str]
    units: dict[Path, _ReviewUnit]


@dataclass(frozen=True, slots=True)
class _ReviewBase:
    parent: DeclaredClass | None
    model_or_enum: bool


class _Dispatch(NamedTuple):
    subject: str
    branch_count: int


@final
class PreferMatchTypeDispatch(ProjectRule):
    id: str = "prefer-match-type-dispatch"
    code: str = "SARJ080"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer `match` for structural runtime type dispatch.",
        rationale=(
            "A repeated mutually exclusive `isinstance` dispatch repeats its subject and hides the closed list of "
            "runtime shapes. Class patterns make the alternatives explicit without repeating the dispatch subject."
        ),
        remediation=(
            "Replace the branches with `match subject` and one class-pattern arm per distinct type; combine types "
            "that share behavior with an OR-pattern."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes require a closed private nested synchronous helper with proven inert containing scopes and exact primitive literal callers. Only comment-free builtin class-check ladders on one parameter qualify; unknown subjects, callbacks, frame/closure escapes, sibling checks, grouped conditions, guards and custom classes remain review-only.",
            "General dispatch requires two or more adjacent, unguarded `isinstance` branches over the same simple name. Repeated isinstance calls joined only by or on that same name are also checked; use an OR class pattern for shared behavior. A single isinstance call with a type union remains allowed.",
            "Additional review warnings require at least one source-proven Pydantic/Enum branch. Native-only sequences retain the established proof and exclusions. Mixed model/builtin dispatch is supported; review warnings have no automatic fixes.",
            "A terminating sibling prefix may precede a two-arm if/elif tail whose bodies can fall through. Preserve nested checks inside case bodies rather than moving them into case guards.",
            "The checked types must be unshadowed builtins, undecorated module-local classes without an explicit or known locally inherited custom metaclass, or proven stdlib ast classes; unresolved imports, runtime type groups, repeated type references, generated files, and non-terminating sibling checks are excluded.",
            "Local ancestry must resolve to stable undeclared-metaclass classes or proven builtin/stdlib ast bases. External bases, runtime base aliases, and parameterized base expressions remain excluded because their metaclass or __class_getitem__ effects are unproven.",
            "Nested attribute-validation guards are excluded: converting them to keyword class patterns can turn attribute errors into match fallthrough, and an imported isinstance operand may be a runtime tuple rather than a class.",
            "A terminal-looking context-manager body does not prove a sibling branch terminates: exceptions can be suppressed. An unconditional return or raise after the context manager remains eligible.",
            "Declared support for Python before 3.10 suppresses this recommendation when proven by the nearest project metadata or exact installed-distribution ownership. Missing or ambiguous target metadata retains advisory behavior; it does not prove a modern target.",
        ),
        examples=(
            RuleExample(
                example_id="three-branch-type-dispatch",
                title="Repeated branches dispatch on runtime type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "def parse(value: object):\n"
                        "    if isinstance(value, str):\n"
                        "        return parse_text(value)\n"
                        "    elif isinstance(value, bytes):\n"
                        "        return parse_bytes(value)\n"
                        "    elif isinstance(value, dict):\n"
                        "        return parse_mapping(value)\n"
                        "    raise TypeError(type(value))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="match-type-cases",
                title="Class patterns make the type dispatch explicit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "def parse(value: object):\n"
                        "    match value:\n"
                        "        case str():\n"
                        "            return parse_text(value)\n"
                        "        case bytes():\n"
                        "            return parse_bytes(value)\n"
                        "        case dict():\n"
                        "            return parse_mapping(value)\n"
                        "        case _:\n"
                        "            raise TypeError(type(value))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="two-arm-ast-projection",
                title="Two isinstance returns project one AST identifier shape",
                outcome=ExampleOutcome.MATCH,
                scenario="two-arm-ast-projection",
                files=(
                    ExampleFile.python(
                        "app/ast_names.py",
                        "import ast\n\n"
                        "def dotted_tail(node: ast.expr) -> str | None:\n"
                        "    if isinstance(node, ast.Name):\n"
                        "        return node.id\n"
                        "    if isinstance(node, ast.Attribute):\n"
                        "        return node.attr\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/ast_names.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="two-arm-ast-class-pattern",
                title="Class patterns expose the two AST identifier shapes",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="two-arm-ast-projection",
                files=(
                    ExampleFile.python(
                        "app/ast_names.py",
                        "import ast\n\n"
                        "def dotted_tail(node: ast.expr) -> str | None:\n"
                        "    match node:\n"
                        "        case ast.Name():\n"
                        "            return node.id\n"
                        "        case ast.Attribute():\n"
                        "            return node.attr\n"
                        "        case _:\n"
                        "            return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/ast_names.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="terminal-prefix-with-conditional-tail",
                title="A terminating prefix and conditional if/elif tail dispatch on the same AST node",
                outcome=ExampleOutcome.MATCH,
                scenario="mixed-type-dispatch",
                files=(
                    ExampleFile.python(
                        "app/bindings.py",
                        "import ast\ndef has_binding(node, name):\n    if isinstance(node, ast.ListComp):\n        return True\n    if isinstance(node, ast.FunctionDef):\n        if name in bindings(node):\n            return True\n    elif isinstance(node, ast.ClassDef):\n        if name in bindings(node):\n            return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/bindings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="class-patterns-with-nested-checks",
                title="Class patterns preserve the nested checks within their case bodies",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="mixed-type-dispatch",
                files=(
                    ExampleFile.python(
                        "app/bindings.py",
                        "import ast\ndef has_binding(node, name):\n    match node:\n        case ast.ListComp():\n            return True\n        case ast.FunctionDef():\n            if name in bindings(node):\n                return True\n        case ast.ClassDef():\n            if name in bindings(node):\n                return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/bindings.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="two-type-dispatch",
                scenario="two-type-dispatch",
                title="Two branches already repeat the same type dispatch",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/types.py",
                        "def label(value):\n    if isinstance(value, str):\n        return 'text'\n    elif isinstance(value, bytes):\n        return 'binary'\n    return 'other'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/types.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="two-class-patterns",
                scenario="two-type-dispatch",
                title="Class patterns name both alternatives",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/types.py",
                        "def label(value):\n    match value:\n        case str():\n            return 'text'\n        case bytes():\n            return 'binary'\n    return 'other'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/types.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="repeated-isinstance-or",
                scenario="or-type-dispatch",
                title="Repeated boolean checks share one type subject",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/types.py",
                        "def is_text(value):\n    if isinstance(value, str) or isinstance(value, bytes):\n        return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/types.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="or-class-pattern",
                scenario="or-type-dispatch",
                title="One OR pattern declares shared handling",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/types.py",
                        "def is_text(value):\n    match value:\n        case str() | bytes():\n            return True\n    return False\n",
                    ),
                ),
                focus_path=PurePosixPath("app/types.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "def label():\n    def _label(value):\n        if isinstance(value, str):\n            return 'text'\n        elif isinstance(value, bytes):\n            return 'bytes'\n        elif isinstance(value, int):\n            return 'number'\n        return 'other'\n    return _label('sample')\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "def label():\n    def _label(value):\n        match value:\n            case str():\n                return 'text'\n            case bytes():\n                return 'bytes'\n            case int():\n                return 'number'\n        return 'other'\n    return _label('sample')\n"
                        ),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        imports = context.imports
        all_nodes = tuple(context.nodes(ast.AST))
        unsafe_bindings = _unsafe_local_bound_names(tree, all_nodes, imports) | _namespace_mutations(all_nodes, imports)
        has_wildcard_import = any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in all_nodes
        )
        if (
            not imports.builtin_is_unshadowed("isinstance")
            or {"isinstance", "builtins.isinstance"} & unsafe_bindings
            or has_wildcard_import
        ):
            return []
        local_classes = _unshadowed_module_classes(tree, all_nodes, imports, unsafe_bindings)
        covered: set[int] = set()
        findings = _sibling_findings(
            all_nodes,
            path,
            self.code,
            imports,
            local_classes,
            unsafe_bindings=unsafe_bindings,
            covered=covered,
        )
        findings.extend(
            _ladder_findings(
                all_nodes,
                path,
                self.code,
                imports,
                local_classes,
                unsafe_bindings=unsafe_bindings,
                covered=covered,
            )
        )
        findings.extend(
            _two_arm_ast_projection_findings(
                all_nodes,
                path,
                self.code,
                imports,
                local_classes,
                unsafe_bindings=unsafe_bindings,
            )
        )
        findings.extend(
            _or_dispatch_findings(
                all_nodes,
                path,
                self.code,
                imports,
                local_classes,
                unsafe_bindings=unsafe_bindings,
                covered=covered,
                occupied={(finding.line, finding.col) for finding in findings},
            )
        )
        findings.extend(_review_dispatch_findings(context, local_classes, unsafe_bindings, findings))
        if findings and context.session.python_target.has_declared_support_before(path, (3, 10)):
            return []
        findings = list({(finding.line, finding.col): finding for finding in findings}.values())
        findings.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return findings


def _or_dispatch_findings(
    all_nodes: tuple[ast.AST, ...],
    path: Path,
    code: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    *,
    unsafe_bindings: frozenset[str],
    covered: set[int],
    occupied: set[tuple[int, int]],
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for node in all_nodes:
        if (
            not isinstance(node, ast.If)
            or id(node) in covered
            or not isinstance(node.test, ast.BoolOp)
            or not isinstance(node.test.op, ast.Or)
        ):
            continue
        branch = _type_branch(node.test, imports, local_classes, unsafe_bindings)
        if (
            branch is not None
            and len(branch.types) >= _MIN_BRANCHES
            and (node.lineno, node.col_offset + 1) not in occupied
        ):
            findings.append(
                _diagnostic(
                    path,
                    code,
                    node,
                    _Dispatch(branch.subject, len(node.test.values)),
                    "isinstance OR condition",
                )
            )
    return findings


def _review_dispatch_findings(
    context: PythonFileContext,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
    existing: list[Diagnostic],
) -> list[Diagnostic]:
    evidence = _ReviewEvidence(context.imports, DeclaredContracts(context), local_classes, unsafe_bindings, {})
    used = {item.line for item in existing}
    findings: list[Diagnostic] = []
    for candidates in _review_sequences(context, used):
        branches = _review_dispatch_proven(candidates, evidence)
        if branches is None:
            continue
        used.update(branch.lineno for branch in branches)
        statement = branches[0]
        findings.append(
            Diagnostic(
                context.path,
                statement.lineno,
                statement.col_offset + 1,
                "SARJ080",
                "Review this runtime type dispatch as match/case class patterns; preserve branch order, "
                "fallbacks and nested guards. This broader recommendation has no automatic rewrite.",
                severity=Severity.WARNING,
            )
        )
    return findings


def _review_sequences(context: PythonFileContext, used: set[int]) -> Iterator[Iterator[ast.If]]:
    blocks = (block for owner in context.nodes(ast.AST) for block in _statement_blocks(owner))
    expanded: set[int] = set()
    for block in blocks:
        yield from _review_block(block, used, expanded)


def _review_block(statements: list[ast.stmt], used: set[int], expanded: set[int]) -> Iterator[Iterator[ast.If]]:
    for index, statement in enumerate(statements):
        if not isinstance(statement, ast.If) or id(statement) in expanded:
            continue
        branches = _review_branches(statements, index)
        if statement.lineno in used:
            for branch in branches:
                used.add(branch.lineno)
                expanded.add(id(branch))
        else:
            yield branches


def _review_dispatch_proven(branches: Iterable[ast.If], evidence: _ReviewEvidence) -> list[ast.If] | None:
    proven: list[ast.If] = []
    subject: str | None = None
    seen: set[str] = set()
    has_model_or_enum = False
    for node in branches:
        branch = _review_branch(node, evidence)
        if branch is None or (subject is not None and branch.subject != subject) or seen & branch.types:
            return None
        subject = branch.subject
        seen.update(branch.types)
        has_model_or_enum |= branch.model_or_enum
        proven.append(node)
    return proven if len(proven) >= _MIN_REVIEW_BRANCHES and has_model_or_enum else None


def _review_branches(statements: list[ast.stmt], index: int) -> Iterator[ast.If]:
    first = statements[index]
    if not isinstance(first, ast.If):
        return
    yield first
    current = first
    while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
        current = current.orelse[0]
        yield current
    if current is not first:
        return
    for position in range(index + 1, len(statements)):
        statement = statements[position]
        if current.orelse or not _body_terminates(current.body) or not isinstance(statement, ast.If):
            return
        yield statement
        current = statement
        if statement.orelse:
            return


def _review_branch(node: ast.If, evidence: _ReviewEvidence) -> _ReviewBranch | None:
    test = node.test
    match test:
        case ast.Call(func=ast.Name(id="isinstance"), args=[ast.Name(id=subject), kind], keywords=[]):
            pass
        case _:
            return None
    if known := _type_references(kind, evidence.imports, evidence.local_classes, evidence.unsafe_bindings):
        return _ReviewBranch(subject, known, model_or_enum=False)
    if not isinstance(kind, ast.Name | ast.Attribute):
        return None
    model = evidence.contracts.class_type(kind, at=test)
    if model is None or not _review_ancestry_proven(model, evidence):
        return None
    return _ReviewBranch(subject, frozenset({f"{model.unit.module}.{model.declaration.name}"}), model_or_enum=True)


def _review_ancestry_proven(model: DeclaredClass, evidence: _ReviewEvidence) -> bool:
    pending = [(model, False)]
    active: set[ast.ClassDef] = set()
    completed: set[ast.ClassDef] = set()
    inherited = False
    while pending:
        current, leaving = pending.pop()
        declaration = current.declaration
        if leaving:
            active.remove(declaration)
            completed.add(declaration)
            continue
        if declaration in completed:
            continue
        if declaration in active:
            return False
        unit = _review_unit(current, evidence)
        if unit is None:
            return False
        active.add(declaration)
        pending.append((current, True))
        for base in declaration.bases:
            proven = _review_base(base, current, evidence, unit)
            if proven is None:
                return False
            inherited |= proven.model_or_enum
            if proven.parent is not None:
                pending.append((proven.parent, False))
    return inherited


def _review_unit(model: DeclaredClass, evidence: _ReviewEvidence) -> _ReviewUnit | None:
    if model.unit.tree is None:
        return None
    unit = evidence.units.get(model.unit.path)
    if unit is None:
        imports = ImportIndex.from_tree(model.unit.tree, module_scope_only=True)
        unit = _ReviewUnit(imports, _namespace_mutations(tuple(ast.walk(model.unit.tree)), imports))
        evidence.units[model.unit.path] = unit
    return unit


def _review_base(
    base: ast.expr, model: DeclaredClass, evidence: _ReviewEvidence, unit: _ReviewUnit
) -> _ReviewBase | None:
    qualified = unit.imports.resolved_qualified_name(base)
    root = base
    while isinstance(root, ast.Attribute):
        root = root.value
    if qualified in unit.unsafe_bindings or (isinstance(root, ast.Name) and root.id in unit.unsafe_bindings):
        return None
    if qualified in _REVIEW_BASES:
        return _ReviewBase(None, model_or_enum=True)
    if _builtin_class_reference(base, unit.imports, unit.unsafe_bindings) is not None:
        return _ReviewBase(None, model_or_enum=False)
    parent = evidence.contracts.class_type(base, model.unit, at=base)
    return _ReviewBase(parent, model_or_enum=False) if parent is not None else None


def _namespace_mutations(all_nodes: tuple[ast.AST, ...], imports: ImportIndex) -> frozenset[str]:
    mutated: set[str] = set()
    for node in all_nodes:
        mutated.update(_reflective_namespace_mutations(node, imports))
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and (qualified := imports.resolved_qualified_name(node)) is not None
        ):
            mutated.add(qualified)
    return frozenset(mutated)


def _reflective_namespace_mutations(node: ast.AST, imports: ImportIndex) -> frozenset[str]:
    operation: str | None = None
    member: ast.expr | None = None
    match node:
        case ast.Attribute(attr="__dict__", value=ast.Name(id=name)):
            pass
        case ast.Call(func=ast.Name(id="vars"), args=[ast.Name(id=name)]):
            operation = "vars"
        case ast.Call(func=ast.Name(id=operation), args=[ast.Name(id=name), member, *_]) if operation in {
            "setattr",
            "delattr",
        }:
            pass
        case _:
            return frozenset()
    if operation is not None and not imports.builtin_is_unshadowed(operation):
        return frozenset()
    target = imports.bindings.get(name)
    if target is None or target.symbol is not None:
        return frozenset()
    if isinstance(member, ast.Constant) and isinstance(member.value, str):
        return frozenset({f"{target.module}.{member.value}"})
    return frozenset({name, "isinstance"} if target.module == "builtins" else {name})


def _unshadowed_module_classes(
    tree: ast.Module, all_nodes: tuple[ast.AST, ...], imports: ImportIndex, unsafe_bindings: frozenset[str]
) -> frozenset[str]:
    declarations = [statement for statement in tree.body if isinstance(statement, ast.ClassDef)]
    rebound: set[str] = set()
    for node in all_nodes:
        match node:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
            ):
                rebound.add(name)
            case ast.ClassDef(name=name) if node not in tree.body:
                rebound.add(name)
            case _:
                pass
    _add_module_import_bindings(tree, rebound)
    names = [declaration.name for declaration in declarations]
    stable = [
        declaration
        for declaration in declarations
        if names.count(declaration.name) == 1 and declaration.name not in rebound
    ]
    nominal = _nominal_class_ancestry(stable, imports, unsafe_bindings)
    return frozenset(
        declaration.name
        for declaration in stable
        if declaration.name in nominal
        and not any(keyword.arg in {"metaclass", None} for keyword in declaration.keywords)
    )


def _nominal_class_ancestry(
    declarations: list[ast.ClassDef], imports: ImportIndex, unsafe_bindings: frozenset[str]
) -> frozenset[str]:
    proven: frozenset[str] = frozenset()
    while True:
        nominal = frozenset(
            declaration.name
            for declaration in declarations
            if not declaration.decorator_list
            and not _unproven_metaclass_header(declaration, imports, unsafe_bindings)
            and all(_nominal_base(base, imports, proven, unsafe_bindings) for base in declaration.bases)
        )
        if nominal <= proven:
            return proven
        proven |= nominal


def _nominal_base(
    expression: ast.expr, imports: ImportIndex, local_classes: frozenset[str], unsafe_bindings: frozenset[str]
) -> bool:
    if isinstance(expression, ast.Subscript):
        return False
    return _type_reference(expression, imports, local_classes, unsafe_bindings) is not None or (
        _builtin_class_reference(expression, imports, unsafe_bindings) is not None
    )


def _unproven_metaclass_header(
    declaration: ast.ClassDef, imports: ImportIndex, unsafe_bindings: frozenset[str]
) -> bool:
    for keyword in declaration.keywords:
        if keyword.arg is None:
            return True
        if keyword.arg != "metaclass":
            continue
        if _builtin_class_reference(keyword.value, imports, unsafe_bindings) == "type":
            continue
        return True
    return False


def _builtin_class_reference(expression: ast.expr, imports: ImportIndex, unsafe_bindings: frozenset[str]) -> str | None:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in unsafe_bindings:
        return None
    if (
        isinstance(expression, ast.Name)
        and expression.id in _BUILTIN_TYPES
        and imports.builtin_is_unshadowed(expression.id)
        and f"builtins.{expression.id}" not in unsafe_bindings
    ):
        return expression.id
    symbol = imports.resolved_symbol(expression, sources=frozenset({"builtins"}))
    if symbol in _BUILTIN_TYPES and f"builtins.{symbol}" not in unsafe_bindings:
        return symbol
    return None


def _unsafe_local_bound_names(tree: ast.Module, all_nodes: tuple[ast.AST, ...], imports: ImportIndex) -> frozenset[str]:
    names = _unsafe_import_bound_names(tree, all_nodes, imports)
    names.update(
        candidate.name
        for candidate in all_nodes
        if isinstance(candidate, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and candidate.name is not None
    )
    names.update(
        candidate.rest
        for candidate in all_nodes
        if isinstance(candidate, ast.MatchMapping) and candidate.rest is not None
    )
    return frozenset(names)


def _unsafe_import_bound_names(tree: ast.Module, all_nodes: tuple[ast.AST, ...], imports: ImportIndex) -> set[str]:
    module_imports = {id(statement) for statement in tree.body if isinstance(statement, (ast.Import, ast.ImportFrom))}
    names: set[str] = set()
    for statement in all_nodes:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        relative = isinstance(statement, ast.ImportFrom) and statement.level > 0
        if id(statement) in module_imports and not relative:
            continue
        for alias in statement.names:
            if not _preserves_indexed_import(statement, alias, imports):
                names.add(alias.asname or alias.name.partition(".")[0])
    return names


def _preserves_indexed_import(statement: ast.Import | ast.ImportFrom, alias: ast.alias, imports: ImportIndex) -> bool:
    local = alias.asname or alias.name.partition(".")[0]
    target = imports.bindings.get(local)
    if target is None:
        return False
    if isinstance(statement, ast.ImportFrom):
        return not statement.level and target.module == statement.module and target.symbol == alias.name
    return target.module == alias.name and target.symbol is None


def _ladder_findings(
    all_nodes: tuple[ast.AST, ...],
    path: Path,
    code: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    *,
    unsafe_bindings: frozenset[str],
    covered: set[int],
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    continuations = set(covered)
    for node in all_nodes:
        if not isinstance(node, ast.If) or id(node) in continuations:
            continue
        branches = [node]
        child_ids: list[int] = []
        current = node
        while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            branches.append(current)
            child_ids.append(id(current))
        if any(
            isinstance(part, ast.Call) and isinstance(part.func, ast.Name) and part.func.id == "isinstance"
            for part in ast.walk(node.test)
        ):
            continuations.update(child_ids)
        dispatch = _dispatch(branches, imports, local_classes, unsafe_bindings)
        if dispatch is not None:
            covered.update(child_ids)
            findings.append(_diagnostic(path, code, node, dispatch, "isinstance ladder"))
    return findings


def _sibling_findings(
    all_nodes: tuple[ast.AST, ...],
    path: Path,
    code: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    *,
    unsafe_bindings: frozenset[str],
    covered: set[int],
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []

    def collect_block(statements: list[ast.stmt]) -> None:
        index = 0
        while index < len(statements):
            run = _terminal_prefix(statements, index, imports, local_classes, unsafe_bindings)
            cursor = index + len(run)
            if run and cursor < len(statements):
                tail_statement = statements[cursor]
                if isinstance(tail_statement, ast.If):
                    tail = _two_arm_ladder(tail_statement)
                    if tail and _dispatch([*run, *tail], imports, local_classes, unsafe_bindings) is not None:
                        run.extend(tail)
                        cursor += 1
            dispatch = _dispatch(run, imports, local_classes, unsafe_bindings)
            if dispatch is not None:
                covered.update(id(branch) for branch in run[1:])
                shape = (
                    "terminating isinstance prefix with if/elif tail"
                    if run[-2].orelse
                    else "terminating isinstance sequence"
                )
                findings.append(_diagnostic(path, code, run[0], dispatch, shape))
            index = max(cursor, index + 1)

    for owner in all_nodes:
        for statements in _statement_blocks(owner):
            collect_block(statements)
    return findings


def _terminal_prefix(
    statements: list[ast.stmt],
    index: int,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> list[ast.If]:
    run: list[ast.If] = []
    subject: str | None = None
    seen: set[str] = set()
    for cursor in range(index, len(statements)):
        statement = statements[cursor]
        if not isinstance(statement, ast.If) or statement.orelse or not _body_terminates(statement.body):
            break
        branch = _type_branch(statement.test, imports, local_classes, unsafe_bindings)
        if branch is None or (subject is not None and branch.subject != subject) or bool(seen & branch.types):
            break
        run.append(statement)
        subject = branch.subject
        seen.update(branch.types)
    return run


def _two_arm_ladder(statement: ast.If) -> tuple[ast.If, ast.If] | None:
    if len(statement.orelse) != 1 or not isinstance(statement.orelse[0], ast.If):
        return None
    second = statement.orelse[0]
    if len(second.orelse) == 1 and isinstance(second.orelse[0], ast.If):
        return None
    return statement, second


def _dispatch(
    branches: list[ast.If],
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> _Dispatch | None:
    if len(branches) < _MIN_BRANCHES:
        return None
    parsed = [_type_branch(branch.test, imports, local_classes, unsafe_bindings) for branch in branches]
    if any(branch is None for branch in parsed):
        return None
    typed = [branch for branch in parsed if branch is not None]
    subjects = {branch.subject for branch in typed}
    if len(subjects) != 1:
        return None
    seen: set[str] = set()
    for branch in typed:
        if seen & branch.types:
            return None
        seen.update(branch.types)
    if len(seen) < _MIN_BRANCHES:
        return None
    return _Dispatch(subjects.pop(), len(branches))


def _two_arm_ast_projection_findings(
    all_nodes: tuple[ast.AST, ...],
    path: Path,
    code: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    *,
    unsafe_bindings: frozenset[str],
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for owner in all_nodes:
        for statements in _statement_blocks(owner):
            for index in range(len(statements) - 2):
                first, second, fallback = statements[index : index + 3]
                if not _returns_none(fallback):
                    continue
                first_projection = _ast_identifier_projection(
                    first,
                    imports,
                    local_classes,
                    unsafe_bindings,
                )
                second_projection = _ast_identifier_projection(
                    second,
                    imports,
                    local_classes,
                    unsafe_bindings,
                )
                if (
                    first_projection is None
                    or second_projection is None
                    or first_projection[0] != second_projection[0]
                    or {first_projection[1], second_projection[1]} != {"ast.Name", "ast.Attribute"}
                ):
                    continue
                if index > 0 and _is_preceding_type_branch(
                    statements[index - 1],
                    first_projection[0],
                    imports,
                    local_classes,
                    unsafe_bindings,
                ):
                    continue
                subject = first_projection[0]
                findings.append(
                    Diagnostic(
                        path=path,
                        line=first.lineno,
                        col=first.col_offset + 1,
                        code=code,
                        severity=Severity.ERROR,
                        message=(
                            f"two-arm ast.Name/ast.Attribute projection on '{subject}' — use one match/case "
                            "statement so the structural alternatives are explicit."
                        ),
                    )
                )
    return findings


def _ast_identifier_projection(
    statement: ast.stmt,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> tuple[str, str] | None:
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return None
    branch = _type_branch(statement.test, imports, local_classes, unsafe_bindings)
    returned = statement.body[0]
    if branch is None or len(branch.types) != 1 or not isinstance(returned, ast.Return):
        return None
    type_name = next(iter(branch.types))
    expected_field = {"ast.Name": "id", "ast.Attribute": "attr"}.get(type_name)
    value = returned.value
    if not (
        expected_field is not None
        and isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == branch.subject
        and value.attr == expected_field
    ):
        return None
    return branch.subject, type_name


def _is_preceding_type_branch(
    statement: ast.stmt,
    subject: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> bool:
    if not isinstance(statement, ast.If) or statement.orelse or not _body_terminates(statement.body):
        return False
    branch = _type_branch(statement.test, imports, local_classes, unsafe_bindings)
    return branch is not None and branch.subject == subject


def _returns_none(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Return) and (
        statement.value is None or (isinstance(statement.value, ast.Constant) and statement.value.value is None)
    )


def _is_class_pattern_type(
    node: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id[:1].isupper() and (node.id in local_classes or node.id in imports.bindings)
    if not isinstance(node, ast.Attribute) or not node.attr[:1].isupper():
        return False
    root: ast.expr = node
    while isinstance(root, ast.Attribute):
        root = root.value
    return isinstance(root, ast.Name) and root.id in imports.bindings


def _type_branch(
    test: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> _TypeBranch | None:
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return _or_type_branch(test, imports, local_classes, unsafe_bindings)
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == _ISINSTANCE_ARGS
        and not test.keywords
        and isinstance(test.args[0], ast.Name)
    ):
        return None
    types = _type_references(test.args[1], imports, local_classes, unsafe_bindings)
    return _TypeBranch(test.args[0].id, types) if types else None


def _or_type_branch(
    test: ast.BoolOp,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> _TypeBranch | None:
    parts = [_type_branch(value, imports, local_classes, unsafe_bindings) for value in test.values]
    if any(part is None for part in parts):
        return None
    branches = [part for part in parts if part is not None]
    if len({part.subject for part in branches}) != 1:
        return None
    combined_types: set[str] = set()
    for part in branches:
        if combined_types & part.types:
            return None
        combined_types.update(part.types)
    return _TypeBranch(branches[0].subject, frozenset(combined_types))


def _type_references(
    expression: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> frozenset[str] | None:
    if isinstance(expression, ast.Tuple):
        parts = expression.elts
    elif isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        parts = _flatten_union(expression)
    else:
        parts = [expression]
    references = [_type_reference(part, imports, local_classes, unsafe_bindings) for part in parts]
    if any(reference is None for reference in references):
        return None
    return frozenset(reference for reference in references if reference is not None)


def _type_reference(
    expression: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> str | None:
    if (builtin := _builtin_class_reference(expression, imports, unsafe_bindings)) is not None:
        return builtin
    if isinstance(expression, ast.Name) and expression.id in local_classes and expression.id not in unsafe_bindings:
        return expression.id
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name) and root.id in unsafe_bindings:
        return None
    symbol = imports.resolved_symbol(expression, sources=frozenset({"ast"}))
    if symbol is None or f"ast.{symbol}" in unsafe_bindings or symbol not in _STDLIB_AST_TYPES:
        return None
    return f"ast.{symbol}"


def _diagnostic(path: Path, code: str, node: ast.If, dispatch: _Dispatch, shape: str) -> Diagnostic:
    return Diagnostic(
        path=path,
        line=node.lineno,
        col=node.col_offset + 1,
        code=code,
        severity=Severity.ERROR,
        message=(
            f"{dispatch.branch_count}-branch {shape} on '{dispatch.subject}' — use match/case class patterns "
            "so the mutually exclusive runtime type dispatch is explicit."
        ),
    )


def _body_terminates(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    last = body[-1]
    match last:
        case ast.Return() | ast.Raise() | ast.Break() | ast.Continue():
            return True
        case ast.If(body=if_body, orelse=else_body):
            return bool(else_body) and _body_terminates(if_body) and _body_terminates(else_body)
        case _:
            return False


def _statement_blocks(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    match node:
        case ast.Module() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return (node.body,)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.With() | ast.AsyncWith() | ast.ExceptHandler() | ast.match_case():
            return (node.body,)
        case ast.Try() | ast.TryStar():
            # ExceptHandler owns each handler body when ast.walk reaches it.
            return node.body, node.orelse, node.finalbody
        case _:
            return ()


def _add_module_import_bindings(tree: ast.Module, rebound: set[str]) -> None:
    rebound.update(
        alias.asname or alias.name.partition(".")[0]
        for statement in tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
        for alias in statement.names
        if alias.name != "*"
    )
