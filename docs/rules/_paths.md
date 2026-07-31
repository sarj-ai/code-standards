# `_paths` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

Shared file-path predicates for rules that are scoped by file
kind rather than by syntax — a timing-attack surface only exists in
production auth code, fixture SQL in a test legitimately breaks the
store-write conventions, and a dev script legitimately skips production
hardening. Answering "is this a test file?" / "is this a script?" in exactly
one place (mirroring the Python `_paths.py` extraction) is what stops the
per-rule regexes from drifting apart again.

## Evidence relocated from the source

### `*`

The `__…__` fixture spellings are recognised for the same reason as the
`-test.ts` suffix below: a fixture is INPUT to a test, and its exact text is
usually asserted. `storybook/code/renderers/react/src/componentManifest/
__testfixtures__/ForwardRef.tsx` documents three props with `/** Input label
*\/`-style JSDoc that `componentMetaExtractor.qa.test.ts:448` compares
string-for-string; a rule that told the author to delete those comments
would be telling them to break the test the file exists for.

The `-test.ts` / `_test.ts` suffixes are recognised because the dot form
alone is not the universal convention, and missing them silently un-exempts a
whole repo's test tree. Measured while converging `no-repeated-string-literal`
with its Python twin (2026-07): react-router names every suite `*-test.ts`, and
ALL 5 of the rule's hits over the 2,186-file third-party corpus were in two of
them — `react-router/packages/react-router-dev/vite/remove-exports-test.ts`
(4 hits) and `route-chunks-test.ts` (1). Each is a source-transform fixture
(`"export const keptExport_1 = () => {};…"`) deliberately repeated so the
before/after assertions stay comparable — the exact category the test
exemption exists for. Python's `_paths.is_test_path` has always accepted
`*_test.py`; this closes the same gap on the TS side.

