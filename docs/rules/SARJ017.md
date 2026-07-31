# SARJ017 `no-fstring-in-log` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_fstring_in_log.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

The house logging style is structured: pass variables as keyword arguments so
log aggregators can index and filter on them, and so the message template stays
constant across calls:

    # flagged
    logger.info(f"call {call_id} finished in {elapsed}s")

    # preferred
    logger.info("call finished", call_id=call_id, elapsed=elapsed)

F-string interpolation bakes the values into the message text, defeating
structured search, breaking template grouping, and (for loguru) evaluating the
string even when the level is disabled.

To keep false positives near zero we require BOTH a logger-like receiver
(`logger`/`log`/`logging`/`loguru` and common aliases) AND a logging method
name — an f-string passed to some unrelated `.info(...)` is not flagged. The
receiver chain is resolved, so builder/factory forms are still caught:
`logger.bind(...).info(...)`, `logger.opt(lazy=True).debug(...)`. Only the first
positional argument (the message) is inspected.

The structured-keyword advice is loguru-specific: stdlib `logging` treats
trailing positional args as %-format parameters and reserves `exc_info` /
`stack_info` / `extra` keywords, so rewriting a stdlib call to
`logger.info("msg", key=value)` raises `TypeError: _log() got an unexpected
keyword argument`. We therefore suppress calls whose receiver is a stdlib
logger, and keep firing on the loguru-shaped calls the advice actually applies
to.

EXEMPTIONS, WITH CORPUS EVIDENCE
--------------------------------

Measured over 2,657 files of popular third-party Python (fastapi, pydantic,
black, sqlmodel, rich, flask, httpx, requests, anyio), the earlier version of
this rule reported 94 hits, of which 70 were false positives — every one of
them a **stdlib `logging` call**, for which the advice recommends a fix that
raises at runtime. Only the inline `logging.getLogger(__name__).info(...)`
spelling was recognised as stdlib; the two spellings that actually dominate
were not:

1. **The module-level convenience functions (59 hits, 63%)** — `logging.info(
   f"...")` on the root logger, with no `getLogger` anywhere. Evidence:
   `fastapi/scripts/notify_translations.py:312`, `fastapi/scripts/sponsors.py:155`,
   `fastapi/scripts/docs.py:656`, `sqlmodel/scripts/docs.py:206`,
   `pydantic/.github/actions/people/people.py:675`,
   `fastapi/scripts/label_approved.py:30`. Guard: a receiver naming a module
   bound by `import logging`.

2. **A module-level logger assigned once, then used by name (11 hits)** —
   `LOG = logging.getLogger(__name__)` at the top of the file, `LOG.info(
   f"...")` throughout. The receiver at the call site is a bare `Name`, so the
   existing chain walk could never reach the factory. Evidence:
   `black/scripts/release.py:17` (the binding) with hits at `:80`, `:123`,
   `:242`; `black/scripts/migrate-black.py:93`. Guard: resolve the binding —
   any name assigned from a `getLogger(...)` chain is a stdlib logger.

Already correct before the audit, and confirmed against the corpus: `f"static"`
with no interpolation is never flagged (harmless), and neither
`warnings.warn(f"...")` nor rich's `console.log(f"...")` fires, because the
receiver resolver requires a logger-shaped name — `warnings` and `console` are
not one. The 24 survivors are true positives by shape (`log.info(f"...")`), all
in one file: `black/tests/data/cases/preview_long_strings.py:311` and on, a
formatter fixture that pastes the same snippets twice (input and expected
output). No guard is warranted for that — it is a corpus artifact, not a rule
defect.

Suppress an intentional case with `# sarj-noqa: SARJ017 — <reason>`.

## Implementation notes

### `_interpolating_fstring`

A concatenated message like `f"{x}" + "!"` wraps the f-string in a `BinOp`,
so the interpolation is not the top-level node — walk the `Add` tree to find
it while leaving interpolation-free f-strings unflagged.

### `_chain_has_getlogger`

Matched against the SAME set and casing as `_logging.is_logger_expr`, and that
parity is load-bearing. When `is_logger_expr` learned to recognise a bare
`get_logger()` callee, this guard still tested the exact string `"getLogger"`,
so a snake_case factory returning a *stdlib* logger became a logger to the
rule but not a stdlib logger to the guard — and the rule then advised
`logger.info("msg", key=value)` on an API that rejects it.

That advice fails in the worst possible way: stdlib `Logger._log` raises
`TypeError: got an unexpected keyword argument`, but only when the call is
actually emitted, so the code is green at the default WARNING level and
breaks the moment log level is raised to INFO. The shim that triggers it —
`def get_logger(name): return logging.getLogger(name)` — ships in
huggingface_hub, transformers, fastmcp, mcp and speechmatics, all present in
consumer virtualenvs.

### `_is_stdlib_logging_call`

A stdlib-reserved keyword (`exc_info`/`stack_info`/`extra`), a
`logging.getLogger(...)` factory anywhere in the receiver chain, or a
receiver resolving to one of the file's stdlib `logging` bindings marks the
logger as stdlib, whose message API is %-style positional, not structured
keywords — so the rule must stay silent to avoid recommending a fix that
raises `TypeError`.

### `_StdlibLoggers`

Both spellings that dominate real code hide the stdlib provenance from the
call site: `logging.info(...)` names the module, and `LOG = logging.getLogger
(__name__)` puts the factory in a different statement entirely. Resolving the
bindings once per file is what lets the call site be judged.

### `_StdlibLoggers.owns`

Matching is on the receiver's dotted path or a *prefix* of it, never on a
loose name: `self.logger = logging.getLogger(...)` binds `self.logger`,
which must not make an unrelated module-level loguru `logger` look
stdlib. The prefix is what lets builder calls through —
`logging.getLogger(x).bind(...)` has the path `logging.getLogger.bind`.
