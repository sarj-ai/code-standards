# SARJ052 `no-stdlib-logging` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_stdlib_logging.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Two logging systems in one process is one system too many. The stdlib logger
and loguru keep separate handler chains, separate levels and separate sinks, so
a module that reaches for `logging.getLogger(__name__)` writes to a logger
nobody configured: its records skip the JSON formatter, skip the Sentry
breadcrumb integration, skip the PII redaction patcher, and — because the
stdlib root logger defaults to WARNING with a `lastResort` stderr handler —
usually vanish in production while looking fine locally. The house convention
(`ruff.strict.toml` sets `logger-objects = ["loguru.logger"]` so ruff's G-family
even judges loguru calls) is that `from loguru import logger` is the only
logger.

Fires on any runtime import of the stdlib logging package:
`import logging`, `import logging as x`, `import logging.config`,
`from logging import getLogger`, `from logging.handlers import RotatingFileHandler`.

Deliberately NOT flagged:

* **the loguru bridge.** A module that imports stdlib `logging` *and* loguru is
  usually the shim that routes one into the other — an `InterceptHandler`
  subclassing `logging.Handler`, a `logging.basicConfig` call that installs it,
  a third-party library's logger being re-pointed. That is the one legitimate
  reason to touch stdlib logging in a loguru house. Measured across the two
  production corpora the exemption is exact: one repo's three sites (a package
  `__init__.py`, a `configure_logging.py`, and a service `main.py`) and the
  other's one (`common/logging.py`) are all bridges, all import loguru, and no
  other module in either repo imports stdlib logging.

  Importing loguru is **not on its own** enough, though, and the first version of
  this rule made it so. A file-wide pass keyed on one import means that the day
  someone adds `import logging` + `logging.getLogger(__name__).info(...)` to a
  module that already says `from loguru import logger`, the rule goes quiet — and
  a module already using the house logger is the *most* likely place for a second
  hierarchy to appear by accident. So the exemption additionally requires the
  file to show that it **configures** stdlib logging rather than emitting through
  it: `logging.Handler` / `LogRecord` / `Logger` / `Formatter` / `Filter`,
  `basicConfig`, `addHandler` / `setLevel` / `addLevelName` / `handlers=` /
  `propagate`, `getLogger()` with no argument, or `logging.<LEVEL>` used as a
  level constant. All four production bridges match; a module that merely logs
  through both does not.
* **`if TYPE_CHECKING:` imports** — `logging.Logger` as an annotation is a type,
  not a logger. Nothing is emitted through it.
* **test files** (`_paths.is_test_path`) — `caplog` is pytest's fixture and it
  speaks stdlib logging; asserting on a dependency's records is normal.
* **`scripts/` and `notebooks/`** — one-shot code with no log pipeline to join.
* **generated files** — they mirror whatever their generator emits.

This is a house-convention rule, not a universal one: a *library* should log
through stdlib `logging` precisely because it must not impose a sink on its
callers (trio's three sites are correct for trio). Enable the hook in
applications, not in libraries.

A genuine exception is suppressed with `# sarj-noqa: SARJ052 — <reason>`.

## Implementation notes

### `_imports_loguru`

Half of the bridge test; the caller pairs it with `_BRIDGE_MARKER_RE` so that
naming loguru is not on its own a licence to open a second logger hierarchy.
