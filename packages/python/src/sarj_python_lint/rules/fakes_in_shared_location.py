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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_DOUBLE_NAME_RE = re.compile(r"^(?:Fake|Stub|Mock|InMemory|Recording|Scripted)[A-Z0-9]")
_SHARED_SUPPORT_NAMES = frozenset(
    {
        "doubles",
        "fakes",
        "helpers",
        "mocks",
        "stubs",
        "support",
        "test_doubles",
        "test_fakes",
        "testing",
        "test_support",
        "test_utils",
    }
)
_TEST_ROOT_NAMES = frozenset({"integration_tests", "test", "tests"})
_NON_INFRA_ROOT_NAMES = frozenset({"benchmarks", "examples", "site-packages", "third_party", "vendor"})
_SUPPORT_STEM_RE = re.compile(r"(?:^|_)(?:fakes?|mocks?|stubs?|doubles?|testing)(?:$|_)")


@final
class FakesInSharedLocation(Rule):
    id = "fakes-in-shared-location"
    code = "SARJ428"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Review named top-level test doubles for shared-support ownership unless they are intentionally scenario-local.",
        rationale=(
            "Reusable doubles hidden in an individual test module are difficult to discover and are often recreated. "
            "A per-file warning cannot prove cross-module reuse, so scenario-local doubles may remain with an exact rationale."
        ),
        remediation=(
            "Move a reusable double to a testing, fakes, stubs, mocks, doubles, helpers, support, or test_utils module. "
            "Keep a deliberately local double near its scenario with an exact SARJ428 suppression and rationale."
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
                example_id="scenario-local-fake",
                title="A nested double is visibly coupled to one scenario",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_checkout.py",
                        "def test_decline_retries_once():\n"
                        "    class FakePaymentGateway:\n"
                        "        async def charge(self, amount: int) -> None:\n"
                        "            raise Declined()\n"
                        "    assert retries(FakePaymentGateway()) == 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_checkout.py"),
                expected_count=0,
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
                public=False,
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
                    f"named top-level test double `{node.name}` may need shared ownership; move it only when reused "
                    "across modules, otherwise keep it local with an exact SARJ428 suppression and rationale"
                ),
                severity=Severity.WARNING,
            )
            for node in tree.body
            if isinstance(node, ast.ClassDef) and _DOUBLE_NAME_RE.match(node.name)
        ]


def _is_shared_support(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    return (
        path.name == "conftest.py"
        or path.stem.lower() in _SHARED_SUPPORT_NAMES
        or bool(_SUPPORT_STEM_RE.search(path.stem.lower()))
        or bool(set(parts) & _NON_INFRA_ROOT_NAMES)
        or _support_below_test_root(parts)
        or _non_collected_module_below_test_root(path, parts)
    )


def _support_below_test_root(parts: list[str]) -> bool:
    test_roots = [index for index, part in enumerate(parts) if part in _TEST_ROOT_NAMES]
    if not test_roots:
        return False
    below_root = parts[test_roots[-1] + 1 : -1]
    return bool(set(below_root) & _SHARED_SUPPORT_NAMES)


def _non_collected_module_below_test_root(path: Path, parts: list[str]) -> bool:
    return bool(set(parts) & _TEST_ROOT_NAMES) and not (path.name.startswith("test") or path.name.endswith("_test.py"))
