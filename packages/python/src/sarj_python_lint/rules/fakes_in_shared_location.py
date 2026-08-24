from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


_DOUBLE_NAME_RE = re.compile(r"^(?:Fake|Stub|Mock|InMemory|Recording|Scripted)[A-Z0-9]")
_SHARED_SUPPORT_NAMES = frozenset({"helpers", "support", "test_support", "test_utils"})


@final
class FakesInSharedLocation(Rule):
    id = "fakes-in-shared-location"
    code = "SARJ428"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Define reusable test doubles in a shared testing-support module.",
        rationale=(
            "A fake embedded in one test module silently becomes a private second implementation of a contract. "
            "A named support module makes the double discoverable, reusable, and reviewable as test infrastructure."
        ),
        remediation=(
            "Move the class to a testing, fakes, stubs, mocks, doubles, or test_utils module and import it. "
            "Use an exact SARJ428 suppression only when the double is intentionally coupled to one scenario."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only top-level classes in test files with an explicit Fake, Stub, Mock, InMemory, Recording, or Scripted prefix are classified as doubles.",
            "conftest.py and conventional shared-support paths are already shared locations and are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="local-fake-service",
                title="A test module privately defines a named fake",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_checkout.py",
                        "class FakePaymentGateway:\n    async def charge(self, amount: int) -> None:\n        pass\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_checkout.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="shared-fake-service",
                title="A shared support module owns the fake",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/payment.py",
                        "class FakePaymentGateway:\n    async def charge(self, amount: int) -> None:\n        pass\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/payment.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or _is_shared_support(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"test double `{node.name}` is private to this test module; move it to shared testing support "
                    "or add an exact SARJ428 suppression for a deliberately scenario-local double"
                ),
            )
            for node in tree.body
            if isinstance(node, ast.ClassDef) and _DOUBLE_NAME_RE.match(node.name)
        ]


def _is_shared_support(path: Path) -> bool:
    names = {part.lower() for part in path.parts}
    return (
        path.name == "conftest.py"
        or path.stem.lower() in _SHARED_SUPPORT_NAMES
        or bool(names & _SHARED_SUPPORT_NAMES)
        or is_test_support_path(path)
    )
