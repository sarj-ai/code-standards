"""SARJ054: file-level `# ruff: noqa: TID251` — an escape hatch must be per-line.

SARJ038 bans the *unscoped* blanket (`# ruff: noqa` with no codes). This is its
scoped sibling, and it exists because scoping is not always enough.

For most codes a file-level exemption is a legible statement about the file:
`# ruff: noqa: E501` says "this file has long generated lines", and nothing is
lost by saying it once. For a small set of codes it is not, because the code
does not report a mechanical property — it reports a *decision*, and the
standard's own configuration says so in the diagnostic text. Every
`flake8-tidy-imports` ban in `ruff.strict.toml` ends the same way:

    "If a mock is genuinely required, import with `# noqa: TID251 — <reason>`."
    "for a genuine external boundary use ... inline `# noqa: TID251 — <reason>`."
    "If you genuinely need raw os.environ, add `# noqa: TID251 — <reason>` inline."

The instruction is *inline, with a reason*, and it is load-bearing: TID251 is
the mock/raw-env ban, so each surviving site is a specific claim that one
specific boundary needs one specific hatch, and the reason is what a reviewer
reads in the diff. Hoisting it to `# ruff: noqa: TID251` at the top of the file
converts N reviewed decisions into one unreviewable one and pre-authorizes
every mock anybody adds to that file afterwards — including in code that does
not exist yet. It also erases the ratchet's signal: `sarj-ratchet` counts
`noqa:TID251` and `file-noqa:TID251` under separate keys precisely because the
file-level form is not a substitute for the inline one.

The flagged code set is therefore not a taste list. It is exactly the codes for
which this standard's shipped `ruff.strict.toml` instructs an inline reasoned
suppression — today that is `TID251` alone, the only banned-API code ruff has.

Fires on a `# ruff: noqa: <codes>` comment, anywhere in the file (ruff honours
the file-level exemption wherever it appears), when `<codes>` names one of
those codes.

Deliberately NOT flagged:

* the **inline** form `mock.patch(...)  # noqa: TID251 — reason`. It has no
  `ruff:` prefix, binds to one line, and is the shape this rule steers toward.
* file-level exemptions for every other code (`# ruff: noqa: E501`,
  `# ruff: noqa: F401, F403`) — mechanical whole-file properties, and measured
  across five repos they are exactly what the population consists of
  (`UP035` in pydantic's `main.py`, `RUF067`/`F403` in a first-party repo's
  `__init__.py`s).
* the unscoped blanket `# ruff: noqa`, which is SARJ038's finding, not this one.
  A file carrying both gets one diagnostic from each rule, which is correct:
  they are two different mistakes.

A file that genuinely must hoist the hatch (a vendored test-support module that
mocks a paid SDK end to end) is suppressed with
`# sarj-noqa: SARJ054 — <reason>` on the same line.
"""

from __future__ import annotations

import re
import tokenize
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule
from sarj_python_lint.rules._suppression_comments import scan_comments


if TYPE_CHECKING:
    from pathlib import Path


# The codes whose remediation `ruff.strict.toml` spells as an inline, reasoned
# suppression. TID251 (flake8-tidy-imports banned-api) is ruff's
# only such code; the frozenset is the extension point if that changes.
ESCAPE_HATCH_CODES = frozenset({"TID251"})

# Matched as ruff accepts a file-level scoped suppression: case-insensitive on
# the directive head, requiring a colon and at least one code (the code-less
# form is SARJ038's).
_RUFF_SCOPED_NOQA_RE = re.compile(
    r"^ruff:\s*noqa\s*:\s*(?P<codes>[A-Za-z][A-Za-z0-9]*(?:\s*,\s*[A-Za-z][A-Za-z0-9]*)*)",
    re.IGNORECASE,
)


@final
class NoFileLevelEscapeHatchNoqa(Rule):
    """File-level `# ruff: noqa` naming an escape-hatch code — suppress it per line instead."""

    id: str = "no-file-level-escape-hatch-noqa"
    code: str = "SARJ054"
    description: str = (
        "A file-level `# ruff: noqa` naming an escape-hatch code (TID251) "
        "pre-authorizes every future use in the file — suppress it inline, "
        "one reviewed `# noqa: TID251 — <reason>` per site."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every file-level ruff exemption naming an escape-hatch code.

        Input that cannot be lexed yields no diagnostics rather than an
        exception.

        Returns:
            The diagnostics, sorted by (line, col).

        """
        try:
            comments = scan_comments(source)
        except tokenize.TokenError, IndentationError, SyntaxError:
            return []
        diags = [
            Diagnostic(
                path=path,
                line=comment.line,
                col=comment.col,
                code=self.code,
                message=_message(hatched),
            )
            for comment in comments
            if (hatched := _hatch_codes(comment.body))
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _hatch_codes(body: str) -> tuple[str, ...]:
    """Extract the escape-hatch codes named by a file-level ruff exemption.

    Returns:
        The matched codes in source order, or an empty tuple when the comment is
        not a scoped `ruff: noqa` or names none of them.

    """
    match = _RUFF_SCOPED_NOQA_RE.match(body)
    if match is None:
        return ()
    codes = [code.strip().upper() for code in match["codes"].split(",")]
    return tuple(code for code in codes if code in ESCAPE_HATCH_CODES)


def _message(codes: tuple[str, ...]) -> str:
    """Render the diagnostic for the escape-hatch codes found on the line.

    Returns:
        The formatted message.

    """
    listed = ", ".join(codes)
    return (
        f"file-level `# ruff: noqa: {listed}` pre-authorizes every future use in "
        f"this file, including code not written yet — {listed} is an escape "
        f"hatch whose whole value is the per-site reason, so suppress it inline: "
        f"`# noqa: {codes[0]} — <why this boundary needs it>`."
    )
