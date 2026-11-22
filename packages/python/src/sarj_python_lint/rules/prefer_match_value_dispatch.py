from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._declared_contracts import DeclaredContracts
from sarj_python_lint.rules._finite_literal_dispatch import finite_literal_dispatches


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type _Literal = str | bytes | int | float
_MIN_TESTS = 2
_MIN_EXPANDED_ARMS = 3
_GUARDED_TEST_PARTS = 2
_MIN_GROUP_VALUES = 2
_MAX_GROUP_VALUES = 6
_ENUM_BASES = frozenset({"enum.Enum", "enum.IntEnum", "enum.StrEnum"})


@final
class PreferMatchValueDispatch(Rule):
    id: str = "prefer-match-value-dispatch"
    code: str = "SARJ439"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Prefer match/case for repeated dispatch on one value with a fallback.",
        rationale="A single dispatch subject makes distinct value cases and their fallback easier to review.",
        remediation=(
            "Consider match/case while preserving fallback and constant semantics; use literal or dotted value "
            "patterns, never bare constant names that capture instead of compare. Review membership versus equality, "
            "subject evaluation, and guard order before rewriting."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "A stable string- or integer-Literal parameter also warns when one returning positive equality or membership branch, with the parameter on the left, partitions it against an else ending in return, or against a return immediately following it in a function body or if/else branch; elif branches, negated or reversed comparisons, Boolean selectors, and following returns preceded by other statements or nested in with, try, loop or match blocks abstain. This subset is always WARNING and has no autofix.",
            "After explicit literal cases, a non-rejecting match wildcard covering remaining known values also warns, including captured wildcards. Explicit rejection and import-proven assert_never remain valid, including logging prefixes and return assert_never.",
            "Direct Literal annotations, module-local aliases and unique first-party imports, including imports in module-level TYPE_CHECKING blocks, are resolved without executing imports; aliases defined inside conditional blocks abstain. Open, mutated, guarded, locally shadowed and unresolved domains abstain. Alias resolution stops after eight binding nodes and source ownership after eight modules.",
            "Literal comparisons, Boolean combinations and assertions narrow reachable values through enclosing if branches, try bodies before their else, and preceding if/elif chains whose branches end in return, raise, continue, break, assert False, assert_never or sys.exit/os._exit/os.abort. Any other preceding statement that reads the subject and can return, raise, assert, call those exits or leave its enclosing loop, any such statement inside a subject-narrowed branch, enclosing while tests and match cases whose subject or guard reads the subject, and guards nested over eight levels abstain. Nested function definitions are not executed. Assertion narrowing assumes assertions run (not python -O); other NoReturn helpers are treated as returning.",
            "Rejection proof follows statement order and runtime import lookup, including methods that skip class bindings, is bounded to eight levels and abstains on uncertain control flow. Upstream type checking owns missing-case exhaustiveness; protection requires reportMatchNotExhaustive, enabled as an error by the Sarj strict preset.",
            "Safe fixes require a closed private nested synchronous helper with proven inert containing scopes and exact primitive literal callers. Only comment-free literal-equality ladders on one parameter qualify; unknown subjects, callbacks, frame/closure escapes, sibling checks, grouped conditions and guards remain review-only.",
            "ERROR covers direct literal equality ladders on an unrebound local parameter and terminal equality dispatch on a stable local name against distinct dotted values from one import-proven namespace or local enum. A proven minimum Python version of 3.10 and no visible namespace access are required. Other supported dispatch remains WARNING.",
            "Equality-only ladders require two or more tests on the same left-hand name or attribute chain, followed by else.",
            "Cases must be distinct string, bytes, or numeric literals, or singly bound module constants containing them; shadowed constants and singleton values are excluded.",
            "This is a readability suggestion, not proof of exhaustiveness or a safe automatic rewrite: attributes can have side effects and match evaluates its subject once.",
            "Grouped or guarded ladders and terminal sibling branches require three distinct arms on a bare name; only the last arm may have a selector-first guard.",
            "Two or more terminal sibling equality branches with a terminal fallback, or an if/elif ladder with else, also qualify when comparing one bare name with distinct values from the same qualified namespace. Imported values are not assumed to be exhaustive enum members. This subset remains review-only because import attributes and equality may have custom behavior.",
            "Legacy grouped ladders contain two to six distinct string literals in a tuple, list, or set; the finite-parameter subset accepts any nonempty literal group within its proven domain. Set hashing and custom equality can differ from pattern matching; no runtime string type is inferred.",
            "Declared support for Python before 3.10 suppresses this recommendation when proven by the nearest project metadata or exact installed-distribution ownership. Missing or ambiguous target metadata retains advisory behavior; it does not prove a modern target.",
            "An if/elif ladder without else warns at three or more arms and never receives the safe fix. Identity checks against members of a source-proven Enum, IntEnum or StrEnum class without a custom __eq__ also warn; value patterns compare with ==, so confirm the subject is a member before rewriting. Unresolved, relative or reassigned enum namespaces abstain.",
        ),
        examples=(
            RuleExample(
                example_id="terminal-qualified-value-dispatch",
                scenario="qualified-terminal-dispatch",
                title="Keep error variants and their fallback under one dispatch subject",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile(PurePosixPath("pyproject.toml"), "[project]\nrequires-python = '>=3.10'\n"),
                    ExampleFile.python(
                        "app/errors.py",
                        "from provider import ErrorId\n"
                        "def classify(error_id):\n"
                        "    if error_id == ErrorId.INSUFFICIENT:\n        return insufficient()\n"
                        "    if error_id == ErrorId.INVALID_OPTION:\n        return invalid_option()\n"
                        "    return rejected()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="qualified-value-match-retains-fallback",
                scenario="qualified-terminal-dispatch",
                title="Value cases preserve the terminal fallback",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from provider import ErrorId\n"
                        "def classify(error_id):\n"
                        "    match error_id:\n"
                        "        case ErrorId.INSUFFICIENT:\n            return insufficient()\n"
                        "        case ErrorId.INVALID_OPTION:\n            return invalid_option()\n"
                        "        case _:\n            return rejected()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="stable-literal-parameter",
                title="Dispatch a stable parameter through literal cases",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile(PurePosixPath("pyproject.toml"), "[project]\nrequires-python = '>=3.10'\n"),
                    ExampleFile.python(
                        "app/parse.py",
                        "def parse(kind):\n    if kind == 'json': return json_parser()\n    elif kind == 'yaml': return yaml_parser()\n    else: return fallback()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parse.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="grouped-terminal-suffix-dispatch",
                scenario="grouped-terminal-dispatch",
                title="Group terminal format dispatch under one subject",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/formats.py",
                        "def parse_config(suffix: str, source: str, jsonc_is_valid: bool):\n"
                        "    if suffix in {'.yaml', '.yml'}:\n"
                        "        return ('yaml', source)\n"
                        "    if suffix == '.toml':\n"
                        "        return ('toml', source)\n"
                        "    if suffix == '.jsonc' and jsonc_is_valid:\n"
                        "        return ('jsonc', source)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/formats.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="grouped-suffix-match-with-guard",
                scenario="grouped-terminal-dispatch",
                title="Retain grouped alternatives, the guard, and the fallback",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/formats.py",
                        "def parse_config(suffix: str, source: str, jsonc_is_valid: bool):\n"
                        "    match suffix:\n"
                        "        case '.yaml' | '.yml':\n"
                        "            return ('yaml', source)\n"
                        "        case '.toml':\n"
                        "            return ('toml', source)\n"
                        "        case '.jsonc' if jsonc_is_valid:\n"
                        "            return ('jsonc', source)\n"
                        "        case _:\n"
                        "            return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/formats.py"),
                expected_count=0,
                public=False,
            ),
            RuleExample(
                example_id="named-file-dispatch",
                title="Make repeated filename dispatch explicit",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/migrate.py",
                        "_ESLINT_SUPPRESSIONS = 'eslint.json'\n"
                        "_RATCHET_SUPPRESSIONS = 'ratchet.json'\n"
                        "def migrate(path):\n"
                        "    if path.name == _ESLINT_SUPPRESSIONS:\n"
                        "        migrated = rewrite_eslint(path)\n"
                        "    elif path.name == _RATCHET_SUPPRESSIONS:\n"
                        "        migrated = rewrite_ratchet(path)\n"
                        "    else:\n"
                        "        migrated = rewrite(path)\n"
                        "    return migrated\n",
                    ),
                ),
                focus_path=PurePosixPath("app/migrate.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="literal-match-dispatch",
                title="Use value cases and retain the fallback",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/migrate.py",
                        "def migrate(path):\n"
                        "    match path.name:\n"
                        "        case 'eslint.json':\n"
                        "            return rewrite_eslint(path)\n"
                        "        case 'ratchet.json':\n"
                        "            return rewrite_ratchet(path)\n"
                        "        case _:\n"
                        "            return rewrite(path)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/migrate.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="finite-format-partition",
                scenario="finite-literal-partition",
                title="An implicit format group hides future values",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/formats.py",
                        "from typing import Literal\nFormat = Literal['pcm', 'wav', 'mp3', 'flac']\n"
                        "def encode(value: Format):\n    if value in ('pcm', 'wav'):\n"
                        "        return direct(value)\n    return compressed(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/formats.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-format-cases",
                scenario="finite-literal-partition",
                title="Every format belongs to an explicit case",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/formats.py",
                        "from typing import Literal\nFormat = Literal['pcm', 'wav', 'mp3', 'flac']\n"
                        "def encode(value: Format):\n    match value:\n"
                        "        case 'pcm' | 'wav':\n            return direct(value)\n"
                        "        case 'mp3' | 'flac':\n            return compressed(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/formats.py"),
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
                            "def label():\n    def _label(value):\n        if value == 'one':\n            return 1\n        elif value == 'two':\n            return 2\n        elif value == 'three':\n            return 3\n        else:\n            return 0\n    return _label('one')\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "def label():\n    def _label(value):\n        match value:\n            case 'one':\n                return 1\n            case 'two':\n                return 2\n            case 'three':\n                return 3\n            case _:\n                return 0\n    return _label('one')\n"
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
        findings: list[Diagnostic] = []
        candidates = _candidate_dispatches(context, tree)
        finite_candidates = finite_literal_dispatches(context)
        if (candidates or finite_candidates) and context.session.python_target.has_declared_support_before(
            path, (3, 10)
        ):
            return []
        provenance = context.static_resource_provenance if candidates else None
        findings.extend(
            self._dispatch_diagnostic(context, node, subject, provenance, qualified=qualified)
            for node, subject, qualified in sorted(candidates, key=lambda candidate: candidate[0].lineno)
        )
        existing: set[int] = _owned_dispatch_nodes(context, tree, candidates) if finite_candidates else set()
        findings.extend(
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"Finite Literal dispatch on '{subject}' has an implicit value group; enumerate every value "
                    "with match/case and retain the type checker's exhaustiveness check. "
                    "Use assert_never for an unreachable remainder."
                ),
            )
            for node, subject in finite_candidates
            if id(node) not in existing and not context.suppressions.is_suppressed(node.lineno, self.code)
        )
        return sorted(findings, key=lambda diagnostic: (diagnostic.line, diagnostic.col))

    def _dispatch_diagnostic(
        self,
        context: PythonFileContext,
        node: ast.If,
        subject: str,
        provenance: ResourceProvenance | None,
        *,
        qualified: bool,
    ) -> Diagnostic:
        arms = _dispatch_arms(node, context)
        identity = any(_identity_test(arm.test) for arm in arms)
        fallback = bool(arms[-1].orelse) or len(arms) == 1 or not node.orelse
        return Diagnostic(
            path=context.path,
            line=node.lineno,
            col=node.col_offset + 1,
            code=self.code,
            severity=(
                Severity.ERROR
                if provenance is not None
                and fallback
                and not identity
                and (
                    _blocking_literal_dispatch(context, node, provenance)
                    or (qualified and _blocking_qualified_dispatch(context, node, subject, provenance))
                )
                else Severity.WARNING
            ),
            message=(
                f"Repeated value dispatch on '{subject}'{' with a fallback' if fallback else ''} — consider "
                "match/case; preserve fallback and constant semantics, and review repeated attribute "
                "evaluation, membership versus equality, and guard order."
                + (
                    " Value patterns compare with ==; confirm the subject is a member of this enum before "
                    "replacing identity checks."
                    if identity
                    else ""
                )
            ),
        )


def _owned_dispatch_nodes(
    context: PythonFileContext, tree: ast.Module, candidates: list[tuple[ast.If, str, bool]]
) -> set[int]:
    owned = {id(node) for node, _, _ in candidates}
    if owned:
        for branches in _terminal_sibling_dispatches(tree, node_index=context.node_index):
            if id(branches[0]) in owned:
                owned.update(id(branch) for branch in branches)
    return owned


def _candidate_dispatches(context: PythonFileContext, tree: ast.Module) -> list[tuple[ast.If, str, bool]]:
    constants = _module_constants(tree, node_index=context.node_index)
    continuations: set[int] = set()
    candidates: list[tuple[ast.If, str, bool]] = []
    for node in context.nodes(ast.If):
        if id(node) in continuations:
            continue
        chain = _elif_chain(node, context.source_lines, continuations)
        if len(chain.branches) < (_MIN_TESTS if chain.last.orelse else _MIN_EXPANDED_ARMS):
            continue
        subject = _dispatch_subject(chain.branches, constants)
        if subject is None:
            subject = _expanded_dispatch_subject(chain.branches, constants)
        qualified = False
        if subject is None:
            subject = _qualified_dispatch_subject(chain.branches, context)
            qualified = subject is not None
        if subject is not None:
            candidates.append((node, subject, qualified))
    for branches in _terminal_sibling_dispatches(tree, node_index=context.node_index):
        subject = _expanded_dispatch_subject(branches, constants)
        qualified = False
        if subject is None:
            subject = _qualified_dispatch_subject(branches, context)
            qualified = subject is not None
        if subject is not None:
            candidates.append((branches[0], subject, qualified))
    return candidates


def _qualified_dispatch_subject(branches: list[ast.If], context: PythonFileContext) -> str | None:
    subject: str | None = None
    namespace: str | None = None
    members: set[str] = set()
    bodies: set[tuple[str, ...]] = set()
    for branch in branches:
        match branch.test:
            case ast.Compare(
                left=ast.Name(id=name), ops=[ast.Eq() | ast.Is() as operator], comparators=[ast.Attribute() as value]
            ):
                owner = _subject(value.value)
            case _:
                return None
        body = tuple(ast.dump(statement) for statement in branch.body)
        if owner is None or not _qualified_namespace(value.value, context):
            return None
        if isinstance(operator, ast.Is) and not _proven_enum(value.value, context, branch):
            return None
        if (subject is not None and subject != name) or (namespace is not None and namespace != owner):
            return None
        if value.attr in members or body in bodies:
            return None
        subject, namespace = name, owner
        members.add(value.attr)
        bodies.add(body)
    return subject if len(branches) >= _MIN_TESTS else None


def _qualified_namespace(node: ast.expr, context: PythonFileContext) -> bool:
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    provenance = context.static_resource_provenance
    if provenance.wildcard or provenance.dynamic_namespace or root.id in provenance.mutated:
        return False
    binding = provenance.binding(root.id, root)
    if isinstance(binding, ast.alias):
        return root.id in context.imports.bindings
    return (
        isinstance(binding, ast.ClassDef)
        and isinstance(node, ast.Name)
        and any(
            context.imports.resolved_symbol(base, sources=frozenset({"enum"}))
            in {"Enum", "IntEnum", "StrEnum", "ReprEnum"}
            for base in binding.bases
        )
    )


def _proven_enum(namespace: ast.expr, context: PythonFileContext, at: ast.AST) -> bool:
    contracts = DeclaredContracts(context)
    enum = contracts.class_type(namespace, at=at)
    if enum is None or any(
        isinstance(statement, ast.FunctionDef) and statement.name == "__eq__" for statement in enum.declaration.body
    ):
        return False
    imports = contracts.imports_for(enum.unit)
    bases = enum.declaration.bases
    return bool(bases) and all(imports.resolved_qualified_name(base) in _ENUM_BASES for base in bases)


def _identity_test(test: ast.expr) -> bool:
    return isinstance(test, ast.Compare) and isinstance(test.ops[0], ast.Is)


def _dispatch_arms(node: ast.If, context: PythonFileContext) -> list[ast.If]:
    arms = _elif_chain(node, context.source_lines, set()).branches
    if len(arms) > 1 or node.orelse:
        return arms
    block = next((field for field in _statement_lists(context.parents.get(node, node)) if node in field), [node])
    siblings: list[ast.If] = []
    for statement in block[block.index(node) :]:
        if not isinstance(statement, ast.If) or statement.orelse:
            break
        siblings.append(statement)
    return siblings


def _blocking_qualified_dispatch(
    context: PythonFileContext, node: ast.If, subject: str, provenance: ResourceProvenance
) -> bool:
    if context.dynamic_namespace or not context.session.python_target.has_declared_minimum(context.path, (3, 10)):
        return False
    binding = provenance.binding(subject, node)
    owner = provenance.scope(node)
    return (
        subject not in provenance.external_bindings
        and isinstance(binding, ast.arg | ast.Name)
        and isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef)
        and provenance.scope(binding) is owner
    )


def _blocking_literal_dispatch(context: PythonFileContext, node: ast.If, provenance: ResourceProvenance) -> bool:
    if context.dynamic_namespace or not context.session.python_target.has_declared_minimum(context.path, (3, 10)):
        return False
    chain = _elif_chain(node, context.source_lines, set())
    if not chain.last.orelse:
        return False
    subject: str | None = None
    for branch in chain.branches:
        test = branch.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
        ):
            return False
        if subject is not None and subject != test.left.id:
            return False
        subject = test.left.id
        binding = provenance.binding(subject, test.left)
        owner = provenance.scope(test)
        if (
            subject in provenance.external_bindings
            or not isinstance(binding, ast.arg)
            or not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef)
            or provenance.scope(binding) is not owner
        ):
            return False
    return len(chain.branches) >= _MIN_TESTS


def _terminal_sibling_dispatches(tree: ast.Module, *, node_index: NodeIndex | None = None) -> list[list[ast.If]]:
    candidates: list[list[ast.If]] = []
    for node in walk_ast(tree, index=node_index):
        for field in _statement_lists(node):
            _collect_terminal_siblings(field, candidates)
    return candidates


def _statement_lists(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    match node:
        case (
            ast.Module()
            | ast.FunctionDef()
            | ast.AsyncFunctionDef()
            | ast.ClassDef()
            | ast.With()
            | ast.AsyncWith()
            | ast.ExceptHandler()
            | ast.match_case()
        ):
            return (node.body,)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.Try() | ast.TryStar():
            return node.body, node.orelse, node.finalbody
        case _:
            return ()


def _expanded_dispatch_subject(branches: list[ast.If], constants: dict[str, _Literal]) -> str | None:
    if len(branches) < _MIN_EXPANDED_ARMS:
        return None
    subject: str | None = None
    values: set[_Literal] = set()
    bodies: set[tuple[str, ...]] = set()
    for index, branch in enumerate(branches):
        body = tuple(ast.dump(statement) for statement in branch.body)
        if body in bodies:
            return None
        bodies.add(body)
        selector = _guarded_selector(branch.test, is_last=index == len(branches) - 1)
        if selector is None:
            return None
        parsed = _expanded_selector(selector, constants)
        if parsed is None:
            return None
        candidate, alternatives = parsed
        if (
            candidate in constants
            or (subject is not None and candidate != subject)
            or values.intersection(alternatives)
        ):
            return None
        subject = candidate
        values.update(alternatives)
    return subject


def _expanded_selector(expression: ast.expr, constants: dict[str, _Literal]) -> tuple[str, set[_Literal]] | None:
    match expression:
        case ast.Compare(left=ast.Name(id=name), ops=[ast.Eq()], comparators=[right]):
            value = constants.get(right.id) if isinstance(right, ast.Name) else _literal(right)
            return (name, {value}) if value is not None else None
        case ast.Compare(
            left=ast.Name(id=name),
            ops=[ast.In()],
            comparators=[ast.Tuple(elts=items) | ast.List(elts=items) | ast.Set(elts=items)],
        ):
            if not _MIN_GROUP_VALUES <= len(items) <= _MAX_GROUP_VALUES:
                return None
            values: set[_Literal] = set()
            for item in items:
                if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or item.value in values:
                    return None
                values.add(item.value)
            return name, values
        case _:
            return None


def _module_constants(tree: ast.Module, *, node_index: NodeIndex | None = None) -> dict[str, _Literal]:
    bindings: Counter[str] = Counter()
    for node in walk_ast(tree, index=node_index):
        match node:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.TypeVar(name=name)
                | ast.ParamSpec(name=name)
                | ast.TypeVarTuple(name=name)
            ):
                bindings[name] += 1
            case ast.alias(name=name, asname=alias):
                if name == "*":
                    return {}
                bindings[alias or name.partition(".")[0]] += 1
            case (
                ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
            ):
                if name is not None:
                    bindings[name] += 1
            case ast.Global(names=names) | ast.Nonlocal(names=names):
                bindings.update(names)
            case _:
                pass
    constants: dict[str, _Literal] = {}
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                literal = _literal(value)
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
                literal = _literal(value)
            case _:
                continue
        if literal is not None and bindings[name] == 1:
            constants[name] = literal
    return constants


def _literal(expression: ast.expr) -> _Literal | None:
    match expression:
        case ast.Constant(value=value) if isinstance(value, (str, bytes, int, float)) and not isinstance(value, bool):
            return value
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=value)) if isinstance(
            value, (int, float)
        ) and not isinstance(value, bool):
            return -value if isinstance(expression.op, ast.USub) else value
        case _:
            return None


def _dispatch_subject(branches: list[ast.If], constants: dict[str, _Literal]) -> str | None:
    subject: str | None = None
    values: set[_Literal] = set()
    bodies: set[tuple[str, ...]] = set()
    for branch in branches:
        body = tuple(ast.dump(statement) for statement in branch.body)
        if body in bodies:
            return None
        bodies.add(body)
        match branch.test:
            case ast.Compare(left=left, ops=[ast.Eq()], comparators=[right]):
                candidate = _subject(left)
                value = constants.get(right.id) if isinstance(right, ast.Name) else _literal(right)
            case _:
                return None
        if candidate is None or candidate.partition(".")[0] in constants or value is None or value in values:
            return None
        if subject is not None and candidate != subject:
            return None
        subject = candidate
        values.add(value)
    return subject


def _subject(expression: ast.expr) -> str | None:
    match expression:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            parent = _subject(value)
            return f"{parent}.{attribute}" if parent is not None else None
        case _:
            return None


@dataclass(frozen=True, slots=True)
class _ElifChain:
    branches: list[ast.If]
    last: ast.If


def _elif_chain(node: ast.If, lines: list[str], continuations: set[int]) -> _ElifChain:
    branches = [node]
    current = node
    while len(current.orelse) == 1:
        child = current.orelse[0]
        if not isinstance(child, ast.If) or not lines[child.lineno - 1].lstrip().startswith("elif"):
            break
        continuations.add(id(child))
        branches.append(child)
        current = child
    return _ElifChain(branches=branches, last=current)


def _collect_terminal_siblings(field: list[ast.stmt], candidates: list[list[ast.If]]) -> None:
    branches: list[ast.If] = []
    for statement in field:
        if isinstance(statement, ast.If) and not statement.orelse:
            branches.append(statement)
            continue
        if (
            len(branches) >= _MIN_TESTS
            and isinstance(statement, (ast.Return, ast.Raise))
            and all(branch.body and isinstance(branch.body[-1], (ast.Return, ast.Raise)) for branch in branches)
        ):
            candidates.append(branches)
        branches = []


def _guarded_selector(selector: ast.expr, *, is_last: bool) -> ast.expr | None:
    if isinstance(selector, ast.BoolOp) and isinstance(selector.op, ast.And):
        if not is_last or len(selector.values) != _GUARDED_TEST_PARTS:
            return None
        if any(
            isinstance(node, (ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom))
            for node in walk_ast(selector.values[1])
        ):
            return None
        selector = selector.values[0]
    return selector
