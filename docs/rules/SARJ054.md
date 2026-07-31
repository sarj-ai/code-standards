# SARJ054 `no-file-level-escape-hatch-noqa` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_file_level_escape_hatch_noqa.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

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

## Implementation notes

### `NoFileLevelEscapeHatchNoqa.check`

Input that cannot be lexed yields no diagnostics rather than an
exception.
