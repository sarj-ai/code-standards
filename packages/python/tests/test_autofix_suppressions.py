from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sarj_python_lint.autofix import fix_paths, fix_source
from sarj_python_lint.rules import REGISTRY


_RULE = "no-file-level-escape-hatch-suppression"
_PATH = Path("app/limits.py")
_DIRECTIVE = "# ruff: file-ignore[banned-api]"


@pytest.mark.parametrize(
    "directive",
    ["# ruff: noqa: TID251", _DIRECTIVE, "# RUFF: FILE-IGNORE[ TID251 ]"],
    ids=("legacy-code", "modern-name", "modern-code-case"),
)
@pytest.mark.parametrize("literal", ["3", "True", "None", "'limit'", "b'limit'", "3.5", "3j"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_no_api_can_hide_in_primitive_name_assignments(directive: str, literal: str, newline: str) -> None:
    source = f"{directive}{newline}MAX_RETRIES = {literal}{newline}"
    expected = f"{newline}MAX_RETRIES = {literal}{newline}"
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 1
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == expected
    assert ast.dump(ast.parse(source), include_attributes=True) == ast.dump(ast.parse(fixed), include_attributes=True)
    assert compile(source, str(_PATH), "exec", dont_inherit=True) == compile(
        fixed, str(_PATH), "exec", dont_inherit=True
    )
    assert not REGISTRY[_RULE]().check(_PATH, fixed)
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed
    assert fix_source(_PATH, source, rule_ids=[]) == source


@pytest.mark.parametrize(
    "body",
    [
        "import os\n",
        "from os import environ\n",
        "VALUE = run()\n",
        "VALUE = os.environ\n",
        "VALUE: int = 3\n",
        "VALUE = [3]\n",
        "VALUE = (3,)\n",
        "VALUE = {'a': 3}\n",
        "VALUE = 1 + 2\n",
        "VALUE = -3\n",
        "VALUE = ...\n",
        "VALUE = OTHER = 3\n",
        "VALUE[0] = 3\n",
        "def value():\n    return 3\n",
        "class Value:\n    code = 3\n",
        "if True:\n    VALUE = 3\n",
        '"""Module limits."""\nVALUE = 3\n',
        "VALUE = 3\n# fmt: skip\n",
        "",
    ],
    ids=(
        "import",
        "from-import",
        "call",
        "attribute",
        "annotation",
        "list",
        "tuple",
        "dictionary",
        "arithmetic",
        "unary-expression",
        "ellipsis",
        "multiple-bindings",
        "subscript-target",
        "function",
        "class",
        "conditional",
        "docstring",
        "other-directive",
        "no-assignments",
    ),
)
def test_any_unproven_api_or_directive_context_stays_manual(body: str) -> None:
    source = f"{_DIRECTIVE}\n{body}"
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 1
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize(
    "directive",
    [
        "# ruff: noqa: TID251, F401",
        "# ruff: file-ignore[banned-api, unused-import]",
        "# ruff: file-ignore[banned-api] -- maintained boundary",
        "# ruff: noqa: TID251 # sarj-noqa: SARJ054 -- maintained boundary",
    ],
    ids=("multiple-codes", "multiple-names", "existing-reason", "sarj-suppression"),
)
def test_selector_lists_and_existing_reasons_are_preserved(directive: str) -> None:
    source = f"{directive}\nMAX_RETRIES = 3\n"
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 1
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"], ids=("utf8", "utf8-bom"))
@pytest.mark.parametrize("final_newline", [True, False], ids=("newline", "eof"))
def test_file_writer_preserves_bom_endings_unicode_and_eof(
    tmp_path: Path, newline: str, bom: bytes, *, final_newline: bool
) -> None:
    suffix = newline if final_newline else ""
    path = tmp_path / "limits.py"
    source = f"{_DIRECTIVE}{newline}上限 = 3{suffix}"
    path.write_bytes(bom + source.encode("utf-8"))
    assert fix_paths([path], rule_ids=[_RULE]) == 1
    assert path.read_bytes() == bom + f"{newline}上限 = 3{suffix}".encode()
    assert fix_paths([path], rule_ids=[_RULE]) == 0
