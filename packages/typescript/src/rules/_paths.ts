/**
 * @fileoverview Shared file-path predicates for rules that are scoped by file
 * kind rather than by syntax — a timing-attack surface only exists in
 * production auth code, fixture SQL in a test legitimately breaks the
 * store-write conventions, and a dev script legitimately skips production
 * hardening. Answering "is this a test file?" / "is this a script?" in exactly
 * one place (mirroring the Python `_paths.py` extraction) is what stops the
 * per-rule regexes from drifting apart again.
 */

const SCRIPT_FILE_RE = /([\\/]scripts[\\/])|(\.mjs$)/;
const STORY_FILE_RE = /\.stories\.[cm]?[jt]sx?$/i;
const GENERATED_FILE_RE =
  /([\\/](?:generated|openapi-gen|graphql[\\/]types)[\\/])|(\.gen\.[cm]?[jt]sx?$)|(\.generated\.[cm]?[jt]sx?$)|(\.d\.[cm]?ts$)|(\.types\.[cm]?ts$)/;
const GENERATED_MARKER_RE =
  /(?:@generated\b|generated (?:with|by)|generated (?:graphql )?types|do not edit(?: directly| manually)?)/i;

/**
 * True for a test file: a `*.test.*` / `*.spec.*` basename, the `-test` /
 * `_test` suffix forms of the same, or anything under a `test/` / `tests/` /
 * `__tests__/` / `__mocks__/` / `fixtures/` directory.
 *
 * The `-test.ts` / `_test.ts` suffixes are recognised because the dot form
 * alone is not the universal convention, and missing them silently un-exempts a
 * whole repo's test tree. Measured while converging `no-repeated-string-literal`
 * with its Python twin (2026-07): react-router names every suite `*-test.ts`, and
 * ALL 5 of the rule's hits over the 2,186-file third-party corpus were in two of
 * them — `react-router/packages/react-router-dev/vite/remove-exports-test.ts`
 * (4 hits) and `route-chunks-test.ts` (1). Each is a source-transform fixture
 * (`"export const keptExport_1 = () => {};…"`) deliberately repeated so the
 * before/after assertions stay comparable — the exact category the test
 * exemption exists for. Python's `_paths.is_test_path` has always accepted
 * `*_test.py`; this closes the same gap on the TS side.
 */
export function isTestFile(filename: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  const base = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (/[.\-_](test|spec|e2e)\.[cm]?[jt]sx?$/.test(base) || /\.integration\.[cm]?[jt]sx?$/.test(base)) {
    return true;
  }
  return /(^|\/)(tests?|__tests__|__mocks__|fixtures|e2e|integration)\//.test(normalized);
}

export function isStoryFile(filename: string): boolean {
  return STORY_FILE_RE.test(filename);
}

export function isGeneratedFile(filename: string, sourceText = ""): boolean {
  return GENERATED_FILE_RE.test(filename.replaceAll("\\", "/")) || GENERATED_MARKER_RE.test(sourceText.slice(0, 2048));
}

/**
 * True for one-off tooling files: anything under a `scripts/` directory or a
 * `*.mjs` file. Dev scripts run interactively and die with the terminal, so
 * production-hardening rules (e.g. fetch timeouts) do not apply there.
 */
export function isScriptFile(filename: string): boolean {
  return SCRIPT_FILE_RE.test(filename);
}
