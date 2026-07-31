"""Every engine must agree on what a log call and a secret name are.

Two live false negatives came from the same shape: a word list mirrored by hand
between the Python and TypeScript engines, where one copy was shorter. Nothing
compared them, so each engine's own tests passed.

`logger.success("auth", token=token)` was a log call to SARJ017 and not to
SARJ012 -- the SECURITY rule had the shorter list. `bearer == provided` was a
timing attack in TypeScript and silent in Python.
"""

from __future__ import annotations

from pathlib import Path
import re

from sarj_python_lint._secret_names import SECRET_WORDS
from sarj_python_lint.rules._logging import LOG_METHODS


_TS_ROOT = Path(__file__).resolve().parents[3] / "packages" / "typescript" / "src" / "rules"


def _ts_string_set(source: str, name: str) -> set[str]:
    """Read the entries of a `const <name> ... = new Set([...])` literal."""
    start = source.index(f"const {name}")
    body = source[source.index("[", start) : source.index("]", start)]
    return set(re.findall(r'"([^"]+)"', body))


def test_log_methods_are_one_set_in_python() -> None:
    """A second copy is how SARJ012 came to disagree with SARJ017."""
    rules = Path(__file__).resolve().parent.parent / "src" / "sarj_python_lint" / "rules"
    redefiners = [
        path.name
        for path in sorted(rules.glob("*.py"))
        if re.search(r"^_LOG_METHODS[:\s]*=", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert redefiners == [], (
        f"{redefiners} define their own _LOG_METHODS. Import LOG_METHODS from "
        "rules._logging instead -- a private copy is free to be shorter than the "
        "security rule's, which is exactly how logger.success(token=...) went unlinted."
    )


def test_python_secret_words_cover_the_typescript_set() -> None:
    """`bearer` was in the TS set and neither Python set; the rest were identical."""
    ts = _ts_string_set((_TS_ROOT / "_secret-names.ts").read_text(encoding="utf-8"), "SECRET_WORDS")
    missing = sorted(ts - SECRET_WORDS)
    assert missing == [], (
        f"TypeScript treats {missing} as secret-like and Python does not, so the "
        "same identifier is a finding in one engine and silent in the other."
    )


def test_loguru_levels_are_log_methods() -> None:
    """`loguru` is in _LOGGER_NAMES, so its documented levels must be log calls."""
    assert {"success", "trace", "log", "fatal"} <= LOG_METHODS
