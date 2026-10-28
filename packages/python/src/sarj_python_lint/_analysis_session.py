from __future__ import annotations

from typing import TYPE_CHECKING, final

from sarj_python_lint._python_target import PythonTargetFacts
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._local_source import LocalSourceFacts
from sarj_python_lint.rules._nominal_project import NominalProjectFacts


if TYPE_CHECKING:
    from sarj_python_lint._prepared_sources import PreparedSourceInputs
    from sarj_python_lint.rules._project_index import ProjectIndexSet


@final
class AnalysisSession:
    def __init__(self, *, source_inputs: PreparedSourceInputs | None = None) -> None:
        self.project: ProjectIndexSet | None = None
        self.source_inputs = source_inputs
        self.first_party = FirstPartyFacts()
        self.local_source = (
            LocalSourceFacts() if source_inputs is None else LocalSourceFacts(source_inputs=source_inputs)
        )
        self.python_target = PythonTargetFacts()
        self.nominal_project = NominalProjectFacts()
