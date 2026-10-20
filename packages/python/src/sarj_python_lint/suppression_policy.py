from __future__ import annotations


# A suppression cannot grant itself authority to disable suppression accountability.
PROTECTED_SUPPRESSION_CODES = frozenset({"SARJ054", "SARJ419", "SARJ448", "SARJ523"})
