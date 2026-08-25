from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import PytestFixtureReturnsBareTuple


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/app/tests/fixtures/stores.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return PytestFixtureReturnsBareTuple().check(Path(path), source)


_PUBLIC_EXAMPLES = PytestFixtureReturnsBareTuple.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


_BARE_TUPLE_FIXTURE = """
import pytest

@pytest.fixture
def orgs_and_users():
    return org_store, user_store
"""


# Test-path gating.                                                            #


@pytest.mark.parametrize("path", ["conftest.py", "test_x.py", "a/tests/fixtures.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_BARE_TUPLE_FIXTURE, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_BARE_TUPLE_FIXTURE, path) == []


# Positive: every fixture-decorator spelling and result form.                  #


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.fixture",
        "@pytest.fixture(scope='session')",
        "@fixture",
        "@pytest_asyncio.fixture",
        "@pytest_asyncio.fixture(loop_scope='session')",
    ],
)
def test_flags_every_fixture_spelling(decorator: str):
    src = f"""
import pytest
import pytest_asyncio
from pytest import fixture

{decorator}
def pair():
    return a, b
"""
    assert len(_check(src)) == 1


def test_unimported_or_unrelated_fixture_decorators_are_ignored():
    src = """
class framework:
    @staticmethod
    def fixture(fn):
        return fn

@fixture
def first():
    return a, b

@framework.fixture
def second():
    return a, b
"""
    assert _check(src) == []


def test_flags_yielded_bare_tuple():
    src = """
import pytest

@pytest.fixture
def pair():
    yield org, user
"""
    assert len(_check(src)) == 1


def test_flags_async_fixture():
    src = """
import pytest_asyncio

@pytest_asyncio.fixture
async def pair():
    return await make_org(), await make_user()
"""
    assert len(_check(src)) == 1


def test_flags_tuple_returned_from_inside_control_flow():
    src = """
import pytest

@pytest.fixture
def pair(flag):
    if flag:
        return a, b
    return c, d
"""
    assert len(_check(src)) == 2


def test_message_reports_the_field_count():
    src = """
import pytest

@pytest.fixture
def triple():
    return a, b, c
"""
    [diag] = _check(src)
    assert "bare 3-field tuple" in diag.message


# FP guard: the named alternative and the factory-closure shape.               #


def test_namedtuple_construction_is_exempt():
    src = """
import pytest

@pytest.fixture
def pair():
    return OrgAndUser(org=org, user=user)
"""
    assert _check(src) == []


def test_dataclass_construction_is_exempt():
    src = """
import pytest

@pytest.fixture
def pair():
    return Seeded(org, user)
"""
    assert _check(src) == []


def test_factory_closure_returning_a_tuple_is_attributed_to_the_closure():
    src = """
import pytest

@pytest.fixture
def make_pair():
    def _make():
        return org, user
    return _make
"""
    assert _check(src) == []


def test_single_element_tuple_is_exempt():
    src = """
import pytest

@pytest.fixture
def one():
    return (value,)
"""
    assert _check(src) == []


def test_starred_tuple_is_exempt():
    src = """
import pytest

@pytest.fixture
def spread():
    return *pair, extra
"""
    assert _check(src) == []


def test_scalar_return_is_exempt():
    src = """
import pytest

@pytest.fixture
def store():
    return PsqlOrgStore(pool)
"""
    assert _check(src) == []


def test_undecorated_function_returning_a_tuple_is_exempt():
    src = """
def helper():
    return a, b
"""
    assert _check(src) == []


def test_test_function_returning_a_tuple_is_exempt():
    src = """
def test_thing():
    return a, b
"""
    assert _check(src) == []


# Edge cases.                                                                  #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("@pytest.fixture\ndef pair(:\n    return a, b\n") == []


def test_multiple_fixtures_in_one_file():
    src = """
import pytest

@pytest.fixture
def one():
    return a, b

@pytest.fixture
def two():
    return Named(a=1)

@pytest.fixture
def three():
    yield c, d
"""
    assert len(_check(src)) == 2


def test_reports_line_and_column_of_the_tuple():
    src = """
import pytest

@pytest.fixture
def pair():
    return org, user
"""
    [diag] = _check(src)
    assert diag.line == 6
    assert diag.code == "SARJ044"


def test_diagnostics_are_sorted_by_position():
    src = """
import pytest

@pytest.fixture
def a_fix(flag):
    if flag:
        return a, b
    yield c, d
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_distinctly_typed_tuple_annotation_still_requires_named_fields():
    src = """
import pytest

@pytest.fixture
def setup_orgs_and_users() -> tuple[PsqlOrganizationStore, PsqlUserStore]:
    return org_store, user_store
"""
    assert len(_check(src)) == 1


def test_repeated_type_in_annotation_still_fires():
    # `tuple[str, str]` is exactly the silent-reorder case the rule exists for.
    src = """
import pytest

@pytest.fixture
def ids() -> tuple[str, str]:
    return org_id, user_id
"""
    assert len(_check(src)) == 1


def test_unannotated_fixture_still_fires():
    src = """
import pytest

@pytest.fixture
def pair():
    return org, user
"""
    assert len(_check(src)) == 1


def test_homogeneous_variadic_tuple_annotation_still_fires():
    # `tuple[str, ...]` is a sequence, not a record — the distinctness argument
    # does not apply, so the rule keeps its say.
    src = """
import pytest

@pytest.fixture
def names() -> tuple[str, ...]:
    return first, second
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("annotation", ["tuple[*Ts]", "tuple[Unpack[Ts]]", "typing.Tuple[typing.Unpack[Ts]]"])
def test_variadic_tuple_annotation_does_not_invent_a_fixed_record(annotation: str) -> None:
    src = f"""\
import pytest
import typing
from typing import Unpack

@pytest.fixture
def values() -> {annotation}:
    return existing_values
"""

    assert _check(src) == []


def test_typing_tuple_annotation_still_requires_named_fields():
    src = """
import pytest
import typing

@pytest.fixture
def pair() -> typing.Tuple[OrgStore, UserStore]:
    return org, user
"""
    assert len(_check(src)) == 1


def test_tuple_return_annotation_catches_returned_alias():
    src = """
import pytest

@pytest.fixture
def pair() -> tuple[OrgStore, UserStore]:
    return existing_pair
"""
    assert len(_check(src)) == 1


def test_generator_tuple_annotation_catches_yielded_alias():
    src = """
import pytest
from collections.abc import Iterator

@pytest.fixture
def pair() -> Iterator[tuple[OrgStore, UserStore]]:
    yield existing_pair
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("wrapper", ["Iterable", "Iterator", "AsyncIterable", "AsyncIterator"])
def test_collection_of_tuples_returned_as_a_value_is_not_the_fixture_tuple(wrapper: str):
    src = f"""
import pytest

@pytest.fixture
def rows() -> {wrapper}[tuple[OrgStore, UserStore]]:
    return existing_rows
"""
    assert _check(src) == []


def test_stringized_tuple_annotation_catches_returned_alias():
    src = """
import pytest

@pytest.fixture
def pair() -> "tuple[OrgStore, UserStore]":
    return existing_pair
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "annotation",
    [
        "tuple[int, str] | None",
        "None | tuple[int, str]",
        "Optional[tuple[int, str]]",
        "Union[tuple[int, str], None]",
    ],
)
def test_optional_tuple_annotation_is_still_positional(annotation: str) -> None:
    src = f"""\
import pytest
from typing import Optional, Union

@pytest.fixture
def pair() -> {annotation}:
    return make_pair()
"""
    assert len(_check(src)) == 1


def test_non_optional_union_annotation_is_ambiguous() -> None:
    src = """\
import pytest

@pytest.fixture
def pair() -> tuple[int, str] | list[str]:
    return make_pair()
"""
    assert _check(src) == []


def test_local_tuple_type_alias_catches_returned_alias():
    src = """
import pytest

Pair = tuple[OrgStore, UserStore]

@pytest.fixture
def pair() -> Pair:
    return existing_pair
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("module", ["pytest", "pytest_asyncio"])
def test_imported_fixture_alias_is_recognized(module: str):
    src = f"""
from {module} import fixture as fx

@fx
def pair() -> tuple[OrgStore, UserStore]:
    return existing_pair
"""
    assert len(_check(src)) == 1


def test_generated_fixture_file_is_exempt():
    src = """
import pytest

@pytest.fixture
def pair() -> tuple[OrgStore, UserStore]:
    return org, user
"""
    assert _check(src, path="python/app/tests/generated/fixtures.py") == []
