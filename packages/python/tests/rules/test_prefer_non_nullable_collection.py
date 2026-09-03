from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import RuleCategory, Severity, is_suppressed
from sarj_python_lint.rules.prefer_non_nullable_collection import (
    PreferNonNullableCollection,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


PATH = Path("app/resolver.py")


def _check(source: str, path: Path = PATH) -> list[Diagnostic]:
    return PreferNonNullableCollection().check(path, source)


_PUBLIC_EXAMPLES = PreferNonNullableCollection.public_examples()


def _path_id(path: Path) -> str:
    return path.as_posix()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, Path(focus.path))) == example.expected_count
    compile(focus.source, str(focus.path), "exec")


def test_rule_identity_and_ui_match_advisory_list_boundary() -> None:
    rule = PreferNonNullableCollection()

    assert rule.code == "SARJ082"
    assert rule.id == "prefer-non-nullable-collection"
    assert rule.documentation is not None
    assert rule.documentation.category is RuleCategory.MAINTAINABILITY
    assert "nullable list parameters" in rule.description


@pytest.mark.parametrize(
    "source",
    [
        "def resolve(items: list[str] | None = None):\n    return items or []\n",
        "def resolve(items: None | list[str] = None):\n    return items or []\n",
        "from typing import List, Optional\ndef resolve(items: Optional[List[str]] = None):\n    return items or []\n",
        "import typing\ndef resolve(items: typing.Union[typing.List[str], None] = None):\n    return items or []\n",
        "def resolve(items: 'list[str] | None' = None):\n    return items or []\n",
        "def resolve(*, items: list[str] | None = None):\n    return items or list()\n",
        "import builtins\ndef resolve(items: builtins.list[str] | None = None):\n    return items or builtins.list()\n",
        "def resolve(items: list[str] | None = None):\n    items = items or []\n    return sorted(items)\n",
        "class Resolver:\n    def __init__(self, items: list[str] | None = None):\n        self.items = items or []\n",
        "class Resolver(object):\n    def __init__(self, items: list[str] | None = None):\n        self.items = items or []\n",
        "from typing import Annotated\ndef resolve(items: Annotated[list[str] | None, 'input'] = None):\n    return items or []\n",
    ],
)
def test_flags_proven_single_empty_list_collapse(source: str) -> None:
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ082"
    assert diagnostics[0].severity is Severity.WARNING
    assert "identity or mutation" in diagnostics[0].message


@pytest.mark.parametrize(
    "source",
    [
        "def resolve(items: list[str]):\n    return items\n",
        "def resolve(items: list[str] | None):\n    return items or []\n",
        "def resolve(items: set[str] | None = None):\n    return items or []\n",
        "def resolve(items: str | list[str] | None = None):\n    return items or []\n",
        "def resolve(items: list[str] | None = None):\n    return downstream(items)\n",
        "def resolve(items: list[str] | None = None):\n    audit(items)\n    return items or []\n",
        "def resolve(items: list[str] | None = None):\n    return items or [default]\n",
        "def resolve(items: list[str] | None = None):\n    if items is None:\n        items = []\n    return items\n",
        "def resolve(items: list[str] | None = None):\n    items = [] if items is None else items\n    return items\n",
        "def resolve(items: list[str] | None = None):\n    normalized = items or []\n    def omitted():\n        return items is None\n    return normalized, omitted\n",
        "@app.get('/')\ndef resolve(items: list[str] | None = None):\n    return items or []\n",
        "@click.command()\ndef resolve(items: list[str] | None = None):\n    return items or []\n",
        "class Resolver(FrameworkBase):\n    def __init__(self, items: list[str] | None = None):\n        self.items = items or []\n",
        "class list: ...\ndef resolve(items: list[str] | None = None):\n    return items or []\n",
        "from vendor import Optional\ndef resolve(items: Optional[list[str]] = None):\n    return items or []\n",
        "from vendor import List\ndef resolve(items: List[str] | None = None):\n    return items or []\n",
        "def list(): ...\ndef resolve(items: list[str] | None = None):\n    return items or list()\n",
        "from fake import *\ndef resolve(items: list[str] | None = None):\n    return items or []\n",
    ],
)
def test_allows_unproven_or_semantically_distinct_cases(source: str) -> None:
    assert _check(source) == []


def test_real_import_aliases_are_recognized() -> None:
    source = (
        "from typing import List as Items, Optional as Maybe\n"
        "def resolve(items: Maybe[Items[str]] = None):\n"
        "    return items or []\n"
    )

    assert len(_check(source)) == 1


def test_rebound_typing_import_abstains() -> None:
    source = (
        "from typing import Optional\n"
        "Optional = vendor.Optional\n"
        "def resolve(items: Optional[list[str]] = None):\n"
        "    return items or []\n"
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        Path("tests/test_resolver.py"),
        Path("python/common/testing/builders.py"),
        Path("src/generated/client.py"),
        Path("src/vendor/client.py"),
    ],
    ids=_path_id,
)
def test_skips_nonproduction_paths(path: Path) -> None:
    assert _check("def resolve(items: list[str] | None = None):\n    return items or []\n", path) == []


@pytest.mark.parametrize(
    "header",
    [
        "# Generated by protoc. Do not edit.\n",
        '"""Code generated by Speakeasy. DO NOT EDIT."""\n',
    ],
)
def test_skips_generated_source(header: str) -> None:
    assert _check(f"{header}def resolve(items: list[str] | None = None):\n    return items or []\n") == []


def test_suppression_is_recognized() -> None:
    source = (
        "def resolve(items: list[str] | None = None):  "
        "# sarj-noqa: SARJ082 — None remains accepted for compatibility\n"
        "    return items or []\n"
    )
    diagnostic = _check(source)[0]

    assert is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code)


@pytest.mark.parametrize("source", ["", "# comment\n", "def broken( -> None:\n"])
def test_allows_empty_or_invalid_source(source: str) -> None:
    assert _check(source) == []
