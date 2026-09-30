from __future__ import annotations

from typing import TYPE_CHECKING, final

from sarj_python_lint._python_target import PythonTargetFacts
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._nominal_project import NominalProjectFacts


if TYPE_CHECKING:
    from sarj_python_lint.rules._project_index import ProjectIndexSet


@final
class AnalysisSession:
    def __init__(self) -> None:
        self.project: ProjectIndexSet | None = None
        self.first_party = FirstPartyFacts()
        self.python_target = PythonTargetFacts()
        self.nominal_project = NominalProjectFacts()
