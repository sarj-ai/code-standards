# SARJ038 `no-file-level-suppression` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_file_level_suppression.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A per-line suppression is a claim about one line. A module-scope *unscoped*
blanket is a claim about every line in the file, forever: it switches the whole
checker off for the file, including the rules that do not exist yet. The next
person adds a function to the file and their new violations are pre-silenced by
a decision someone else made months ago, in a comment they will never scroll
past. Nothing in review or CI says a word. This is the file-level-suppression
escape hatch raised in review on a first-party repo.

A SCOPED suppression is the opposite: naming the codes it silences makes it a
reviewed, legible, bounded decision, and it keeps working exactly as intended
when new rules land. Scoped forms are NEVER flagged by this rule.

Fires on exactly three shapes:

1. Bare `# ruff: noqa` — anywhere in the file, since ruff honours the
   file-level exemption wherever the comment appears. A trailing prose reason
   (`# ruff: noqa — legacy module`) is still unscoped: it names no codes.
2. Standalone `# type: ignore` (mypy) appearing BEFORE the module's first
   statement — that position is what makes it file-level rather than per-line.
3. Standalone `# pyright: ignore` before the module's first statement.

"Standalone" means the comment is the only thing on its line. "Before the first
statement" means above the line of the first token that is not a comment or
layout — a module docstring IS a statement, so a `# type: ignore` under the
docstring is not file-level.

Deliberately NOT flagged:

* every scoped counterpart — `# ruff: noqa: E501`, `# ruff: noqa: E501, F401`,
  `# type: ignore[attr-defined]`, `# pyright: ignore[reportUnusedImport]`;
* trailing per-line suppressions — `x = foo()  # type: ignore`,
  `y = bar()  # pyright: ignore` — these bind to one line by construction, and
  their position in the file is irrelevant;
* a bare per-line `# noqa` with no `ruff:` prefix: it silences one line, not the
  file, and belongs to a different rule;
* other `ruff:` directives that are not `noqa` (`# ruff:ignore[...]`), and
  pyright's configuration comments (`# pyright: strict`);
* shebangs, encoding cookies (`# -*- coding: utf-8 -*-`) and license headers,
  which legitimately precede the first statement.

The rule is token-based rather than AST-based because comments do not survive
`ast.parse`. Malformed input yields no diagnostics rather than an exception.

A file-level blanket that is genuinely justified (vendored code, a generated
module) is suppressed with `# sarj-noqa: SARJ038 — <reason>`, which puts the
reason in the diff where a reviewer sees it.

## Implementation notes

### `_blanket_message`

A bare `# ruff: noqa` counts wherever it sits; the mypy and pyright forms
only count when they stand alone above the module's first statement, since
anywhere else they are per-line suppressions.

### `NoFileLevelSuppression.check`

Input that cannot be lexed (unterminated string, bad indentation)
yields no diagnostics rather than an exception.
