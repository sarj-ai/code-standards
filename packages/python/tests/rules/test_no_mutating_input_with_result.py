from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_mutating_input_with_result import NoMutatingInputWithResult


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule


@pytest.fixture
def rule() -> Rule:
    return NoMutatingInputWithResult()


def test_documented_examples() -> None:
    verify_native_rule(NoMutatingInputWithResult, analyze)


@pytest.mark.parametrize(
    "statement", ["body.version = 2", "body.version += 1", "del body.version", "alias = body\n    alias.version = 2"]
)
def test_result_function_writes_its_request(rule: Rule, statement: str) -> None:
    source = f"def send_update(body: Request) -> Response:\n    {statement}\n    return send(body)\n"
    assert len(rule.check(Path("tests/test_update.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def update(body: Request) -> None:\n    body.version = 2\n",
        "def update(body: Request) -> None:\n    body.version = 2\n    return None\n",
        "def update(body: Request):\n    body.version = 2\n    return send(body)\n",
        "def update(body: Request) -> Response:\n    updated = evolve(body)\n    updated.version = 2\n    return send(updated)\n",
        "class Client:\n    def send(self) -> Response:\n        self.version = 2\n        return send(self)\n",
        "def send_update(body: Request) -> Response:\n    def update():\n        body.version = 2\n    return send(body)\n",
        "def versions(body: Request) -> Iterator[int]:\n    body.version = 2\n    yield body.version\n",
        "def update(body: Request) -> Response:\n    body.version = 2  # sarj-noqa: SARJ555 -- this adapter deliberately updates the caller-owned cursor\n    return send(body)\n",
    ],
)
def test_commands_copies_receivers_generators_and_reviewed_contracts(rule: Rule, source: str) -> None:
    assert rule.check(Path("api.py"), source) == []


def test_existing_model_and_container_rules_keep_mutation_ownership(rule: Rule) -> None:
    model = "from pydantic import BaseModel\nclass Request(BaseModel):\n    version: int\ndef send_update(body: Request) -> Response:\n    body.version = 2\n    return send(body)\n"
    assert rule.check(Path("api.py"), model) == []
    container = "def versions(values: list[int]) -> list[int]:\n    values[0] = 2\n    return values\n"
    assert rule.check(Path("api.py"), container) == []
