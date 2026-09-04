from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

import pytest

import sarj_python_lint.__main__ as cli
from sarj_python_lint.rule_base import AutofixPolicy, RuleExample, Severity
from sarj_python_lint.rules.no_dunder_all import NoDunderAll


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_PUBLIC_EXAMPLES = NoDunderAll.public_examples()


def _check(source: str, path: str = "pkg/__init__.py") -> list[Diagnostic]:
    return NoDunderAll().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        '__all__ = ["Widget"]',
        '__all__: tuple[str, ...] = ("Widget",)',
        '__all__ += ["Widget"]',
        '(__all__ := ["Widget"])',
        "for __all__ in exports:\n    pass",
        "async for __all__ in exports:\n    pass",
        "with exports() as __all__:\n    pass",
        "async with exports() as __all__:\n    pass",
        "try:\n    pass\nexcept Error as __all__:\n    pass",
        "try:\n    pass\nexcept* Error as __all__:\n    pass",
        "match value:\n    case __all__:\n        pass",
        "match value:\n    case [*__all__]:\n        pass",
        "match value:\n    case {**__all__}:\n        pass",
        "type __all__ = tuple[str, ...]",
        "import exports as __all__",
        "import __all__.helpers",
        "from .exports import __all__",
        "from .exports import names as __all__",
        "def __all__(): ...",
        "async def __all__(): ...",
        "class __all__: ...",
        "del __all__",
    ],
    ids=(
        "assign",
        "annotated-assign",
        "augmented-assign",
        "named-expression",
        "for-target",
        "async-for-target",
        "with-target",
        "async-with-target",
        "except-target",
        "except-star-target",
        "match-as",
        "match-star",
        "match-mapping-rest",
        "type-alias",
        "import-alias",
        "dotted-import",
        "from-import",
        "from-import-alias",
        "function-definition",
        "async-function-definition",
        "class-definition",
        "delete",
    ),
)
def test_rejects_module_owned_bindings(source: str) -> None:
    [finding] = _check(source)

    assert finding.code == "SARJ438"
    assert finding.severity is Severity.ERROR
    assert "module-owned `__all__`" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        '__all__.append("Widget")',
        '__all__.extend(["Widget"])',
        '__all__.insert(0, "Widget")',
        '__all__.remove("Widget")',
        "__all__.pop()",
        "__all__.clear()",
        "__all__.sort()",
        "__all__.reverse()",
        'result = __all__.append("Widget")',
        'if __all__.extend(["Widget"]):\n    pass',
        '__all__[0] = "Widget"',
        '__all__[:] += ["Widget"]',
        "del __all__[0]",
        "__all__.flag = True",
    ],
    ids=(
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "sort",
        "reverse",
        "nested-call",
        "conditional-call",
        "item-store",
        "item-augmented-store",
        "item-delete",
        "attribute-store",
    ),
)
def test_rejects_provable_module_mutations(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'if enabled:\n    __all__ = ["Widget"]\nelse:\n    __all__ = []',
        "for item in values:\n    __all__ = [item]\nelse:\n    __all__ = []",
        'while enabled:\n    __all__ = ["Widget"]',
        'with context():\n    __all__ = ["Widget"]',
        'try:\n    __all__ = ["Widget"]\nexcept ImportError:\n    __all__ = []\nelse:\n    __all__ = []\nfinally:\n    __all__ = []',
        'match mode:\n    case "public":\n        __all__ = ["Widget"]',
    ],
    ids=("if-else", "for-else", "while", "with", "try-branches", "match-body"),
)
def test_traverses_module_control_flow(source: str) -> None:
    assert _check(source)


@pytest.mark.parametrize(
    "source",
    [
        "from .models import Widget as Widget",
        "_all__ = []",
        "__all_ = []",
        "ALL = []",
        "obj.__all__ = []",
        'mapping["__all__"] = []',
        "call(__all__=[])",
        "def build(__all__):\n    return __all__",
        "factory = lambda __all__: __all__",
        'def build():\n    __all__ = ["local"]',
        'class Namespace:\n    __all__ = ["local"]',
        "[value for __all__ in values]",
        "from .exports import __all__ as exports",
        "copy = __all__.copy()",
        'count = __all__.count("Widget")',
        'position = __all__.index("Widget")',
        "alias = __all__",
        "consume(__all__)",
        "other.__all__.append('Widget')",
        'setattr(globals(), "__all__", [])',
    ],
    ids=(
        "explicit-reexport",
        "leading-single-underscore",
        "trailing-single-underscore",
        "uppercase-name",
        "other-object-attribute",
        "mapping-key",
        "keyword-argument",
        "function-parameter",
        "lambda-parameter",
        "function-local",
        "class-local",
        "comprehension-target",
        "import-aliased-away",
        "copy-read",
        "count-read",
        "index-read",
        "bare-read",
        "argument-read",
        "other-object-mutation",
        "dynamic-construction",
    ),
)
def test_allows_non_module_bindings_and_reads(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "@(__all__ := decorator)\ndef build():\n    pass",
        "def build(value=(__all__ := [])):\n    pass",
        "class Namespace((__all__ := Base)):\n    pass",
        "[(__all__ := value) for value in values]",
    ],
    ids=("decorator", "default", "class-base", "comprehension-walrus"),
)
def test_rejects_bindings_in_module_evaluated_expressions(source: str) -> None:
    assert len(_check(source)) == 1


def test_rejects_explicit_global_writes_but_not_ordinary_locals() -> None:
    source = """
def update():
    global __all__
    __all__ = ["Widget"]

def local():
    __all__ = ["local"]
"""

    [finding] = _check(source)

    assert (finding.line, finding.col) == (4, 5)


def test_reports_one_exact_location_per_statement_in_source_order() -> None:
    source = """
if (__all__ := []):
    (__all__, __all__) = ([], [])
else:
    result = (__all__.append("A"), __all__.extend(["B"]))
"""

    findings = _check(source)

    assert [(finding.line, finding.col) for finding in findings] == [(2, 5), (3, 6), (5, 15)]


def test_multiline_import_reports_the_alias_line() -> None:
    source = "from .exports import (\n    names as __all__,\n)\n"

    [finding] = _check(source)

    assert (finding.line, finding.col) == (2, 5)


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    assert len(NoDunderAll().check(Path(focus.path), focus.source)) == example.expected_count


def test_generated_malformed_non_python_and_stub_sources_are_ignored() -> None:
    generated = '# Generated by schema compiler. Do not edit.\n__all__ = ["Widget"]\n'

    assert _check(generated) == []
    assert _check('__all__ = ["Widget"') == []
    assert _check('__all__ = ["Widget"]', "module.txt") == []
    assert _check('__all__ = ["Widget"]', "module.pyi") == []


def test_comments_and_strings_are_ignored() -> None:
    assert _check('TEXT = "__all__ = [\\"Widget\\"]"\n# __all__ = ["Widget"]\n') == []


def test_rule_has_no_autofix() -> None:
    documentation = NoDunderAll.documentation

    assert documentation is not None
    assert documentation.autofix is AutofixPolicy.NONE


def test_repeated_checks_are_deterministic() -> None:
    source = '__all__ = ["A"]\nif enabled:\n    __all__.append("B")\n'
    rule = NoDunderAll()

    assert rule.check(Path("pkg/__init__.py"), source) == rule.check(Path("pkg/__init__.py"), source)


def test_large_declaration_is_fast() -> None:
    source = f"__all__ = {['Widget'] * 5_000!r}"
    started = perf_counter()

    findings = _check(source)

    assert len(findings) == 1
    assert perf_counter() - started < 1.0


def test_cli_honors_exact_code_suppression_on_multiline_alias(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "__init__.py"
    target.write_text(
        "from .exports import (\n    names as __all__,  # sarj-noqa: SARJ438 — compatibility boundary\n)\n",
        encoding="utf-8",
    )

    assert cli.main(["check", "--rule", NoDunderAll.id, str(target)]) == 0
    assert not capsys.readouterr().out


def test_cli_wrong_code_does_not_suppress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "__init__.py"
    target.write_text('__all__ = ["Widget"]  # sarj-noqa: SARJ437 — unrelated\n', encoding="utf-8")

    assert cli.main(["check", "--rule", NoDunderAll.id, str(target)]) == 1
    assert "SARJ438" in capsys.readouterr().out
