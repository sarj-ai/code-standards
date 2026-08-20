from __future__ import annotations

from typing import final

from sarj_python_lint.rules._first_party import FirstPartyFacts


@final
class AnalysisSession:
    def __init__(self) -> None:
        self.first_party = FirstPartyFacts()
