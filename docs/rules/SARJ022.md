# SARJ022 `single-public-export` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_single_public_export.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Such a module stem should describe its responsibility instead.

This rule is deliberately narrow. It fires ONLY when BOTH hold:

  (a) the module stem is a generic "junk-drawer" name that says nothing about
      the module's responsibility (`utils`, `base`, `models`, `types`, ...), AND
  (b) the module has exactly one public top-level `def` / `class`, so the
      rename target is unambiguous.

When both hold, the sole public export's name is the obvious, information-rich
replacement for the meaningless stem (`utils.py` exposing `snake_case_text` ->
`snake_case_text.py`; `enums.py` exposing `IntegrationProvider` ->
`integration_provider.py`).

Why the denylist gate matters: an informative stem names the module's DOMAIN
(`pagination.py`, `retry_wrapper.py`, `warmup.py`), which is frequently broader
than its one current export. Renaming those to the export loses the domain and
is a regression. A junk-drawer stem carries no domain to lose, so replacing it
with the export name is strictly an improvement.

Public = a top-level `class` / `def` / `async def` whose name has no leading
underscore. Imports are ignored.

A public module-level CONSTANT (`UPPER_SNAKE = ...`, with or without an
annotation) counts as a public export too, and any such constant blocks the
rule: the module's public surface is then wider than its one def, so naming the
file after that def is a lie. Corpus evidence (1 of the 2 hits over 2,657 files
of third-party Python): `pydantic/release/shared.py:6` has one public function
`run_command` but also exports `REPO`, `HISTORY_FILE`, `PACKAGE_VERSION_FILE`
and `GITHUB_TOKEN`, three of which its importers (`release/prepare.py`,
`release/push.py`) pull in — `run_command.py` would be the wrong name for it.
Lowercase module-level assignments (`logger = ...`, cached singletons) are NOT
public exports and do not block the rule.

Skipped entirely: `__init__.py`, `conftest.py`, test files (`test_*.py` or under
a `tests/` directory), and framework-convention filenames whose stem is fixed by
a framework/tool and cannot be renamed (`models.py`, `views.py`, `base.py`, ...).
Modules whose single export already snake-cases to the stem are not flagged
(there is nothing to improve).
* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package accounts for all of them.

## Implementation notes

### `_has_public_constant`

A constant is part of the module's public surface just as a def is, so its
presence means the sole def is not the whole story and renaming the file
after that def would misdescribe the module. `__all__` and other dunders
are excluded (they describe the surface, they are not part of it), as are
lowercase assignments such as `logger`.
