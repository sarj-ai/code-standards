from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint._file_context import PythonFileContext


_CAPTURES = (
    "try:\n    action()\nexcept Exception as runtime:\n    pass\n",
    "match source:\n    case runtime:\n        pass\n",
    "match source:\n    case [*runtime]:\n        pass\n",
    "match source:\n    case {**runtime}:\n        pass\n",
)
_CASES = tuple(
    EvaluationCase(
        f"module-capture-{index}",
        Language.PYTHON,
        "import sys as runtime\n" + capture,
    )
    for index, capture in enumerate(_CAPTURES)
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_module_capture_invalidates_import_provenance(case: EvaluationCase) -> None:
    context = PythonFileContext(Path("app.py"), case.source)
    reference = ast.Attribute(value=ast.Name(id="runtime"), attr="modules")
    assert context.module_imports.resolved_qualified_name(reference) is None
    assert context.imports.resolved_qualified_name(reference) is None
    assert case.expected is ExpectedOutcome.NO_MATCH


@pytest.mark.parametrize("capture", _CAPTURES)
def test_local_capture_preserves_module_scope_provenance(capture: str) -> None:
    body = "\n".join(f"    {line}" for line in capture.splitlines())
    context = PythonFileContext(Path("app.py"), f"import sys as runtime\ndef helper(source):\n{body}\n")
    reference = ast.Attribute(value=ast.Name(id="runtime"), attr="modules")
    assert context.module_imports.resolved_qualified_name(reference) == "sys.modules"
    assert context.imports.resolved_qualified_name(reference) is None


@pytest.mark.parametrize("capture", _CAPTURES)
def test_unrelated_capture_preserves_import_provenance(capture: str) -> None:
    context = PythonFileContext(Path("app.py"), f"import sys as runtime\n{capture.replace('runtime', 'other')}")
    reference = ast.Attribute(value=ast.Name(id="runtime"), attr="modules")
    assert context.module_imports.resolved_qualified_name(reference) == "sys.modules"
    assert context.imports.resolved_qualified_name(reference) == "sys.modules"
