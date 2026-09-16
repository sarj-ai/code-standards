from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
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
    "assignment",
    [
        "public_helper = _private_helper",
        "public_helper: Callable[[], None] = _private_helper",
        "first_helper = second_helper = _private_helper",
    ],
)
def test_reports_public_aliases_for_private_names(assignment: str) -> None:
    diagnostics = _check(f"def _private_helper(): ...\n{assignment}\n")

    expected_names = ["first_helper", "second_helper"] if assignment.startswith("first_helper") else ["public_helper"]
    assert [(finding.code, finding.line) for finding in diagnostics] == [("SARJ440", 2)] * len(expected_names)
    assert all(f"public `{name}`" in finding.message for name, finding in zip(expected_names, diagnostics, strict=True))


@pytest.mark.parametrize(
    "source",
    [
        "_private_alias = public_helper",
        "_second_private_alias = _private_helper",
        "public_dunder = __version__",
        "public_translation = _",
        "public_attribute = owner._private_helper",
        "public_one, public_two = _private_values",
        "if enabled:\n    public_helper = _private_helper\n",
        "try:\n    public_helper = _private_helper\nexcept ImportError:\n    pass\n",
        "with lock:\n    public_helper = _private_helper\n",
        "match mode:\n    case 'legacy':\n        public_helper = _private_helper\n",
        "def configure():\n    public_helper = _private_helper\n",
        "class Compatibility:\n    public_helper = _private_helper\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    public_helper = _private_helper\n",
        "import typing\nif typing.TYPE_CHECKING:\n    public_helper = _private_helper\n",
        "from implementation import _private_helper as public_helper",
        "public_helper = public_implementation",
    ],
)
def test_excludes_non_module_public_private_name_aliases(source: str) -> None:
    assert _check(source) == []


def test_exact_suppression_allows_deliberate_compatibility_alias(tmp_path: Path) -> None:
    source = tmp_path / "compatibility.py"
    source.write_text(
        "public_helper = _private_helper  # sarj-noqa: SARJ440 -- legacy import path until API-123\n",
        encoding="utf-8",
    )

    assert analyze([NoRedundantModuleAliasExports.id], [source]) == []


@pytest.mark.parametrize(
    ("module_import", "replacement"),
    [
        ("import sys", "sys.modules[__name__] = canonical"),
        ("import sys as runtime", "runtime.modules[__name__] = canonical"),
        ("from sys import modules", "modules[__name__] = canonical"),
        ("from sys import modules as loaded_modules", "loaded_modules[__name__] = canonical"),
    ],
)
def test_reports_current_module_replacement(module_import: str, replacement: str) -> None:
    diagnostics = _check(f"{module_import}\nimport canonical\n{replacement}\n")
    assert [(finding.code, finding.line, finding.col) for finding in diagnostics] == [("SARJ440", 3, 1)]


@pytest.mark.parametrize(
    "body",
    [
        "if enabled:\n    sys.modules[__name__] = canonical\n",
        "try:\n    sys.modules[__name__] = canonical\nexcept KeyError:\n    pass\n",
        "with lock:\n    sys.modules[__name__] = canonical\n",
        "match mode:\n    case 'replace':\n        sys.modules[__name__] = canonical\n",
    ],
)
def test_reports_replacement_in_module_control_flow(body: str) -> None:
    assert len(_check(f"import sys\nimport canonical\n{body}")) == 1


def test_reports_each_replacement_in_source_order() -> None:
    diagnostics = _check(
        "import sys\nimport canonical\nsys.modules[__name__] = canonical\nsys.modules[__name__] = canonical\n"
    )
    assert [(finding.line, finding.col) for finding in diagnostics] == [(3, 1), (4, 1)]


@pytest.mark.parametrize(
    "replacement",
    [
        "sys.modules[__name__]: object = canonical",
        "legacy = sys.modules[__name__] = canonical",
    ],
)
def test_reports_annotated_and_chained_replacement(replacement: str) -> None:
    assert len(_check(f"import sys\nimport canonical\n{replacement}\n")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import sys\ncurrent = sys.modules[__name__]\n",
        "import sys\nsys.modules['legacy.settings'] = canonical\n",
        "import sys\nsys.modules[f'{__name__}.child'] = canonical\n",
        "import sys\nsys.modules['__name__'] = canonical\n",
        "import registry\nregistry.modules[__name__] = canonical\n",
        "import sys\nsys.modules[__name__].value = canonical\n",
        "import sys\nsys.modules.setdefault(__name__, canonical)\n",
        "import sys\nsys.modules.update({__name__: canonical})\n",
        "import sys\nsys.modules.__setitem__(__name__, canonical)\n",
        "import sys\ndel sys.modules[__name__]\n",
        "import sys\nsys = registry\nsys.modules[__name__] = canonical\n",
        "import sys\n__name__ = 'legacy.settings'\nsys.modules[__name__] = canonical\n",
        "if enabled:\n    import sys\nsys.modules[__name__] = canonical\n",
        "from typing import TYPE_CHECKING\nimport sys\nif TYPE_CHECKING:\n    sys.modules[__name__] = canonical\n",
        "import typing\nimport sys\nif typing.TYPE_CHECKING:\n    sys.modules[__name__] = canonical\n",
        "import sys\ndef replace():\n    sys.modules[__name__] = canonical\n",
        "import sys\nclass Alias:\n    sys.modules[__name__] = canonical\n",
        "from canonical.settings import Settings as Settings\n",
        "# sys.modules[__name__] = canonical\n",
        'TEXT = "sys.modules[__name__] = canonical"\n',
        "if:",
        "# Generated file; do not edit\nimport sys\nsys.modules[__name__] = canonical\n",
    ],
)
def test_excludes_other_module_cache_operations_and_ambiguous_bindings(source: str) -> None:
    assert _check(source) == []


def test_stub_files_are_excluded() -> None:
    assert _check("import sys\nsys.modules[__name__] = canonical\n", "legacy/settings.pyi") == []
