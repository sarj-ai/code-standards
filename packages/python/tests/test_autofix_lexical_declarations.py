from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.__main__ import check_source
from sarj_python_lint._autofix_docs import private_unescaped_function
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_PATH = Path("app/normalize.py")


@dataclass(frozen=True, slots=True)
class _LexicalCase:
    source: str
    invoke: str


_CASES = (
    pytest.param(
        _LexicalCase(
            'def outer(value):\n    if False:\n        global watched\n    def _normalize(item):\n        """Normalize."""\n        return item\n    watched = None\n    return _normalize(value)\n',
            "watched = Watched()\nassert outer(7) == 7\n",
        ),
        id="dead-global-finalizer",
    ),
    pytest.param(
        _LexicalCase(
            'def outer(value, watched):\n    def run():\n        if False:\n            nonlocal watched\n        def _normalize(item):\n            """Normalize."""\n            return item\n        watched = None\n        return _normalize(value)\n    return run()\n',
            "assert outer(7, Watched()) == 7\n",
        ),
        id="dead-nonlocal-finalizer",
    ),
)


@pytest.mark.parametrize("case", _CASES)
@pytest.mark.parametrize("rule_id", ["no-unnecessary-docstring", "redundant-docstring"])
def test_lexical_declarations_preserve_live_private_metadata_and_actual_finalizer_observers(
    case: _LexicalCase, rule_id: str, tmp_path: Path
) -> None:
    assert check_source([REGISTRY[rule_id]()], _PATH, case.source)
    context = PythonFileContext(_PATH, case.source)
    helper = next(function for function in context.nodes(ast.FunctionDef) if function.name == "_normalize")
    assert not private_unescaped_function(helper, context)
    fixed = fix_source(_PATH, case.source, rule_ids=[rule_id])
    assert fixed == case.source
    oracle = (
        "\nimport json\nimport sys\nevents = []\n"
        "class Watched:\n"
        "    def __del__(self):\n"
        "        helper = sys._getframe(1).f_locals['_normalize']\n"
        "        events.append(helper.__doc__)\n" + case.invoke + "print(json.dumps(events))\n"
    )
    for filename, candidate in (("before.py", case.source), ("after.py", fixed)):
        path = tmp_path / filename
        path.write_text(candidate + oracle)
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout == '["Normalize."]\n'


def test_declarations_outside_the_analyzed_outer_callable_do_not_disable_safe_fixes() -> None:
    source = (
        "def unrelated():\n    global other\n    other = None\n"
        'def outer(value):\n    def _normalize(item):\n        """Normalize."""\n        return item\n    return _normalize(value)\n'
    )
    fixed = fix_source(_PATH, source, rule_ids=["no-unnecessary-docstring"])
    assert fixed == source.replace('        """Normalize."""\n', "")


@pytest.mark.parametrize(
    "declaration", [pytest.param("global other", id="global"), pytest.param("nonlocal item", id="nonlocal")]
)
def test_nested_unexecuted_declarations_are_refused_before_abstract_execution(declaration: str) -> None:
    source = (
        'def outer(value):\n    def _normalize(item):\n        """Normalize."""\n'
        "        def unused():\n            if False:\n                "
        + declaration
        + "\n        return item\n    return _normalize(value)\n"
    )
    assert fix_source(_PATH, source, rule_ids=["no-unnecessary-docstring"]) == source
