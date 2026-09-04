from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.prefer_struct_over_namedtuple import (
    PreferStructOverNamedtuple,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = PreferStructOverNamedtuple.public_examples()


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return PreferStructOverNamedtuple().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = PreferStructOverNamedtuple().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_rule_identity():
    rule = PreferStructOverNamedtuple()
    assert rule.code == "SARJ015"
    assert rule.id == "prefer-struct-over-namedtuple"
    assert rule.description


def test_diag_carries_code_and_message():
    diags = _check("from collections import namedtuple\nRow = namedtuple('Row', ['id'])\n")
    assert len(diags) == 1
    assert diags[0].code == "SARJ015"
    assert "typing.NamedTuple" in diags[0].message
    assert diags[0].severity.value == "warning"


@pytest.mark.parametrize(
    "src",
    [
        "from collections import namedtuple, defaultdict\n",
        "from collections import defaultdict, namedtuple\n",
        "from collections import OrderedDict, namedtuple, deque\n",
        "from collections import namedtuple, Counter, deque\n",
    ],
)
def test_unused_namedtuple_import_is_allowed(src: str):
    assert _check(src) == []


def test_multiple_unused_from_imports_are_allowed():
    src = "from collections import namedtuple\nfrom collections import namedtuple as nt\n"
    assert _check(src) == []


def test_flags_aliased_from_import_call_at_call_site():
    src = "from collections import namedtuple as nt\nRow = nt('Row', ['id', 'name'])\n"
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (2, 7)


def test_flags_qualified_collections_namedtuple_call():
    src = 'import collections\nRow = collections.namedtuple("Row", "id name")\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 7


def test_allows_qualified_call_without_explicit_import():
    src = 'Row = collections.namedtuple("Row", ["id", "name"])\n'
    assert _check(src) == []


@pytest.mark.parametrize("alias", ["c", "col", "_c", "collections_mod", "cx"])
def test_flags_aliased_collections_import_call(alias: str):
    src = f'import collections as {alias}\nRow = {alias}.namedtuple("Row", "id name")\n'
    assert len(_check(src)) == 1


def test_flags_multiple_qualified_calls():
    src = (
        "import collections\n"
        'A = collections.namedtuple("A", ["x"])\n'
        'B = collections.namedtuple("B", ["y"])\n'
        'C = collections.namedtuple("C", ["z"])\n'
    )
    diags = _check(src)
    assert len(diags) == 3
    assert [d.line for d in diags] == [2, 3, 4]


def test_flags_call_inside_function_body():
    src = """
import collections

def make():
    Row = collections.namedtuple("Row", ["x"])
    return Row
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_flags_call_inside_class_body():
    src = """
import collections

class Holder:
    Row = collections.namedtuple("Row", ["x"])
"""
    assert len(_check(src)) == 1


def test_flags_call_inside_conditional():
    src = """
import collections

if True:
    Row = collections.namedtuple("Row", ["x"])
"""
    assert len(_check(src)) == 1


def test_flags_call_as_base_class():
    src = """
import collections

class Point(collections.namedtuple("Point", ["x", "y"])):
    pass
"""
    assert len(_check(src)) == 1


def test_allows_factory_call_without_a_class_like_binding():
    src = 'import collections\nregister(collections.namedtuple("Row", ["x"]))\n'
    assert _check(src) == []


def test_flags_both_import_and_call_sites():
    src = """
from collections import namedtuple
import collections
A = collections.namedtuple("A", ["x"])
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_functional_call_via_from_import_reports_call_only():
    src = 'from collections import namedtuple\nPoint = namedtuple("Point", ["x", "y"])\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_allows_typing_namedtuple_class():
    src = """
from typing import NamedTuple
class Point(NamedTuple):
    x: float
    y: float
"""
    assert _check(src) == []


def test_allows_typing_namedtuple_import_alone():
    assert _check("from typing import NamedTuple\n") == []


def test_allows_qualified_typing_namedtuple_class():
    src = """
import typing
class Point(typing.NamedTuple):
    x: float
"""
    assert _check(src) == []


def test_allows_typing_namedtuple_functional_call():
    src = 'from typing import NamedTuple\nPoint = NamedTuple("Point", [("x", int)])\n'
    assert _check(src) == []


@pytest.mark.parametrize(
    "src",
    [
        "from collections import defaultdict\n",
        "from collections import defaultdict, Counter\n",
        "from collections import OrderedDict, deque, ChainMap\n",
        "from collections.abc import Mapping, Sequence\n",
        "from collections.abc import Callable\n",
    ],
)
def test_allows_non_namedtuple_collections_imports(src: str):
    assert _check(src) == []


def test_allows_collections_abc_namedtuple_lookalike():
    src = "from collections.abc import Sequence\nimport collections\n"
    assert _check(src) == []


def test_allows_bare_namedtuple_call_without_import():
    src = 'Point = namedtuple("Point", ["x", "y"])\n'
    assert _check(src) == []


def test_allows_unrelated_attribute_namedtuple_call():
    assert _check("result = obj.namedtuple()\n") == []


def test_allows_nested_attribute_namedtuple_call():
    src = 'Row = foo.collections.namedtuple("Row", ["x"])\n'
    assert _check(src) == []


def test_allows_unrelated_module_namedtuple_call():
    src = 'import mymod\nRow = mymod.namedtuple("Row", ["x"])\n'
    assert _check(src) == []


def test_allows_collections_namedtuple_attribute_without_call():
    src = "import collections\nfactory = collections.namedtuple\n"
    assert _check(src) == []


def test_allows_variable_named_namedtuple():
    src = "namedtuple = 5\nx = namedtuple + 1\n"
    assert _check(src) == []


def test_allows_annotation_named_namedtuple():
    src = "namedtuple: int = 0\n"
    assert _check(src) == []


def test_allows_string_annotation_mentioning_namedtuple():
    src = 'def f() -> "collections.namedtuple": ...\n'
    assert _check(src) == []


def test_allows_import_collections_without_use():
    assert _check("import collections\n") == []


def test_allows_collections_import_with_unrelated_name_call():
    src = "import collections\nx.namedtuple()\n"
    assert _check(src) == []


def test_allows_docstring_mentioning_namedtuple():
    src = '"""Use collections.namedtuple sparingly."""\n'
    assert _check(src) == []


@pytest.mark.parametrize("src", ["", "\n", "   \n\t\n", "# just a comment\n"])
def test_empty_or_trivial_source_is_clean(src: str):
    assert _check(src) == []


@pytest.mark.parametrize(
    "src",
    [
        "def broken(:\n",
        "from collections import namedtuple\nRow = collections.namedtuple(\n",
        "class :\n    pass\n",
        "x = = 5\n",
    ],
)
def test_syntax_error_returns_empty_without_crashing(src: str):
    assert _check(src) == []


def test_line_and_col_of_two_distinct_findings():
    src = "from collections import namedtuple\nimport collections as c\nR = c.namedtuple('R', ['a'])\n"
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (3, 5)


def test_findings_are_in_source_order():
    src = (
        "import collections\n"
        'A = collections.namedtuple("A", ["x"])\n'
        "from collections import namedtuple\n"
        'B = collections.namedtuple("B", ["y"])\n'
    )
    diags = _check(src)
    assert [d.line for d in diags] == [2, 4]


def test_check_applies_exact_sarj_noqa():
    src = (
        "from collections import namedtuple\nRow = namedtuple('Row', ['id'])  # sarj-noqa: SARJ015 — legacy tuple ABI\n"
    )
    assert _check(src) == []


def test_is_suppressed_recognizes_code_on_reported_line():
    src = "from collections import namedtuple\nRow = namedtuple('Row', ['id'])\n"
    assert not is_suppressed(src.splitlines(), 2, "SARJ015")


def test_is_suppressed_false_for_unrelated_code():
    src = "from collections import namedtuple\nRow = namedtuple('Row', ['id'])  # sarj-noqa: SARJ999 — other\n"
    diags = _check(src)
    assert len(diags) == 1
    assert not is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


def test_shadowed_collections_name_is_exempt():
    src = 'collections = object()\nRow = collections.namedtuple("Row", ["x"])\n'
    assert _check(src) == []


def test_param_shadowed_collections_is_exempt():
    src = "def f(collections):\n    return collections.namedtuple('R', ['x'])\n"
    assert _check(src) == []


# --- Adversarial: forward references the single-walk optimization must preserve


def test_allows_qualified_call_before_its_import():
    src = 'Row = collections.namedtuple("Row", ["x"])\nimport collections\n'
    assert _check(src) == []


def test_allows_aliased_qualified_call_before_its_import():
    src = 'R = c.namedtuple("R", ["x"])\nimport collections as c\n'
    assert _check(src) == []


def test_from_alias_call_reports_call_only():
    src = "from collections import namedtuple as nt\nP = nt('P', ['x'])\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_flags_from_asname_shadowing_typing_name():
    src = 'from collections import namedtuple as NamedTuple\nP = NamedTuple("P", ["x"])\n'
    assert len(_check(src)) == 1


def test_flags_call_in_deeply_nested_defs():
    src = "import collections\ndef a():\n    def b():\n        def c():\n            R = collections.namedtuple('R', ['x'])\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_flags_call_in_async_def():
    src = "import collections\nasync def f():\n    R = collections.namedtuple('R', ['x'])\n"
    assert len(_check(src)) == 1


def test_flags_call_in_match_case():
    src = "import collections\nmatch 1:\n    case 1:\n        R = collections.namedtuple('R', ['x'])\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_allows_call_as_decorator_without_a_record_binding():
    src = 'import collections\n@collections.namedtuple("R", ["x"])\nclass C:\n    pass\n'
    diags = _check(src)
    assert diags == []


@pytest.mark.parametrize(
    "expr",
    [
        '(R := collections.namedtuple("R", ["x"]))',
        'f = lambda: collections.namedtuple("R", ["x"])',
        'xs = [collections.namedtuple("R", ["x"]) for _ in range(1)]',
    ],
)
def test_allows_call_in_non_declaration_expression_contexts(expr: str):
    assert _check(f"import collections\n{expr}\n") == []


def test_allows_call_after_non_dominating_conditional_import():
    src = "import sys\nif sys.version_info:\n    import collections\nR = collections.namedtuple('R', ['x'])\n"
    diags = _check(src)
    assert diags == []


def test_allows_conditional_from_import_alone():
    assert _check("if True:\n    from collections import namedtuple\n") == []


def test_exact_source_order_interleaved_imports_and_calls():
    src = (
        "import collections\n"
        'A = collections.namedtuple("A", ["x"])\n'
        "from collections import namedtuple\n"
        "def f():\n"
        '    B = collections.namedtuple("B", ["y"])\n'
        'C = collections.namedtuple("C", ["z"])\n'
    )
    diags = _check(src)
    assert [d.line for d in diags] == [2, 5, 6]


def test_base_class_call_after_module_call_bfs_order():
    src = (
        "import collections\n"
        'X = collections.namedtuple("X", ["a"])\n'
        "class Outer:\n"
        '    class Inner(collections.namedtuple("Inner", ["b"])):\n'
        "        pass\n"
    )
    diags = _check(src)
    assert [d.line for d in diags] == [2, 4]


def test_nested_later_import_does_not_license_an_earlier_call():
    src = 'A = collections.namedtuple("A", ["x"])\nclass C:\n    class D:\n        from collections import namedtuple\n'
    assert _check(src) == []


def test_allows_qualified_typing_namedtuple_call():
    assert _check('import typing\nP = typing.namedtuple("P", ["x"])\n') == []


def test_allows_typing_namedtuple_aliased_to_namedtuple():
    src = 'from typing import NamedTuple as namedtuple\nP = namedtuple("P", ["x"])\n'
    assert _check(src) == []


def test_allows_star_import_then_bare_call():
    assert _check('from collections import *\nP = namedtuple("P", ["x"])\n') == []


def test_allows_collections_abc_qualified_call():
    assert _check('import collections.abc\nP = collections.abc.namedtuple("P", ["x"])\n') == []


def test_flags_top_level_collections_call_despite_submodule_import():
    src = 'import collections.abc\nP = collections.namedtuple("P", ["x"])\n'
    assert len(_check(src)) == 1


def test_allows_string_annotation_call_form():
    assert _check('x: "collections.namedtuple" = None\n') == []


# FP-hardening (famous-repo sweep): test files are exempt — a namedtuple in a  #
# test is usually the SUBJECT (pydantic's namedtuple-validation tests).        #


def test_test_file_is_exempt():
    src = "from collections import namedtuple\nPoint = namedtuple('Point', ['x', 'y'])\n"
    assert _check(src, path="tests/test_types_namedtuple.py") == []


def test_tests_directory_is_exempt():
    src = "import collections\nRow = collections.namedtuple('Row', 'id name')\n"
    assert _check(src, path="pydantic-core/tests/validators/helpers.py") == []


def test_production_file_still_fires():
    src = "from collections import namedtuple\nPoint = namedtuple('Point', ['x', 'y'])\n"
    assert len(_check(src, path="app/calls/rows.py")) == 1


# The two famous-repo sweep hits, verified true and pinned as regressions.    #


def test_flags_namedtuple_built_in_a_property_with_a_local_import():
    # httpx/httpx/_urls.py:409 — the deprecated `URL.raw` property imports
    # collections inside the body and builds a 4-field untyped namedtuple.
    src = """
class URL:
    @property
    def raw(self) -> tuple[bytes, bytes, int, bytes]:
        import collections

        RawURL = collections.namedtuple(
            "RawURL", ["raw_scheme", "raw_host", "port", "raw_path"]
        )
        return RawURL(self.raw_scheme, self.raw_host, self.port, self.raw_path)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 7


def test_allows_fieldless_probe_namedtuple():
    # rich/rich/pretty.py:90 — a zero-field probe used to find the file of the
    # generated __repr__; `class _Dummy(NamedTuple): pass` does the same job.
    src = 'import collections\n_dummy_namedtuple = collections.namedtuple("_dummy_namedtuple", [])\n'
    assert _check(src) == []


def test_unrelated_parameter_does_not_hide_module_call() -> None:
    src = """
import collections

Row = collections.namedtuple("Row", ["id", "name"])

def consume(collections: object) -> None:
    pass
"""
    assert len(_check(src)) == 1


def test_call_before_later_module_rebinding_reports() -> None:
    src = """
import collections
Row = collections.namedtuple("Row", ["id", "name"])
collections = load_compat_module()
"""
    assert len(_check(src)) == 1


def test_call_after_module_rebinding_is_excluded() -> None:
    src = """
import collections
collections = load_compat_module()
Row = collections.namedtuple("Row", ["id", "name"])
"""
    assert _check(src) == []


def test_local_import_and_call_report_despite_other_scope_shadow() -> None:
    src = """
def build():
    from collections import namedtuple as nt
    Row = nt("Row", ["id", "name"])
    return Row

def unrelated(nt):
    return nt
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "factory",
    [
        'Row = namedtuple(name, ["id", "name"])',
        'Row = namedtuple("Row", fields)',
        'Row = namedtuple("Row", ["invalid-name"], rename=True)',
        'Row = namedtuple("Row", ["id", "id"])',
        'Row = namedtuple("Row", ["id"], module="legacy.models")',
        'Row = namedtuple("Row", ["id"], **options)',
        'Other = namedtuple("Row", ["id", "name"])',
    ],
)
def test_dynamic_or_non_class_like_factories_are_excluded(factory: str) -> None:
    assert _check(f"from collections import namedtuple\n{factory}\n") == []


def test_manually_annotated_factory_is_already_typed() -> None:
    src = """
from collections import namedtuple
Row = namedtuple("Row", ["id", "name"])
Row.__annotations__ = {"id": int, "name": str}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "use",
    [
        "print(Row.__annotations__)",
        "Row.__annotations__ = {}",
        "Other = Row.__annotations__",
        'Row.__annotations__ = {"id": int}',
    ],
)
def test_annotation_reads_or_incomplete_writes_do_not_hide_untyped_fields(use: str) -> None:
    src = f"""
from collections import namedtuple
Row = namedtuple("Row", ["id", "name"])
{use}
"""
    assert len(_check(src)) == 1


def test_fully_annotated_namedtuple_subclass_is_excluded() -> None:
    src = """
import collections

class Row(collections.namedtuple("Row", ["id", "name"])):
    id: int
    name: str
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "pattern",
    [
        "case collections:\n        Row = collections.namedtuple('Row', ['id'])",
        "case {'lib': collections}:\n        Row = collections.namedtuple('Row', ['id'])",
        "case [*collections]:\n        Row = collections.namedtuple('Row', ['id'])",
    ],
)
def test_pattern_capture_shadows_collections_binding(pattern: str) -> None:
    src = f"""
import collections
match value:
    {pattern}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    ("imports", "expected"),
    [
        ("import collections as c, fake as c", 0),
        ("import fake as c, collections as c", 1),
        ("from collections import namedtuple as nt, deque as nt", 0),
        ("from collections import deque as nt, namedtuple as nt", 1),
    ],
)
def test_last_alias_in_one_import_statement_controls_provenance(imports: str, expected: int) -> None:
    callee = "c.namedtuple" if imports.startswith("import ") else "nt"
    src = f'{imports}\nRow = {callee}("Row", ["id"])\n'
    assert len(_check(src)) == expected


def test_later_wildcard_import_makes_factory_provenance_ambiguous() -> None:
    src = """
from collections import namedtuple
from fake import *
Row = namedtuple("Row", ["id"])
"""
    assert _check(src) == []


def test_later_explicit_factory_import_restores_provenance_after_wildcard() -> None:
    src = """
from fake import *
from collections import namedtuple
Row = namedtuple("Row", ["id"])
"""
    assert len(_check(src)) == 1


def test_nested_class_body_does_not_close_over_outer_class_import() -> None:
    src = """
class Outer:
    import collections as c

    class Inner:
        Row = c.namedtuple("Row", ["id"])
"""
    assert _check(src) == []


def test_nested_class_base_is_evaluated_in_outer_class_body() -> None:
    src = """
class Outer:
    import collections as c

    class Row(c.namedtuple("Row", ["id"])):
        pass
"""
    assert len(_check(src)) == 1


def test_nested_class_body_falls_back_to_module_instead_of_outer_class() -> None:
    src = """
import collections as c

class Outer:
    c = load_compat_module()

    class Inner:
        Row = c.namedtuple("Row", ["id"])
"""
    assert len(_check(src)) == 1


def test_type_checking_factory_is_excluded() -> None:
    src = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections import namedtuple
    Row = namedtuple("Row", ["id", "name"])
"""
    assert _check(src) == []


def test_version_compatibility_factory_is_excluded() -> None:
    src = """
import collections
import sys

if sys.version_info < (3, 11):
    Row = collections.namedtuple("Row", ["id", "name"])
"""
    assert _check(src) == []


def test_generated_source_and_path_are_excluded() -> None:
    src = '# Generated by schema compiler; do not edit.\nfrom collections import namedtuple\nRow = namedtuple("Row", ["id"])\n'
    assert _check(src) == []
    plain = 'from collections import namedtuple\nRow = namedtuple("Row", ["id"])\n'
    assert _check(plain, path="generated/models.py") == []


def test_cli_reports_nonblocking_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "models.py"
    target.write_text(
        'from collections import namedtuple\nRow = namedtuple("Row", ["id", "name"])\n',
        encoding="utf-8",
    )

    assert main(["check", "--rule", "prefer-struct-over-namedtuple", str(target)]) == 0
    assert "SARJ015 warning:" in capsys.readouterr().out
