from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final, override

import pytest

from sarj_python_lint.rule_base import Rule
from tests.illustrative_examples import illustrative_examples


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic, RuleDocumentation


@final
class _UndocumentedRule(Rule):
    id: str = "undocumented"
    code: str = "SARJ999"
    description: str = "Used to prove empty illustrative suites fail during collection."
    documentation: ClassVar[RuleDocumentation | None] = None

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        return []


def test_decorator_rejects_a_rule_without_public_examples() -> None:
    with pytest.raises(ValueError, match="requires at least one public example"):
        illustrative_examples(_UndocumentedRule)
