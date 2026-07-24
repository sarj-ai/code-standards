"""Shared path predicates for the file-scope-gated rules (SARJ031/033/036).

A single definition of "is this a test file?" so the test-scoped rules
(no-sleep-in-test-body, no-raw-sql-in-tests) and the rules that *exempt* tests
(httpx-client-requires-timeout) never diverge on what counts as a test file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


_TEST_DIR_NAMES = frozenset({"tests", "test"})


def is_test_path(path: Path) -> bool:
    """Report whether `path` is a test file.

    A test file is `conftest.py`, a `test_*.py` / `*_test.py` stem, or any file
    under a `tests` / `test` directory segment.

    Returns:
        True when `path` belongs to the test tree.

    """
    name = path.name
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in _TEST_DIR_NAMES for part in path.parts)
