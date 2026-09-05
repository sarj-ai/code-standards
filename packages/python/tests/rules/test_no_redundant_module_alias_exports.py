from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_redundant_module_alias_exports import NoRedundantModuleAliasExports


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "legacy/settings.py") -> list[Diagnostic]:
    return NoRedundantModuleAliasExports().check(Path(path), source)


_EXAMPLES = NoRedundantModuleAliasExports.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_documentation_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


@pytest.mark.parametrize(
    "module_import",
    [
        "import canonical.settings as _canonical",
        "from canonical import settings as _canonical",
    ],
)
def test_warns_once_for_exact_forwarding_ladder(module_import: str) -> None:
    diagnostics = _check(
        f"import sys\n\n{module_import}\n\nThing = _canonical.Thing\nload = _canonical.load\n"
        "sys.modules[__name__] = _canonical\n"
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ440"
    assert diagnostics[0].severity.value == "error"
    assert diagnostics[0].line == 5
    assert diagnostics[0].col == 1


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nfrom canonical import settings as c\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Other\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing: object = c.Thing\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = Other = c.Thing\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing, Other = c.Thing\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.make()\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing.attr\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nif ready:\n    Thing = c.Thing\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nif ready:\n    sys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = c\nrun()\n",
        "import sys as system\nfrom canonical import settings as c\nThing = c.Thing\nsystem.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings\nThing = settings.Thing\nsys.modules[__name__] = settings\n",
        "import sys\nfrom canonical import *\nThing = c.Thing\nsys.modules[__name__] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules['legacy.settings'] = c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = other\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = c\ndel c\n",
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nprint(Thing)\nsys.modules[__name__] = c\n",
        "if:",
        "# Generated file; do not edit\nimport sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = c\n",
    ],
)
def test_excludes_non_pure_or_ambiguous_modules(source: str) -> None:
    assert _check(source) == []


def test_stub_files_are_excluded() -> None:
    source = "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = c\n"
    assert _check(source, "legacy/settings.pyi") == []


def test_module_docstring_is_allowed() -> None:
    source = (
        '"""Compatibility alias."""\n'
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = c\n"
    )
    assert len(_check(source)) == 1


def test_future_import_is_allowed() -> None:
    source = (
        "from __future__ import annotations\n"
        "import sys\nfrom canonical import settings as c\nThing = c.Thing\nsys.modules[__name__] = c\n"
    )
    assert len(_check(source)) == 1
