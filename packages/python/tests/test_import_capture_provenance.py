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


@pytest.mark.parametrize("static", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_runtime_import_proofs_keep_same_named_alias_scopes_separate(*, static: bool, reverse: bool) -> None:
    source = """
def first():
    import re as runtime
    return runtime.compile('x')
def shadowed(runtime):
    return runtime.compile('x')
def direct():
    from re import compile as runtime
    return runtime('x')
def last():
    import re as runtime
    return runtime.compile('x')
"""
    context = PythonFileContext(Path("app.py"), source)
    provenance = context.static_resource_provenance if static else context.resource_provenance
    queries = sorted(context.nodes(ast.Call), key=lambda call: call.lineno, reverse=reverse)
    expected = ["re.compile", None, "re.compile", "re.compile"]
    if reverse:
        expected.reverse()

    assert [provenance.runtime_import_name(call.func) for call in queries] == expected
    assert [provenance.runtime_import_name(call.func) for call in queries] == expected


def test_lexical_read_queries_do_not_supply_runtime_import_proofs() -> None:
    source = (
        "import sys as runtime\n"
        "def replace():\n"
        "    global runtime\n"
        "    runtime = provider\n"
        "def use():\n"
        "    return runtime.getdefaultencoding()\n"
    )
    context = PythonFileContext(Path("app.py"), source)
    reference = context.nodes(ast.Call)[0].func
    assert isinstance(reference, ast.Attribute)
    assert isinstance(reference.value, ast.Name)
    provenance = context.static_resource_provenance

    assert isinstance(provenance.binding("runtime", reference), ast.alias)
    assert provenance.unescaped(reference.value, reference)
    assert provenance.runtime_binding("runtime", reference) is None
    assert provenance.runtime_import_name(reference) is None


def test_runtime_import_checks_class_skipping_reads_after_a_lexical_query() -> None:
    source = (
        "import sys as runtime\n"
        "class Container:\n"
        "    import re as runtime\n"
        "    def use(self):\n"
        "        return runtime.getdefaultencoding()\n"
        "    def expose(self):\n"
        "        return forward(runtime)\n"
    )
    context = PythonFileContext(Path("app.py"), source)
    reference = min(context.nodes(ast.Call), key=lambda call: call.lineno).func
    assert isinstance(reference, ast.Attribute)
    assert isinstance(reference.value, ast.Name)
    provenance = context.static_resource_provenance

    assert not provenance.unescaped(reference.value, reference)
    binding = provenance.runtime_binding("runtime", reference)
    assert isinstance(binding, ast.alias)
    assert binding.name == "sys"
    assert provenance.runtime_import_name(reference) is None


@pytest.mark.parametrize("escaped", [False, True])
def test_import_read_safety_is_specific_to_each_source(*, escaped: bool) -> None:
    source = "import sys as runtime\ndef use():\n    return runtime.getdefaultencoding()\n"
    if escaped:
        source += "def expose():\n    return [runtime]\n"
    context = PythonFileContext(Path("app.py"), source)
    reference = context.nodes(ast.Call)[0].func
    provenance = context.static_resource_provenance

    assert provenance.imported(reference, "sys.getdefaultencoding") is (not escaped)
    assert provenance.imported(reference, "sys.getdefaultencoding") is (not escaped)
    assert provenance.runtime_import_name(reference) == (None if escaped else "sys.getdefaultencoding")
