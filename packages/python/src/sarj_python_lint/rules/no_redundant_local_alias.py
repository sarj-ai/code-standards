from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override
import unicodedata

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
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._local_alias_fix import LocalAliasFixes
from sarj_python_lint.rules._suppression_comments import comment_lines


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SUITES = (*_FUNCTIONS, ast.With, ast.AsyncWith)
_UNCERTAIN = (
    *_FUNCTIONS,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.Match,
    ast.Assert,
    ast.BoolOp,
    ast.Global,
    ast.Nonlocal,
    ast.TypeAlias,
)
_INITIALIZERS = (ast.Call, ast.Await, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set)
_REFERENCE_OBSERVERS = frozenset(
    {
        "getrefcount",
        "get_referrers",
        "getattr",
        "attrgetter",
        "TypeAdapter",
        "BaseModel",
        "RootModel",
        "create_model",
        "validate_call",
        "model_rebuild",
        "rebuild_dataclass",
        "new_class",
    }
)
_WORDS = re.compile(r"\w+")
_TYPE_COMMENT = re.compile(r"#\s*type\s*:")
_NAME_PAIR = re.compile(r"\b(?P<target>[A-Za-z_]\w*)[\s)\\]*=[\s(\\]*(?P<source>[A-Za-z_]\w*)\b(?=[\s),;\\]|$)")


@final
class NoRedundantLocalAlias(Rule):
    id = "no-redundant-local-alias"
    code = "SARJ531"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Remove a local alias used only for its matching keyword argument.",
        rationale="An extra local binding makes readers trace two names for one value when the keyword already communicates its role.",
        remediation="Apply the safe fix where offered; otherwise pass the original local to the matching keyword and remove the unannotated alias after review.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Only unannotated, single-target `alias = original` assignments with one binding and one read at `alias=alias` are checked.",
            "The original must be a parameter or an earlier initialized local with one binding; reassignment, deletion, imports, alias chains and uncertain initialization are excluded.",
            "Functions with if statements, loops, try statements, asserts, Boolean short-circuiting, nested scopes, global/nonlocal declarations or type aliases are excluded. Ordinary and async with bodies require ordered enclosing-suite binding evidence.",
            "A conditional expression is admitted only when its test is a bare name bound once as a parameter, and neither local is read within the expression.",
            "Typed aliases, files with type comments, same-scope quoted references and conditional reads of either local are excluded. Captured bindings and module/class aliases are preserved.",
            "Files with wildcard imports, Pydantic imports or references to known namespace readers, dynamic attribute getters or reference-count observers are excluded. Wildcard exports cannot establish builtin identity; computed type names can consume caller-local bindings without a Name read in the AST.",
            "Dynamic class construction and class-valued references to type are excluded. Direct, unshadowed unary type(value) queries and standard-library dataclasses remain supported.",
            "Generated source, stubs and malformed input are excluded; files must compile with normal module execution flags. Arbitrary external frame introspection is not modeled.",
            "Safe fixes are limited to undecorated module functions with one required parameter, an optional existing docstring, a clean single-line alias and a tail return of unshadowed builtin dict with exactly the matching keyword. Recorded dict bindings, visible attribute/subscript writes, setter, mapping-mutator, ior, methodcaller or patch references, unittest imports, `|=` assignments, comments, non-UTF8 encodings, type parameters and visible code-object inspection prevent fixes. Mutation guards also exclude unrelated ordinary mappings, nonmutating methodcaller uses, harmless unittest imports and integer `|=` assignments. Other calls remain diagnostic-only; arbitrary external tracing, reflection and monkeypatching are not modeled.",
            "Readability judgments, multiple reads, positional forwarding and more complex control flow remain outside the contract.",
        ),
        examples=(
            RuleExample(
                example_id="safe-builtin-tail",
                scenario="safe-fix",
                title="A safe builtin mapping return",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "case.py", "def render(item):\n    payload = item\n    return dict(payload=payload)\n"
                    ),
                ),
                focus_path=PurePosixPath("case.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-builtin-tail",
                scenario="safe-fix",
                title="Return the original local in the mapping",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("case.py", "def render(item):\n    return dict(payload=item)\n"),),
                focus_path=PurePosixPath("case.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="keyword-supplies-role",
                title="The keyword supplies the role",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "case.py", "def render(item):\n    payload = item\n    consume(payload=payload)\n"
                    ),
                ),
                focus_path=PurePosixPath("case.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-keyword",
                title="Pass the original local",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("case.py", "def render(item):\n    consume(payload=item)\n"),),
                focus_path=PurePosixPath("case.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if _excluded_file(context):
            return []
        keywords = _matching_keywords(context)
        candidates = _local_assignments(context, set(keywords.values()))
        if not candidates:
            return []
        provenance = context.resource_provenance
        names = {node.targets[0].id for node in candidates if isinstance(node.targets[0], ast.Name)}
        reads = _scope_reads(provenance, names)
        conditional_sources = _conditional_sources(context)
        quoted = _quoted_references(context, provenance, names)
        positions = {statement: i for owner in context.nodes(*_SUITES) for i, statement in enumerate(owner.body)}
        findings: list[Diagnostic] = []
        fixes = LocalAliasFixes(context)
        for assignment in candidates:
            target = assignment.targets[0]
            source = assignment.value
            if not isinstance(target, ast.Name) or not isinstance(source, ast.Name):
                continue
            if (provenance.scope(assignment), target.id) in quoted:
                continue
            use = _single_keyword_read(target, provenance, reads, keywords)
            if use is None:
                continue
            if not _dominates(assignment, use, context.parents, positions):
                continue
            if not _stable_source(source, assignment, provenance, positions, conditional_sources):
                continue
            target_spelling = fixes.spelling(target)
            source_spelling = fixes.spelling(source)
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=target.lineno,
                    col=target.col_offset + 1,
                    code=self.code,
                    message=f"Local `{target_spelling}` only forwards `{source_spelling}` to `{target_spelling}=`; pass `{source_spelling}` directly and remove the alias.",
                    severity=Severity.WARNING,
                    fixes=fixes.for_alias(assignment, use),
                )
            )
        return findings


def _excluded_file(context: PythonFileContext) -> bool:
    if context.path.suffix != ".py" or "=" not in context.source:
        return True
    # This is only a necessary ASCII signal; Unicode identifiers use the AST.
    if context.source.isascii() and not _possible_alias(context.source):
        return True
    return context.tree is None


def _possible_alias(source: str) -> bool:
    # Comments may separate tokens; bypass the text gate instead of rescanning them.
    if "#" in source:
        return True
    forwarded: set[str] = set()
    assigned: set[str] = set()
    for match in _NAME_PAIR.finditer(source):
        target = match.group("target")
        (forwarded if target == match.group("source") else assigned).add(target)
    return not forwarded.isdisjoint(assigned)


def _matching_keywords(context: PythonFileContext) -> dict[ast.Name, str]:
    return {
        node.value: node.value.id
        for node in context.nodes(ast.keyword)
        if isinstance(node.value, ast.Name) and node.arg == node.value.id
    }


def _local_assignments(context: PythonFileContext, names: set[str]) -> list[ast.Assign]:
    candidates = [
        node
        for node in context.nodes(ast.Assign)
        if len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in names
        and isinstance(node.value, ast.Name)
        and node.targets[0].id != node.value.id
    ]
    if not candidates or context.has_wildcard_import:
        return []
    provenance = context.resource_provenance
    blocked = {provenance.scope(node) for node in context.nodes(*_UNCERTAIN)}
    blocked.update(
        provenance.scope(node) for node in context.nodes(ast.IfExp) if not _parameter_choice(node, provenance)
    )
    eligible = [
        node for node in candidates if isinstance(scope := provenance.scope(node), _FUNCTIONS) and scope not in blocked
    ]
    if not eligible or context.dynamic_namespace or _observes_references(context):
        return []
    if context.generated or _has_type_comments(context) or not _compiles(context):
        return []
    return eligible


def _compiles(context: PythonFileContext) -> bool:
    if context.tree is None:
        return False
    try:
        compile(context.tree, str(context.path), "exec")
    except SyntaxError:
        return False
    return True


def _has_type_comments(context: PythonFileContext) -> bool:
    return any(_TYPE_COMMENT.search(comment) for comment in comment_lines(tuple(context.source_lines)).values())


def _parameter_choice(node: ast.IfExp, provenance: ResourceProvenance) -> bool:
    if not isinstance(node.test, ast.Name):
        return False
    bindings = provenance.bindings.get(provenance.scope(node), {}).get(node.test.id, ())
    return len(bindings) == 1 and isinstance(bindings[0], ast.arg)


def _scope_reads(provenance: ResourceProvenance, names: set[str]) -> dict[tuple[ast.AST | None, str], list[ast.Name]]:
    reads: dict[tuple[ast.AST | None, str], list[ast.Name]] = defaultdict(list)
    for name in names:
        for read in provenance.reads.get(name, ()):
            reads[provenance.scope(read), name].append(read)
    return reads


def _conditional_sources(context: PythonFileContext) -> set[tuple[ast.AST | None, str]]:
    provenance = context.resource_provenance
    pending: list[ast.AST] = list(context.nodes(ast.IfExp))
    seen: set[ast.AST] = set()
    names: set[tuple[ast.AST | None, str]] = set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add((provenance.scope(node), node.id))
        pending.extend(children(node))
    return names


def _single_keyword_read(
    target: ast.Name,
    provenance: ResourceProvenance,
    reads: Mapping[tuple[ast.AST | None, str], list[ast.Name]],
    keywords: Mapping[ast.Name, str],
) -> ast.Name | None:
    scope = provenance.scope(target)
    uses = reads.get((scope, target.id), ())
    if provenance.bindings.get(scope, {}).get(target.id) != [target] or len(uses) != 1:
        return None
    [use] = uses
    if keywords.get(use) != target.id or _statement(use, provenance.parents) is None:
        return None
    return use


def _quoted_references(
    context: PythonFileContext,
    provenance: ResourceProvenance,
    names: set[str],
) -> set[tuple[ast.AST | None, str]]:
    references: set[tuple[ast.AST | None, str]] = set()
    for node in context.nodes(ast.Constant):
        if not isinstance(node.value, str):
            continue
        mentioned = _quoted_words(node.value) & names
        if mentioned:
            scope = provenance.scope(node)
            references.update((scope, name) for name in mentioned)
    return references


def _quoted_words(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value)
    if normalized.isascii():
        return set(_WORDS.findall(normalized))
    words: set[str] = set()
    word: list[str] = []
    for character in normalized:
        # A leading letter tests identifier continuation, including combining marks.
        if ("a" + character).isidentifier():
            word.append(character)
        elif word:
            words.add("".join(word))
            word.clear()
    if word:
        words.add("".join(word))
    return words


def _observes_references(context: PythonFileContext) -> bool:
    if _imports_model_namespace(context):
        return True
    for node in context.nodes(ast.Name, ast.Attribute, ast.alias):
        name = _reference_name(node)
        if name in _REFERENCE_OBSERVERS or (name == "type" and not _plain_type_query(node, context)):
            return True
    return False


def _imports_model_namespace(context: PythonFileContext) -> bool:
    for node in context.nodes(ast.Import, ast.ImportFrom):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").partition(".")[0] == "pydantic":
                return True
        elif any(alias.name.partition(".")[0] == "pydantic" for alias in node.names):
            return True
    return False


def _reference_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.name if isinstance(node, ast.alias) else None


def _plain_type_query(node: ast.AST, context: PythonFileContext) -> bool:
    parent = context.parents.get(node)
    return (
        isinstance(node, ast.Name)
        and context.imports.builtin_is_unshadowed("type")
        and isinstance(parent, ast.Call)
        and parent.func is node
        and len(parent.args) == 1
        and not parent.keywords
        and not isinstance(parent.args[0], ast.Starred)
    )


def _statement(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.stmt | None:
    while not isinstance(node, ast.stmt):
        if isinstance(node, (ast.IfExp, ast.BoolOp)) or (parent := parents.get(node)) is None:
            return None
        node = parent
    return node


def _dominates(
    before: ast.stmt,
    at: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
    positions: Mapping[ast.stmt, int],
) -> bool:
    owner = parents.get(before)
    if before not in positions or not isinstance(owner, _SUITES):
        return False
    current = at
    while parents.get(current) is not owner:
        parent = parents.get(current)
        if parent is None:
            return False
        current = parent
    # Exiting a with body can suppress an exception and skip its assignments.
    # Only the same suite or an earlier enclosing-suite statement dominates.
    return isinstance(current, ast.stmt) and current in positions and positions[before] < positions[current]


def _stable_source(
    source: ast.Name,
    at: ast.Assign,
    provenance: ResourceProvenance,
    positions: Mapping[ast.stmt, int],
    conditional_sources: set[tuple[ast.AST | None, str]],
) -> bool:
    scope = provenance.scope(at)
    if (scope, source.id) in conditional_sources:
        return False
    bindings = provenance.bindings.get(scope, {}).get(source.id, ())
    if len(bindings) != 1:
        return False
    [binding] = bindings
    if isinstance(binding, ast.arg):
        return True
    parent = provenance.parents.get(binding)
    if not isinstance(binding, ast.Name) or not isinstance(parent, ast.Assign | ast.AnnAssign):
        return False
    if isinstance(parent, ast.Assign) and (len(parent.targets) != 1 or parent.targets[0] is not binding):
        return False
    return isinstance(parent.value, _INITIALIZERS) and _dominates(parent, at, provenance.parents, positions)
