from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sarj_python_lint._autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId


class _Case(NamedTuple):
    rule_id: str
    path: str
    before: str
    after: str


_CASES = (
    _Case(
        "no-broad-keyword-capture",
        "app/service.py",
        "def adapt(value):\n    def _adapt(value, *, strict=True, **kwargs):\n        return value, strict\n    return _adapt(value, strict=False)\n",
        "def adapt(value):\n    def _adapt(value, *, strict=True):\n        return value, strict\n    return _adapt(value, strict=False)\n",
    ),
    _Case(
        "no-unused-underscored-keyword-parameter",
        "app/service.py",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit():\n        return 'ready'\n    return _emit()\n",
    ),
    _Case(
        "unused-test-factory-option",
        "tests/test_widget.py",
        "def test_widgets():\n    def _make_widget(*, enabled=True):\n        return dict(enabled=enabled)\n    _make_widget()\n    _make_widget(enabled=True)\n",
        "def test_widgets():\n    def _make_widget():\n        return dict(enabled=True)\n    _make_widget()\n    _make_widget()\n",
    ),
    _Case(
        "redundant-docstring",
        "app/service.py",
        'def outer(value):\n    def _normalize(item):\n        """Normalize."""\n        return item\n    return _normalize(value)\n',
        "def outer(value):\n    def _normalize(item):\n        return item\n    return _normalize(value)\n",
    ),
    _Case(
        "no-unnecessary-docstring",
        "app/service.py",
        'def outer(value):\n    def _normalize(item):\n        """Normalize."""\n        return item\n    return _normalize(value)\n',
        "def outer(value):\n    def _normalize(item):\n        return item\n    return _normalize(value)\n",
    ),
    _Case(
        "docstring-args-restate-signature",
        "app/service.py",
        'def outer(value):\n    def _count(tenant_id: str) -> int:\n        """Count active widgets.\n\n        Args:\n            tenant_id: Tenant ID\n        """\n        return 0\n    return _count(value)\n',
        'def outer(value):\n    def _count(tenant_id: str) -> int:\n        """Count active widgets.\n        """\n        return 0\n    return _count(value)\n',
    ),
    _Case(
        "docstring-returns-restate-signature",
        "app/service.py",
        'def outer():\n    def _get_line_length(line: str) -> int:\n        """Measure a rendered line.\n\n        Returns:\n            The line length.\n        """\n        return len(line)\n    return _get_line_length("sample")\n',
        'def outer():\n    def _get_line_length(line: str) -> int:\n        """Measure a rendered line.\n        """\n        return len(line)\n    return _get_line_length("sample")\n',
    ),
    _Case(
        "no-docstring-type-restatement",
        "app/service.py",
        'def outer(value):\n    def _decode(payload: str) -> int:\n        """Decode the payload.\n\n        Args:\n            payload (str): UTF-8 JSON; duplicate keys are rejected.\n        """\n        return 1\n    return _decode(value)\n',
        'def outer(value):\n    def _decode(payload: str) -> int:\n        """Decode the payload.\n\n        Args:\n            payload: UTF-8 JSON; duplicate keys are rejected.\n        """\n        return 1\n    return _decode(value)\n',
    ),
    _Case(
        "no-loguru-printf-format",
        "app/service.py",
        "from loguru import logger\nlogger.error('Request %s failed with status %d', 'marker', 503)\n",
        "from loguru import logger\nlogger.error('Request {!s} failed with status {:d}', 'marker', 503)\n",
    ),
    _Case("no-comment-cruft", "app/service.py", "# --------\nvalue = 1\n", "\nvalue = 1\n"),
    _Case("no-bare-test-phase-comments", "tests/test_service.py", "# Arrange\nvalue = 1\n", "\nvalue = 1\n"),
    _Case(
        "prefer-walrus-regex-match",
        "app/service.py",
        "import re\ndef parse(text):\n    found = re.search('x', text)\n    if found:\n        return found.group(0)\n",
        "import re\ndef parse(text):\n    if (found := re.search('x', text)):\n        return found.group(0)\n",
    ),
    _Case(
        "prefer-walrus-awaited-none-guard",
        "app/service.py",
        "async def load(store):\n    item = await store.get()\n    if item is None:\n        return\n    return item.name\n",
        "async def load(store):\n    if (item := await store.get()) is None:\n        return\n    return item.name\n",
    ),
    _Case(
        "prefer-walrus-stream-loop",
        "app/service.py",
        "def consume(read):\n    result = []\n    while True:\n        chunk = read()\n        if chunk is None:\n            break\n        result.append(chunk)\n    return result\n",
        "def consume(read):\n    result = []\n    while (chunk := read()) is not None:\n        result.append(chunk)\n    return result\n",
    ),
    _Case(
        "prefer-or-pattern",
        "app/service.py",
        "def label(value):\n    match value:\n        case 'one':\n            return 1\n        case 'two':\n            return 1\n",
        "def label(value):\n    match value:\n        case 'one' | 'two':\n            return 1\n",
    ),
    _Case(
        "duplicate-adjacent-exception-handler",
        "app/service.py",
        "def translate(call):\n    try:\n        call()\n    except ValueError as error:\n        raise RuntimeError('invalid') from error\n    except TypeError as error:\n        raise RuntimeError('invalid') from error\n",
        "def translate(call):\n    try:\n        call()\n    except (ValueError, TypeError) as error:\n        raise RuntimeError('invalid') from error\n",
    ),
    _Case(
        "prefer-fstring-over-concat",
        "app/service.py",
        'def label(value):\n    return "The value is " + str(len(value)) + "!"\n',
        "def label(value):\n    return f'The value is {len(value)!s}!'\n",
    ),
    _Case(
        "no-duplicate-dunder-all-entry",
        "app/service.py",
        '__all__ = ["one", "two", "one", "two"]\n',
        '__all__ = ["one", "two"]\n',
    ),
    _Case(
        "no-provably-dead-mock-configuration",
        "tests/test_service.py",
        "from unittest.mock import Mock\ndef test_value():\n    value = Mock(return_value=1)\n    value.return_value = 2\n    assert value() == 2\n",
        "from unittest.mock import Mock\ndef test_value():\n    value = Mock()\n    value.return_value = 2\n    assert value() == 2\n",
    ),
    _Case(
        "prefer-collection-comprehension",
        "app/service.py",
        "def values():\n    result = {}\n    for key, row in [('a', 1), ('b', 2), ('a', 3)]:\n        result[key] = (row,)\n    return result\n",
        "def values():\n    result = {key: (row,) for (key, row) in [('a', 1), ('b', 2), ('a', 3)]}\n    return result\n",
    ),
    _Case(
        "stepdown",
        "app/service.py",
        "def _parse(value):\n    return value\n\ndef render(value):\n    return _parse(value)\n",
        "\ndef render(value):\n    return _parse(value)\n\ndef _parse(value):\n    return value\n\n",
    ),
    _Case("no-unused-value-marker", "app/service.py", "def empty():\n    _ = 1\n", "def empty():\n    pass\n"),
    _Case(
        "prefer-set-isdisjoint",
        "app/service.py",
        "def overlaps():\n    return bool({'one', 'two'} & {'two'})\n",
        "def overlaps():\n    return bool((not ({'one', 'two'}).isdisjoint({'two'})))\n",
    ),
    _Case(
        "prefer-match-type-dispatch",
        "app/service.py",
        "def label():\n    def _label(value):\n        if isinstance(value, str):\n            return 'text'\n        elif isinstance(value, bytes):\n            return 'bytes'\n        elif isinstance(value, int):\n            return 'number'\n        return 'other'\n    return _label('sample')\n",
        "def label():\n    def _label(value):\n        match value:\n            case str():\n                return 'text'\n            case bytes():\n                return 'bytes'\n            case int():\n                return 'number'\n        return 'other'\n    return _label('sample')\n",
    ),
    _Case(
        "prefer-match-value-dispatch",
        "app/service.py",
        "def label():\n    def _label(value):\n        if value == 'one':\n            return 1\n        elif value == 'two':\n            return 2\n        elif value == 'three':\n            return 3\n        else:\n            return 0\n    return _label('one')\n",
        "def label():\n    def _label(value):\n        match value:\n            case 'one':\n                return 1\n            case 'two':\n                return 2\n            case 'three':\n                return 3\n            case _:\n                return 0\n    return _label('one')\n",
    ),
    _Case(
        "defect-xfail-requires-explicit-strict",
        "tests/test_service.py",
        "import pytest\n@pytest.mark.xfail(reason='BUG: wrong output')\ndef test_output():\n    assert result() == 1\n",
        "import pytest\n@pytest.mark.xfail(reason='BUG: wrong output', strict=True)\ndef test_output():\n    assert result() == 1\n",
    ),
    _Case(
        "no-restated-closed-domain-description",
        "app/service.py",
        "from typing import Literal\nfrom pydantic import BaseModel, Field\nclass Request(BaseModel):\n    mode: Literal['one', 'two'] = Field(description=\"Must be 'one' or 'two'.\")\n",
        "from typing import Literal\nfrom pydantic import BaseModel, Field\nclass Request(BaseModel):\n    mode: Literal['one', 'two'] = Field()\n",
    ),
    _Case(
        "prefer-self-type-annotation",
        "app/service.py",
        'from typing import Self, final\nclass Builder:\n    @final\n    def configure(self) -> "Builder":\n        return self\n',
        "from typing import Self, final\nclass Builder:\n    @final\n    def configure(self) -> Self:\n        return self\n",
    ),
    _Case(
        "require-exp-on-jwt-decode",
        "app/service.py",
        "import jwt\ndef claims(token, key):\n    return jwt.decode(token, key, algorithms=['HS256'])\n",
        "import jwt\ndef claims(token, key):\n    return jwt.decode(token, key, algorithms=['HS256'], options={'require': ['exp']})\n",
    ),
    _Case(
        "no-loguru-exc-info",
        "app/service.py",
        "from loguru import logger\ntry:\n    action()\nexcept ValueError:\n    logger.warning('failed', exc_info=True)\n",
        "from loguru import logger\ntry:\n    action()\nexcept ValueError:\n    logger.opt(exception=True).warning('failed')\n",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.rule_id for case in _CASES))
def test_semantic_candidates_rewrite_only_the_proven_region(case: _Case) -> None:
    path = Path(case.path)
    assert REGISTRY[case.rule_id]().check(path, case.before), case.rule_id
    fixed = fix_source(path, case.before, rule_ids=[case.rule_id])
    assert fixed == case.after
    assert REGISTRY[case.rule_id]().check(path, fixed) == []
    compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        fixed, case.path, "exec", dont_inherit=True
    )


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.rule_id for case in _CASES))
def test_fixed_sources_converge_and_unselected_sources_stay_unchanged(case: _Case) -> None:
    path = Path(case.path)
    fixed = fix_source(path, case.before, rule_ids=[case.rule_id])
    assert fix_source(path, fixed, rule_ids=[case.rule_id]) == fixed
    assert fix_source(path, case.before, rule_ids=[]) == case.before


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        ("prefer-fstring-over-concat", 'def label(value: str):\n    return "The value is " + value + "!"\n'),
        ("prefer-set-isdisjoint", "def overlaps(values):\n    return bool({'one'} & set(values))\n"),
        ("no-unused-value-marker", "def retained():\n    _ = lease()\n"),
        ("stepdown", "def _parse(value=build()):\n    return value\n\ndef render(value):\n    return _parse(value)\n"),
        ("no-comment-cruft", "# TODO: improve the parser\nvalue = 1\n"),
        ("no-duplicate-dunder-all-entry", '__all__ = ["one", "one"]  # export contract\n'),
        (
            "prefer-or-pattern",
            "def label(value):\n    match value:\n        case 'one':\n            return 1  # shared policy\n        case 'two':\n            return 1  # shared policy\n",
        ),
    ],
)
def test_ambiguous_behavior_and_comment_ownership_remain_for_review(rule_id: RuleId, source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[rule_id]) == source


def test_suppression_is_checked_before_a_fix_is_built() -> None:
    source = "def empty():\n    _ = 1  # sarj-noqa: SARJ452 -- retains a documented inspection seam\n"
    assert fix_source(Path("app/service.py"), source, rule_ids=["no-unused-value-marker"]) == source


def test_unicode_byte_columns_and_crlf_are_preserved() -> None:
    source = 'def label(value):\r\n    ü = "unused"; return "The value is " + str(len(value)) + "!"\r\n'
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["prefer-fstring-over-concat"])
    assert "ü = \"unused\"; return f'The value is {len(value)!s}!'" in fixed
    assert fixed.count("\r\n") == source.count("\r\n")


def test_comment_fixes_leave_the_executable_ast_unchanged() -> None:
    source = "# --------\nvalue = 1\n# --------\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-comment-cruft"])
    assert fixed != source
    assert ast.compare(ast.parse(source), ast.parse(fixed))


def test_interacting_fixes_reanalyze_locations_after_each_change() -> None:
    source = "# --------\ndef _value():\n    _ = 1\n    return 3\n\ndef value():\n    return _value()\n"
    rules = ["no-comment-cruft", "stepdown", "no-unused-value-marker"]
    fixed = fix_source(Path("app/service.py"), source, rule_ids=rules)
    assert fixed.index("def value") < fixed.index("def _value")
    assert "_ = 1" not in fixed
    assert fix_source(Path("app/service.py"), fixed, rule_ids=rules) == fixed


def test_native_cli_fixes_encoded_executable_files(tmp_path: Path) -> None:
    from sarj_python_lint.__main__ import main  # ruff: ignore[import-outside-top-level] -- exercise CLI file mutation separately from pure source fixtures.

    path = tmp_path / "encoded.py"
    original = b"# coding: latin-1\r\n\r\n# --------\r\nvalue = 'caf\xe9'\r\n"
    path.write_bytes(original)
    path.chmod(0o755)
    assert main(["check", "--rule", "no-comment-cruft", "--fix", str(path)]) == 0
    assert path.read_bytes() == b"# coding: latin-1\r\n\r\n\r\nvalue = 'caf\xe9'\r\n"
    assert path.stat().st_mode & 0o777 == 0o755


def test_custom_string_conversion_and_positional_export_growth_are_preserved() -> None:
    source = "class S(str):\n    def __format__(self, spec):\n        return 'changed'\nclass V:\n    def __str__(self):\n        return S('original')\ndef label(value):\n    return 'The value is ' + str(value) + '!'\n"
    assert fix_source(Path("app/service.py"), source, rule_ids=["prefer-fstring-over-concat"]) == source
    exports = "__all__ = ['x', 'x', 'y']\n__all__.insert(2, 'z')\n"
    assert fix_source(Path("app/service.py"), exports, rule_ids=["no-duplicate-dunder-all-entry"]) == exports


def test_independent_marker_fixes_leave_a_valid_function_body() -> None:
    source = "def empty():\n    _ = 1\n    _ = 2\n    _ = 3\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-unused-value-marker"])
    assert fixed == "def empty():\n    pass\n"
    compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        fixed, "empty.py", "exec", dont_inherit=True
    )


def test_many_independent_comments_are_fixed_without_changing_execution() -> None:
    source = "def test_many():\n    value = 0\n" + "    # Arrange\n    value += 1\n" * 1000
    fixed = fix_source(Path("tests/test_many.py"), source, rule_ids=["no-bare-test-phase-comments"])
    assert "# Arrange" not in fixed
    assert ast.compare(ast.parse(source), ast.parse(fixed))
    assert fix_source(Path("tests/test_many.py"), fixed, rule_ids=["no-bare-test-phase-comments"]) == fixed


@pytest.mark.parametrize("source", ["__all__ = ('item', 'item', 'item')\n", "__all__ = 'item', 'item'\n"])
def test_duplicate_exports_preserve_singleton_tuple_protocol(source: str) -> None:
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-duplicate-dunder-all-entry"])
    module = ast.parse(fixed)
    declaration = module.body[0]
    assert isinstance(declaration, ast.Assign)
    assert isinstance(declaration.value, ast.Tuple)
    assert ast.literal_eval(declaration.value) == ("item",)


def test_duplicate_export_growth_keeps_unique_elements() -> None:
    source = "__all__ = ['item']\n__all__.extend(['item', 'other'])\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-duplicate-dunder-all-entry"])
    assert fixed == "__all__ = ['item']\n__all__.extend(['other'])\n"


@pytest.mark.parametrize(
    "source",
    [
        'def normalize(value):\n    """Normalize."""\n    return value\n',
        'def outer():\n    def _normalize(value):\n        """Normalize."""\n        return value\n    return _normalize\n',
        'def outer(value):\n    def _normalize(item):\n        """Normalize."""\n        return item\n    help(_normalize)\n    return _normalize(value)\n',
        'def outer(value):\n    def _normalize(item):\n        """Normalize."""\n        """A secondary expression is not a docstring."""\n        return item\n    return _normalize(value)\n',
        'def outer(value):\n    def _normalize(item):\n        """Reject stale values before consulting the network."""\n        return item\n    return _normalize(value)\n',
    ],
)
def test_documented_apis_metadata_escapes_and_meaningful_prose_stay_unchanged(source: str) -> None:
    assert (
        fix_source(Path("app/service.py"), source, rule_ids=["redundant-docstring", "no-unnecessary-docstring"])
        == source
    )


@pytest.mark.parametrize(
    ("rule_id", "sections"),
    [
        (
            "docstring-args-restate-signature",
            "        Args:\n            tenant_id: Tenant ID\n\n        Keyword Args:\n            tenant_id: A required tenant partition used for authorization.\n",
        ),
        (
            "docstring-returns-restate-signature",
            "        Returns:\n            The count.\n\n        Yields:\n            Ordered snapshots after every accepted update.\n",
        ),
        (
            "docstring-returns-restate-signature",
            "        Returns:\n            The count.\n\n        Return:\n            A tenant-scoped snapshot without stale entries.\n",
        ),
    ],
)
def test_competing_docstring_sections_keep_their_independent_contracts(rule_id: RuleId, sections: str) -> None:
    source = (
        'def outer(value):\n    def _count(tenant_id: str) -> int:\n        """Count active widgets.\n\n'
        + sections
        + '        """\n        return 0\n    return _count(value)\n'
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=[rule_id]) == source


def test_all_proven_builtin_exception_names_can_share_a_handler() -> None:
    source = (
        "def translate(call):\n    try:\n        call()\n"
        "    except FileNotFoundError as error:\n        raise RuntimeError('invalid') from error\n"
        "    except PermissionError as error:\n        raise RuntimeError('invalid') from error\n"
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["duplicate-adjacent-exception-handler"])
    assert fixed == (
        "def translate(call):\n    try:\n        call()\n"
        "    except (FileNotFoundError, PermissionError) as error:\n"
        "        raise RuntimeError('invalid') from error\n"
    )
    assert fix_source(Path("app/service.py"), fixed, rule_ids=["duplicate-adjacent-exception-handler"]) == fixed


@pytest.mark.parametrize(
    "prefix",
    [
        "class FileNotFoundError(Exception):\n    pass\n",
        "from app.exceptions import CustomError as FileNotFoundError\n",
        "import builtins\nbuiltins.FileNotFoundError = RuntimeError\n",
    ],
)
def test_builtin_exception_spellings_need_native_unshadowed_proof(prefix: str) -> None:
    source = prefix + (
        "def translate(call):\n    try:\n        call()\n"
        "    except FileNotFoundError as error:\n        raise RuntimeError('invalid') from error\n"
        "    except PermissionError as error:\n        raise RuntimeError('invalid') from error\n"
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=["duplicate-adjacent-exception-handler"]) == source


@pytest.mark.parametrize(
    ("declaration", "method"),
    [("Builder[Self]", "configure"), ("Builder", "configure[Self]")],
)
def test_self_alias_shadowed_by_type_parameters_stays_unchanged(declaration: str, method: str) -> None:
    source = (
        "from typing import Self, final\n"
        f"class {declaration}:\n    @final\n    def {method}(self) -> 'Builder':\n        return self\n"
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=["prefer-self-type-annotation"]) == source


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        (
            "prefer-fstring-over-concat",
            "def render[str]():\n    return 'value: ' + str(3)\n",
        ),
        (
            "prefer-fstring-over-concat",
            "def render[len](value):\n    return 'size: ' + str(len(value))\n",
        ),
        (
            "duplicate-adjacent-exception-handler",
            "def translate[FileNotFoundError](call):\n    try:\n        call()\n    except FileNotFoundError as error:\n        raise RuntimeError('invalid') from error\n    except PermissionError as error:\n        raise RuntimeError('invalid') from error\n",
        ),
        (
            "prefer-match-type-dispatch",
            "def render[int](value):\n    if isinstance(value, int):\n        return 'integer'\n    elif isinstance(value, str):\n        return 'text'\n    else:\n        return 'other'\n",
        ),
        (
            "prefer-collection-comprehension",
            "def values[set](rows):\n    result = set()\n    for row in rows:\n        result.add(row.value)\n    return result\n",
        ),
        (
            "require-exp-on-jwt-decode",
            "import jwt\ndef decode[jwt](token, key):\n    return jwt.decode(token, key, algorithms=['HS256'])\n",
        ),
        (
            "no-loguru-exc-info",
            "from loguru import logger\ndef report[logger]():\n    logger.warning('failed', exc_info=True)\n",
        ),
        (
            "no-loguru-printf-format",
            "from loguru import logger\ndef report[logger]():\n    logger.error('value %s', 'marker')\n",
        ),
        (
            "no-loguru-printf-format",
            "from loguru import logger\ndef report[len](value):\n    logger.error('size %s', len(value))\n",
        ),
        (
            "no-provably-dead-mock-configuration",
            "from unittest.mock import Mock\ndef test_value[Mock]():\n    value = Mock(return_value=1)\n    value.return_value = 2\n    assert value() == 2\n",
        ),
        (
            "no-restated-closed-domain-description",
            "from typing import Literal\nfrom pydantic import BaseModel, Field\nclass Request[Field](BaseModel):\n    mode: Literal['one', 'two'] = Field(description=\"Must be 'one' or 'two'.\")\n",
        ),
        (
            "defect-xfail-requires-explicit-strict",
            "import pytest\nclass TestOutput[pytest]:\n    @pytest.mark.xfail(reason='BUG: wrong output')\n    def test_output(self):\n        assert result() == 1\n",
        ),
    ],
)
def test_generic_type_parameters_do_not_borrow_builtin_or_import_provenance(rule_id: RuleId, source: str) -> None:
    path = Path(
        "tests/test_service.py"
        if rule_id in {"no-provably-dead-mock-configuration", "defect-xfail-requires-explicit-strict"}
        else "app/service.py"
    )
    assert fix_source(path, source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    "source",
    [
        "def _emit(*, _unused=True):\n    return 'ready'\n_emit(_unused=False)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit\n",
        "def emit():\n    def _emit(*, _unused=make_default()):\n        return 'ready'\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit(_unused=make_value())\n",
        "def emit():\n    def _emit(*, _unused: marker()=True):\n        return 'ready'\n    return _emit(_unused=False)\n",
        "def emit[T]():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit(**options)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    print(locals())\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    print(sys._getframe().f_locals)\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    from external import emit as _emit\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit(\n        *,\n        _unused=True,  # Caller contract\n    ):\n        return 'ready'\n    return _emit(_unused=False)\n",
        "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit(\n        _unused=False,  # Caller contract\n    )\n",
    ],
)
def test_signature_contracts_effects_reflection_and_comments_remain_for_review(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=["no-unused-underscored-keyword-parameter"]) == source


@pytest.mark.parametrize(
    "source",
    [
        "def _make_widget(*, enabled=True):\n    return Widget(enabled=enabled)\n_make_widget()\n_make_widget(enabled=True)\n",
        "def test_widgets():\n    def _make_widget(*, enabled=True):\n        return Widget(read=lambda: enabled)\n    _make_widget()\n    _make_widget(enabled=True)\n",
        "def test_widgets():\n    def _make_widget(*, enabled=True):\n        return Widget(enabled=enabled)\n    _make_widget()\n    _make_widget(enabled=False)\n",
        "def test_widgets():\n    def _make_widget(*, enabled=make_default()):\n        return Widget(enabled=enabled)\n    _make_widget()\n    _make_widget()\n",
        "def test_widgets():\n    def _make_widget(*, enabled=True):\n        return Widget(enabled=enabled)\n    _make_widget()\n    consume(_make_widget)\n    _make_widget()\n",
        "def test_widgets():\n    def _make_widget(*, enabled: marker()=True):\n        return Widget(enabled=enabled)\n    _make_widget()\n    _make_widget()\n",
        "def test_widgets():\n    def _make_widget(*, enabled=True):\n        value: enabled = 1\n        return Widget(value=value)\n    _make_widget()\n    _make_widget()\n",
    ],
)
def test_factory_signature_lifetimes_closures_and_external_contracts_stay_unchanged(source: str) -> None:
    assert fix_source(Path("tests/test_widget.py"), source, rule_ids=["unused-test-factory-option"]) == source


def test_token_signature_edit_preserves_other_defaults_annotations_and_multiline_structure() -> None:
    source = "def emit():\n    def _emit(\n        value: 'Wire[bytes]' = b'wire',\n        *,\n        _unused=(True),\n        keep=False,\n    ):\n        return value, keep\n    return _emit(_unused=False, keep=True)\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-unused-underscored-keyword-parameter"])
    assert "value: 'Wire[bytes]' = b'wire'" in fixed
    assert "keep=False" in fixed
    assert "_unused" not in fixed
    assert "*," in fixed
    compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        fixed, "service.py", "exec", dont_inherit=True
    )
    assert fix_source(Path("app/service.py"), fixed, rule_ids=["no-unused-underscored-keyword-parameter"]) == fixed


def test_invariant_factory_uses_effective_supplied_value_instead_of_original_default() -> None:
    source = "def test_widgets():\n    def _make_widget(*, enabled=True):\n        return dict(enabled=enabled)\n    _make_widget(enabled=False)\n    _make_widget(enabled=False)\n"
    fixed = fix_source(Path("tests/test_widget.py"), source, rule_ids=["unused-test-factory-option"])
    assert "return dict(enabled=False)" in fixed
    assert "def _make_widget():" in fixed
    assert fix_source(Path("tests/test_widget.py"), fixed, rule_ids=["unused-test-factory-option"]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        "def _adapt(value, **kwargs):\n    return value\n_adapt(3)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    return _adapt(value, extra=False)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs: 'object'):\n        return value\n    return _adapt(value)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value, kwargs\n    return _adapt(value)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return lambda: kwargs\n    return _adapt(value)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    return _adapt\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    from external import adapt as _adapt\n    return _adapt(value)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    return _adapt(value, **options)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    return _adapt(*values)\n",
        "def adapt(value):\n    def _adapt(value, *, strict, **kwargs):\n        return value\n    return _adapt(value)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    print(sys._getframe().f_locals)\n    return _adapt(value)\n",
        "def adapt(value):\n    def _adapt(value, **kwargs):  # sarj-noqa: SARJ477 -- compatibility boundary\n        return value\n    return _adapt(value)\n",
    ],
)
def test_keyword_capture_contracts_captures_and_invalid_calls_remain_for_review(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=["no-broad-keyword-capture"]) == source


def test_unused_nested_keyword_capture_without_keyword_only_parameters_is_removed() -> None:
    source = "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    return _adapt(value)\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-broad-keyword-capture"])
    assert "def _adapt(value):" in fixed
    assert "return _adapt(value)" in fixed
    assert fix_source(Path("app/service.py"), fixed, rule_ids=["no-broad-keyword-capture"]) == fixed


def test_unused_capture_with_inert_builtin_object_annotation_can_be_removed() -> None:
    source = (
        "def adapt(value):\n    def _adapt(value, **kwargs: object):\n        return value\n    return _adapt(value)\n"
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-broad-keyword-capture"])
    assert "def _adapt(value):" in fixed
    assert "return _adapt(value)" in fixed


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        (
            "no-unused-underscored-keyword-parameter",
            "def emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    def call[_emit]():\n        return _emit(_unused=False)\n    return call()\n",
        ),
        (
            "no-broad-keyword-capture",
            "def adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    def call[_adapt]():\n        return _adapt(value)\n    return call()\n",
        ),
        (
            "no-broad-keyword-capture",
            "object = UnknownType\ndef adapt(value):\n    def _adapt(value, **kwargs: object):\n        return value\n    return _adapt(value)\n",
        ),
        (
            "no-broad-keyword-capture",
            "def adapt[object](value):\n    def _adapt(value, **kwargs: object):\n        return value\n    return _adapt(value)\n",
        ),
    ],
)
def test_nested_caller_and_capture_annotation_provenance_reject_type_parameter_shadows(
    rule_id: RuleId, source: str
) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        (
            "no-unused-underscored-keyword-parameter",
            "from inspect import stack\nfrom operator import attrgetter\ndef emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    _emit()\n    functions = attrgetter('f_locals')(stack()[0][0])\n    return functions['_emit'](_unused=False)\n",
        ),
        (
            "no-broad-keyword-capture",
            "from inspect import stack as frames\nfrom operator import attrgetter\ndef adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    _adapt(value)\n    functions = attrgetter('f_locals')(frames()[0][0])\n    return functions['_adapt'](value, extra=False)\n",
        ),
        (
            "unused-test-factory-option",
            "from inspect import stack as frames\nfrom operator import attrgetter\ndef test_widgets():\n    def _make_widget(*, enabled=True):\n        return Widget(enabled=enabled)\n    _make_widget()\n    _make_widget()\n    functions = attrgetter('f_locals')(frames()[0][0])\n    return functions['_make_widget'](enabled=False)\n",
        ),
        (
            "no-unused-underscored-keyword-parameter",
            "def emit():\n    def _emit(*, _unused=True):\n        yield 1\n    return _emit(_unused=False)\n",
        ),
        (
            "no-broad-keyword-capture",
            "def adapt(value):\n    def _adapt(value, **kwargs):\n        yield value\n    return _adapt(value)\n",
        ),
    ],
)
def test_frame_capabilities_and_generator_metadata_keep_nested_signatures(rule_id: RuleId, source: str) -> None:
    path = Path("tests/test_widget.py" if rule_id == "unused-test-factory-option" else "app/service.py")
    assert fix_source(path, source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    ("module", "capability"),
    [
        ("inspect", "stack"),
        ("inspect", "getargvalues"),
        ("inspect", "getgeneratorlocals"),
        ("inspect", "getcoroutinelocals"),
        ("sys", "_current_frames"),
    ],
)
def test_imported_frame_capability_aliases_keep_nested_signatures(module: str, capability: str) -> None:
    source = f"from {module} import {capability} as frames\ndef emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return _emit(_unused=False)\n"
    assert fix_source(Path("app/service.py"), source, rule_ids=["no-unused-underscored-keyword-parameter"]) == source


@pytest.mark.parametrize("kind", ["async", "generator"])
@pytest.mark.parametrize(
    "case",
    tuple(
        case
        for case in _CASES
        if case.rule_id
        in {
            "redundant-docstring",
            "no-unnecessary-docstring",
            "docstring-args-restate-signature",
            "docstring-returns-restate-signature",
            "no-docstring-type-restatement",
        }
    ),
    ids=tuple(
        case.rule_id
        for case in _CASES
        if case.rule_id
        in {
            "redundant-docstring",
            "no-unnecessary-docstring",
            "docstring-args-restate-signature",
            "docstring-returns-restate-signature",
            "no-docstring-type-restatement",
        }
    ),
)
def test_async_and_generator_metadata_keep_their_nested_docstrings(case: _Case, kind: str) -> None:
    source = case.before
    if kind == "async":
        source = source.replace("    def _", "    async def _", 1)
    else:
        source = source.replace("        return ", "        yield ", 1)
    assert fix_source(Path(case.path), source, rule_ids=[case.rule_id]) == source
