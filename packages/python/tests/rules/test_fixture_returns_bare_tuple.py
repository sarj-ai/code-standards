from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.fixture_returns_bare_tuple import FixtureReturnsBareTuple


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/fixtures/stores.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return FixtureReturnsBareTuple().check(Path(path), source)


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

{decorator}
def pair():
    return a, b
"""
    assert len(_check(src)) == 1


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


# FP guard from a first-party review regression: distinct static types make a  #
# reorder a type error, which is the same protection a NamedTuple buys.        #


def test_distinctly_typed_tuple_annotation_is_exempt():
    # A first-party fixture typed this way — swapping these is a pyright error.
    src = """
import pytest

@pytest.fixture
def setup_orgs_and_users() -> tuple[PsqlOrganizationStore, PsqlUserStore]:
    return org_store, user_store
"""
    assert _check(src) == []


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


def test_typing_tuple_alias_is_also_recognised():
    src = """
import pytest
import typing

@pytest.fixture
def pair() -> typing.Tuple[OrgStore, UserStore]:
    return org, user
"""
    assert _check(src) == []
