from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import check_source
from sarj_python_lint._autofix_docs import private_unescaped_function
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId


_RULE_ID = "no-delete-statement"
_PATH = Path("app/deletion.py")


def _source(body: str, *, name: str = "_ready") -> str:
    return f"def ready():\n    def {name}():\n{textwrap.indent(body, '        ')}\n    return {name}()\n"


def _closed(body: str, *, prefix: str = "") -> bool:
    context = PythonFileContext(_PATH, prefix + _source(body))
    helper = next(function for function in context.nodes(ast.FunctionDef) if function.name == "_ready")
    return private_unescaped_function(helper, context)


@pytest.mark.parametrize("ending", [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")])
@pytest.mark.parametrize(
    ("name", "literal"),
    [
        pytest.param("unused", "None", id="none-result"),
        pytest.param("unused", "True", id="boolean-result"),
        pytest.param("unused", "42", id="integer-result"),
        pytest.param("inutilisé", "'préservé'", id="unicode-source-and-result"),
    ],
)
def test_none_deletion_is_a_real_finding_with_exact_source_and_runtime_preservation(
    name: str, literal: str, ending: str, tmp_path: Path
) -> None:
    source = _source(f"{name} = None\ndel {name}\nreturn {literal}").replace("\n", ending)
    rule = REGISTRY[_RULE_ID]()
    before = check_source([rule], _PATH, source)
    assert len(before) == 1
    assert before[0].code == "SARJ442"
    fixed = fix_source(_PATH, source, rule_ids=[_RULE_ID])
    assert fixed == source.replace(f"        del {name}{ending}", ending)
    assert fix_source(_PATH, fixed, rule_ids=[_RULE_ID]) == fixed
    assert check_source([rule], _PATH, fixed) == []
    before_return = [node.lineno for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Return)]
    after_return = [node.lineno for node in ast.walk(ast.parse(fixed)) if isinstance(node, ast.Return)]
    assert before_return == after_return
    outputs: list[str] = []
    for filename, candidate in (("before.py", source), ("after.py", fixed)):
        path = tmp_path / filename
        path.write_bytes((candidate + "\nvalue = ready()\nprint(type(value).__name__, repr(value))\n").encode("utf-8"))
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


_REFUSED_SOURCES = (
    pytest.param("def ready():\n    unused = None\n    del unused\n    return True\n", id="module-function-api"),
    pytest.param(_source("unused = None\ndel unused\nreturn True", name="ready_inner"), id="public-nested-helper"),
    pytest.param(_source("unused = object()\ndel unused\nreturn True"), id="unknown-value-lifetime"),
    pytest.param(_source("unused = 1\ndel unused\nreturn True"), id="non-none-primitive"),
    pytest.param(_source("unused = None\ndel other\nreturn True"), id="different-target-unbound"),
    pytest.param(_source("unused = None\ndel unused, other\nreturn True"), id="multiple-targets"),
    pytest.param(_source("unused = None\ndel unused.value\nreturn True"), id="attribute-deletion"),
    pytest.param(_source("unused = None\ndel unused[0]\nreturn True"), id="subscript-deletion"),
    pytest.param(_source("unused = None; del unused\nreturn True"), id="shared-physical-line"),
    pytest.param(_source("unused = None\ndel unused  # documented lifetime\nreturn True"), id="trailing-comment"),
    pytest.param(_source("unused = None\n# preserve this rationale\ndel unused\nreturn True"), id="helper-comment"),
    pytest.param(_source("unused = None\ndel unused\nreturn unused"), id="read-after-delete"),
    pytest.param(_source("unused = None\ndel unused\ndel unused\nreturn True"), id="double-deletion"),
    pytest.param(_source("global unused\nunused = None\ndel unused\nreturn True"), id="global-owner"),
    pytest.param(
        "def ready():\n    unused = None\n    def _ready():\n        nonlocal unused\n        unused = None\n        del unused\n        return True\n    return _ready()\n",
        id="nonlocal-owner",
    ),
    pytest.param(
        "def ready(observer):\n    def _ready():\n        unused = None\n        del unused\n        return True\n    observer()\n    return _ready()\n",
        id="external-observer-callout",
    ),
    pytest.param(
        "def ready(value):\n    def _ready():\n        unused = None\n        del unused\n        return True\n    value = None\n    return _ready()\n",
        id="unknown-finalizer-during-parent",
    ),
    pytest.param(
        "def ready():\n    def _ready():\n        unused = None\n        del unused\n        return True\n    failure = 1 / 0\n    return _ready()\n",
        id="traceback-exports-live-helper",
    ),
    pytest.param(
        "def ready():\n    def _ready():\n        unused = None\n        del unused\n        return True\n    return _ready\n",
        id="escaped-callable",
    ),
    pytest.param(
        "async def ready():\n    def _ready():\n        unused = None\n        del unused\n        return True\n    return _ready()\n",
        id="async-containing-frame",
    ),
    pytest.param(
        "def ready():\n    def _ready():\n        unused = None\n        del unused\n        return True\n    yield _ready()\n",
        id="generator-containing-frame",
    ),
    pytest.param(
        "def ready(callback):\n    @callback\n    def _ready():\n        unused = None\n        del unused\n        return True\n    return _ready()\n",
        id="decorated-helper",
    ),
    pytest.param(
        "import sys\ndef ready():\n    def _ready():\n        unused = None\n        del unused\n        return True\n    return _ready(), sys._getframe()\n",
        id="frame-metadata-capability",
    ),
    pytest.param(
        "def ready():\n    def _ready(unused=None):\n        unused = None\n        del unused\n        return True\n    return _ready()\n",
        id="helper-parameters",
    ),
    pytest.param(
        _source("unused = None\ndel unused\nunused = None\nreturn True"), id="reassignment-outside-exact-shape"
    ),
)


@pytest.mark.parametrize("source", _REFUSED_SOURCES)
def test_other_delete_contracts_remain_unchanged(source: str) -> None:
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


@pytest.mark.parametrize(
    ("body", "prefix", "safe"),
    [
        pytest.param("unused = None\ndel unused\nreturn 1", "", True, id="proven-local-none"),
        pytest.param("del unused\nreturn 1", "", False, id="uninitialized-local"),
        pytest.param("unused = None\ndel unused\ndel unused\nreturn 1", "", False, id="tombstone-double-delete"),
        pytest.param("unused = None\ndel unused\nreturn unused", "", False, id="tombstone-read"),
        pytest.param("len = None\ndel len\nreturn len([])", "", False, id="no-builtin-fallback"),
        pytest.param("unused = None\ndel unused\nreturn unused", "unused = 9\n", False, id="no-global-fallback"),
        pytest.param(
            "unused = None\ndef _read():\n    return unused\ndel unused\nreturn _read()",
            "",
            False,
            id="closure-created-before-delete",
        ),
        pytest.param(
            "unused = None\ndel unused\ndef _read():\n    return unused\nreturn _read()",
            "",
            False,
            id="closure-created-after-delete",
        ),
        pytest.param(
            "unused = None\ndel unused\ndef _read(value=unused):\n    return value\nreturn _read()",
            "",
            False,
            id="deleted-closure-default",
        ),
        pytest.param(
            "unused = None\ndel unused\nunused = None\nreturn unused", "", True, id="ordinary-reassignment-after-delete"
        ),
        pytest.param(
            "unused = None\ndel unused\ndef _read():\n    unused = 3\n    return unused\nreturn _read()",
            "",
            True,
            id="child-local-shadows-deleted-name",
        ),
        pytest.param(
            "unused = None\ndef _read():\n    return unused\nresult = _read()\ndel unused\nreturn result",
            "",
            True,
            id="closure-read-before-delete",
        ),
        pytest.param("unused = []\ndel unused\nreturn 1", "", False, id="container-deletion-stays-unsupported"),
        pytest.param("unused = 1\ndel unused\nreturn 1", "", False, id="non-none-deletion-stays-unsupported"),
        pytest.param(
            "global unused\nunused = None\ndel unused\nreturn 1",
            "unused = None\n",
            False,
            id="global-delete-stays-unsupported",
        ),
    ],
)
def test_shared_inert_proof_preserves_deleted_local_lookup_and_closure_semantics(
    body: str, prefix: str, *, safe: bool
) -> None:
    assert _closed(body, prefix=prefix) is safe


def test_external_callback_can_observe_the_live_helper_before_its_call(tmp_path: Path) -> None:
    source = "def ready(observer):\n    def _ready():\n        unused = None\n        del unused\n        return True\n    observer()\n    return _ready()\n"
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source
    oracle = (
        "\nimport dis\nimport sys\n"
        "def observe():\n"
        "    helper = sys._getframe(1).f_locals['_ready']\n"
        "    print(any(instruction.opname.startswith('DELETE_') for instruction in dis.get_instructions(helper)))\n"
        "assert ready(observe) is True\n"
    )
    observations: list[str] = []
    for filename, candidate in (("original.py", source), ("unsafe.py", source.replace("        del unused\n", "\n"))):
        path = tmp_path / filename
        path.write_text(candidate + oracle)
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        observations.append(result.stdout)
    assert observations == ["True\n", "False\n"]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "unused = None\ndef ready():\n    def _ready():\n        if False:\n            global unused\n        unused = None\n        del unused\n        return 1\n    return _ready()\n",
            id="dead-global-in-deleting-helper",
        ),
        pytest.param(
            "def ready():\n    unused = None\n    def _ready():\n        if False:\n            nonlocal unused\n        unused = None\n        del unused\n        return 1\n    return _ready()\n",
            id="dead-nonlocal-in-deleting-helper",
        ),
        pytest.param(
            "unused = None\ndef ready():\n    if False:\n        global unused\n    unused = None\n    del unused\n    def _ready():\n        value = None\n        del value\n        return 1\n    return _ready()\n",
            id="dead-global-in-containing-function",
        ),
        pytest.param(
            "def outer():\n    unused = None\n    def ready():\n        if False:\n            nonlocal unused\n        unused = None\n        del unused\n        def _ready():\n            value = None\n            del value\n            return 1\n        return _ready()\n    return ready()\n",
            id="dead-nonlocal-in-containing-function",
        ),
    ],
)
def test_unexecuted_lexical_declarations_never_prove_an_ordinary_local_delete(source: str) -> None:
    context = PythonFileContext(_PATH, source)
    helper = next(function for function in context.nodes(ast.FunctionDef) if function.name == "_ready")
    assert not private_unescaped_function(helper, context)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


def test_backslash_multiline_deletion_is_left_for_review() -> None:
    source = _source("unused = None\ndel \\\n    unused\nreturn 1")
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


@pytest.mark.parametrize(
    "final_newline", [pytest.param(True, id="final-newline"), pytest.param(False, id="no-final-newline")]
)
def test_existing_blank_lines_and_final_newline_are_preserved(*, final_newline: bool) -> None:
    source = _source("unused = None\n\ndel unused\n\nreturn 1")
    if not final_newline:
        source = source.removesuffix("\n")
    fixed = fix_source(_PATH, source, rule_ids=[_RULE_ID])
    assert fixed == source.replace("        del unused\n", "\n")
    assert fixed.endswith("\n") is final_newline


@pytest.mark.parametrize(
    "separator",
    [
        pytest.param("\v", id="vertical-tab"),
        pytest.param("\f", id="form-feed"),
        pytest.param("\x1c", id="file-separator"),
        pytest.param("\x1d", id="group-separator"),
        pytest.param("\x1e", id="record-separator"),
        pytest.param("\x85", id="next-line"),
        pytest.param("\u2028", id="unicode-line-separator"),
        pytest.param("\u2029", id="unicode-paragraph-separator"),
    ],
)
def test_non_python_line_separators_cannot_shift_owned_source_offsets(separator: str) -> None:
    source = f"label = 'before{separator}after'\n" + _source("unused = None\ndel unused\nreturn 1")
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


@pytest.mark.parametrize(
    "rule_ids",
    [
        pytest.param([], id="excluded-from-selection"),
        pytest.param(["prefer-fstring-over-concat"], id="different-selected-fixer"),
        pytest.param(["no-secret-in-log"], id="selected-rule-with-no-builder"),
    ],
)
def test_rule_selection_cannot_apply_unselected_deletion_fixes(rule_ids: list[RuleId]) -> None:
    source = _source("unused = None\ndel unused\nreturn 1")
    assert fix_source(_PATH, source, rule_ids=rule_ids) == source


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        pytest.param(Path("app/generated/deletion.py"), "", id="generated-path"),
        pytest.param(Path("vendor/deletion.py"), "", id="vendored-path"),
        pytest.param(_PATH, "# Code generated by a tool. DO NOT EDIT.\n", id="generated-header"),
    ],
)
def test_generated_and_vendored_source_never_gets_deletion_fixes(path: Path, prefix: str) -> None:
    source = prefix + _source("unused = None\ndel unused\nreturn 1")
    assert check_source([REGISTRY[_RULE_ID]()], path, source) == []
    assert fix_source(path, source, rule_ids=[_RULE_ID]) == source


def test_exact_rule_suppression_is_respected_before_fixer_planning() -> None:
    source = _source("unused = None\ndel unused  # sarj-noqa: SARJ442 — explicit lifetime contract\nreturn 1")
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source) == []
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


def test_default_safe_fix_selection_includes_the_new_deletion_builder() -> None:
    source = _source("unused = None\ndel unused\nreturn 1")
    assert fix_source(_PATH, source) == source.replace("        del unused\n", "\n")
