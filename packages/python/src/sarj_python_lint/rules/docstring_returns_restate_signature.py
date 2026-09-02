from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

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
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected, stem
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    annotation_tokens,
    decorator_markers,
    identifier_stems,
    restates,
    sections,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_RETURN_SECTIONS = ("Returns", "Return", "Yields", "Yield")
_MIN_FIXED_TUPLE_ARITY = 2
_GENERATOR_ARITY = 3
_GENERATOR_RETURN_INDEX = 2
_POSITION_NAMES_RE = re.compile(r"\(\s*(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*,?\s*\)")
_RETURN_HEADER_RE = re.compile(r"^[ \t]*(Returns?|Yields?)[ \t]*:[ \t]*$", re.MULTILINE)
_TYPED_RESULT_RE = re.compile(r"^\s*[A-Za-z_][\w.\[\], |]*\s*:\s*\S", re.MULTILINE)
_RESULT_SEMANTIC_RE = re.compile(
    r"\b(if|when|unless|otherwise|whether|all|current|existing|available|empty|nonempty|non-empty|"
    r"unique|sorted|ordered|first|last|latest|newest|subset|lazy|lazily|eager|eagerly)\b|"
    r"\bmap(?:ping)?\b.+\bto\b",
    re.IGNORECASE,
)

_RUNTIME_DOC_DECORATORS = (
    (frozenset({"agents"}), "function_tool"),
    (frozenset({"click"}), "command"),
    (frozenset({"typer"}), "command"),
)
_OVERLOAD_MODULES = frozenset({"typing", "typing_extensions"})
_GENERATOR_TYPES = frozenset({"AsyncGenerator", "AsyncIterable", "AsyncIterator", "Generator", "Iterable", "Iterator"})
_BROAD_RETURN_TYPES = frozenset({"Any", "object"})

# Identity semantics: whether the value handed back is a FRESH object or the
# receiver itself is the one fact `-> Self` and `-> Foo` cannot carry, and the
# words that state it (`new`, `copy`, `same`) are stopwords for the restatement
# tokenizer, so the block reads as pure ceremony without this.
_IDENTITY_RE = re.compile(
    r"\b(?:new|copy|copies|copied|clone[ds]?|fresh|same|itself|self|shallow|deep|"
    r"in[- ]place|unchanged|original)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _ReturnSection:
    name: str
    block: str


def _return_section(docstring: str) -> _ReturnSection | None:
    headers = list(_RETURN_HEADER_RE.finditer(docstring))
    if len(headers) != 1:
        return None
    found = sections(docstring)
    name = headers[0].group(1)
    block = found.get(name)
    return _ReturnSection(name, block) if block is not None else None


def _names_fixed_tuple_positions(block: str, annotation: ast.expr | None) -> bool:
    elements = _fixed_tuple_elements(annotation)
    if not elements:
        return False
    rendered_elements = tuple(re.sub(r"\W", "", ast.unparse(element)).casefold() for element in elements)
    for match in _POSITION_NAMES_RE.finditer(block):
        names = tuple(part.strip() for part in match.group("names").split(","))
        if len(names) != len(elements):
            continue
        # `(int, str)` merely repeats `tuple[int, str]`; at least one name must
        # add a positional role that the corresponding element type cannot say.
        if any(
            re.sub(r"\W", "", name).casefold() != rendered
            for name, rendered in zip(names, rendered_elements, strict=True)
        ):
            return True
    return False


def _fixed_tuple_elements(annotation: ast.expr | None) -> tuple[ast.expr, ...]:
    if not isinstance(annotation, ast.Subscript):
        return ()
    container = annotation.value
    if not (
        (isinstance(container, ast.Name) and container.id in {"tuple", "Tuple"})
        or (isinstance(container, ast.Attribute) and container.attr == "Tuple")
    ):
        return ()
    if not isinstance(annotation.slice, ast.Tuple) or len(annotation.slice.elts) < _MIN_FIXED_TUPLE_ARITY:
        return ()
    elements = tuple(annotation.slice.elts)
    if any(isinstance(element, ast.Starred) or ast.unparse(element) == "..." for element in elements):
        return ()
    return elements


class DocstringReturnsRestateSignature(Rule):
    id: str = "docstring-returns-restate-signature"
    code: str = "SARJ087"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Google-style Returns and Yields documentation must add facts beyond the corresponding annotated result type.",
        rationale=(
            "Repeating a result type or callable name adds noise and can drift without explaining identity, polarity, "
            "cardinality, ordering, ownership, or empty-result behavior."
        ),
        remediation=(
            "Remove only the redundant Returns or Yields section. Keep identity, ownership, units, ordering, shape, "
            "laziness, sentinel values, and success conditions in the public docstring."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule reads a single Google-style return or yield section and requires an informative explicit result annotation.",
            "Names that document the positions of a fixed tuple return are treated as semantic information.",
            "Generated files, overloads, runtime-consumed docstrings, typed sections, protected facts, result conditions, identity semantics, and whole-docstring restatements owned by SARJ050 are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="return-restates-signature",
                title="Return description repeats the signature",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/lines.py",
                        'def get_line_length(line: list[str]) -> int:\n    """Measure a rendered line.\n\n    Returns:\n        The line length.\n    """\n    return len(line)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/lines.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="return-documents-semantics",
                title="Return description records semantics",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/lines.py",
                        'def get_line_length(line: list[str]) -> int:\n    """Measure a rendered line.\n\n    Returns:\n        The number of render fragments queued for output.\n    """\n    return len(line)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/lines.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._walk(tree, None, path, ImportIndex.from_tree(tree), diags)
        return sorted(diags, key=lambda diag: diag.line)

    def _walk(
        self,
        node: ast.AST,
        class_name: str | None,
        path: Path,
        imports: ImportIndex,
        diags: list[Diagnostic],
    ) -> None:
        for child in children(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self._check_function(child, class_name, path, imports, diags)
                self._walk(child, class_name, path, imports, diags)
            elif isinstance(child, ast.ClassDef):
                self._walk(child, child.name, path, imports, diags)
            else:
                self._walk(child, class_name, path, imports, diags)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        imports: ImportIndex,
        diags: list[Diagnostic],
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring:
            return
        section = _return_section(docstring)
        if section is None:
            return
        block = section.block
        if (
            VALUE_MARKER_RE.search(block)
            or is_protected(block)
            or _IDENTITY_RE.search(block)
            or _RESULT_SEMANTIC_RE.search(block)
            or _TYPED_RESULT_RE.search(block)
        ):
            return
        if _is_runtime_consumed_or_overload(node, imports):
            return
        annotation = _result_annotation(node, section.name)
        if annotation is None or _is_broad_annotation(annotation):
            return
        if _names_fixed_tuple_positions(block, annotation):
            return
        stems = _result_stems(node, class_name, annotation)
        # The whole-docstring case is SARJ050's; reporting it here too would
        # make one deletion look like two findings.
        if restates(docstring, stems):
            return
        if not restates(block, stems):
            return
        expr = node.body[0]
        diags.append(
            Diagnostic(
                path=path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=(
                    f"`{node.name}` {section.name} section only repeats its callable name or annotated result type; "
                    "remove that section or document result semantics not expressed by the signature."
                ),
                severity=Severity.WARNING,
            )
        )


def _result_stems(
    node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None, annotation: ast.expr
) -> set[str]:
    known = identifier_stems(node.name) | {stem(token) for token in annotation_tokens(annotation)}
    if class_name is not None:
        known |= identifier_stems(class_name)
    return known


def _result_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef, section_name: str) -> ast.expr | None:
    annotation = node.returns
    if annotation is None:
        return None
    is_generator = _contains_yield(node)
    wants_yield = section_name.startswith("Yield")
    if wants_yield and not is_generator:
        return None
    if not is_generator:
        return annotation if not wants_yield else None
    container = _annotation_name(annotation)
    elements = _subscript_elements(annotation)
    if container not in _GENERATOR_TYPES or not elements:
        return None
    if wants_yield:
        return elements[0]
    return elements[_GENERATOR_RETURN_INDEX] if container == "Generator" and len(elements) == _GENERATOR_ARITY else None


def _annotation_name(annotation: ast.expr) -> str | None:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name):
        return target.id
    return target.attr if isinstance(target, ast.Attribute) else None


def _subscript_elements(annotation: ast.expr) -> list[ast.expr]:
    if not isinstance(annotation, ast.Subscript):
        return []
    return list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]


def _contains_yield(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    pending: list[ast.AST] = list(node.body)
    while pending:
        current = pending.pop()
        if isinstance(current, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(children(current))
    return False


def _is_broad_annotation(annotation: ast.expr) -> bool:
    return _annotation_name(annotation) in _BROAD_RETURN_TYPES


def _is_runtime_consumed_or_overload(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
        return True
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if imports.resolves(target, sources=_OVERLOAD_MODULES, symbol="overload"):
            return True
        if any(imports.resolves(target, sources=sources, symbol=symbol) for sources, symbol in _RUNTIME_DOC_DECORATORS):
            return True
    return False
