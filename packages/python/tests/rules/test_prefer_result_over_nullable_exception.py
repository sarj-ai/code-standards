from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_result_over_nullable_exception import PreferResultOverNullableException


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return PreferResultOverNullableException().check(Path(path), source)


def test_documented_examples() -> None:
    verify_native_rule(PreferResultOverNullableException, analyze)


_ERRORS = "class BaseError(Exception):\n    pass\nclass ParsingError(BaseError):\n    pass\n"


@pytest.mark.parametrize(
    "source",
    [
        _ERRORS + "def validate(row: str) -> ParsingError | None: ...\n",
        _ERRORS + "def validate(row: str) -> 'BaseError | None': ...\n",
        _ERRORS + "from typing import Optional\ndef validate(row: str) -> Optional[ParsingError]: ...\n",
        _ERRORS + "from typing import Union\ndef validate(row: str) -> Union[ParsingError, None]: ...\n",
        "def first() -> BaseException | None: ...\n",
        "async def first() -> ValueError | None: ...\n",
        "def prepare() -> tuple[dict[str, bytes], BaseException | None]: ...\n",
        "def prepare() -> dict[str, OSError | None]: ...\n",
        "type Outcome = tuple[int, BaseException | None]\ndef prepare() -> Outcome: ...\n",
        "class Service(Port):\n    def _prepare(self) -> tuple[int, BaseException | None]: ...\n",
    ],
)
def test_reports_nullable_exception_returns(source: str) -> None:
    findings = _check(source)

    assert [item.severity for item in findings] == [Severity.WARNING]
    assert "Success[T] | Failure[E]" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "def load() -> str | None: ...\n",
        "def failure() -> BaseException: ...\n",
        "from vendor import VendorError\ndef call() -> VendorError | None: ...\n",
        "class ValueError:\n    pass\ndef call() -> ValueError | None: ...\n",
        "def call(error: BaseException | None) -> None: ...\n",
        "def call() -> None:\n    failure: BaseException | None = None\n",
        "class Port:\n    def __exit__(self, *args: object) -> BaseException | None: ...\n",
        "class Adapter(Port):\n    def fetch(self) -> OSError | None: ...\n",
        "def call() -> OSError | None: ...  # sarj-noqa: SARJ591 -- legacy callback protocol\n",
    ],
)
def test_ignores_non_exception_unproven_or_contract_shapes(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["tests/test_service.py", "app/tests/fakes/service.py"])
def test_skips_tests_and_test_support(path: str) -> None:
    assert _check("def first() -> BaseException | None: ...\n", path) == []
