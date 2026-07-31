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
// A `.stories.*` file, or anything under a `stories/` tree — Storybook's own
// `stories_vue3-vite-default-ts/` naming included. Demo trees are where a
// component's prop JSDoc is not commentary but *output*: docgen renders it as
// the args-table description a reader of the storybook sees.
const STORY_FILE_RE = /\.stories\.[cm]?[jt]sx?$/i;
const STORY_DIR_RE = /(^|\/)stories(?:[_-][^/]*)?\//i;
const GENERATED_FILE_RE =
  /([\\/](?:generated|openapi-gen|graphql[\\/]types|vendor|vendored|external|third[-_]?party)[\\/])|(\.gen\.[cm]?[jt]sx?$)|(\.generated\.[cm]?[jt]sx?$)|(\.d\.[cm]?ts$)|(\.types\.[cm]?ts$)/;
const GENERATED_MARKER_RE =
  /(?:@generated\b|generated (?:with|by)|generated (?:graphql )?types|do not edit(?: directly| manually)?)/i;

/**
 * True for a test file: a `*.test.*` / `*.spec.*` basename, the `-test` /
 * `_test` suffix forms of the same, or anything under a `test/` / `tests/` /
 * `__tests__/` / `__mocks__/` / `fixtures/` / `__fixtures__/` /
 * `__testfixtures__/` directory.
 *
 * The `__…__` fixture spellings are recognised for the same reason as the
 * `-test.ts` suffix below: a fixture is INPUT to a test, and its exact text is
 * usually asserted. `storybook/code/renderers/react/src/componentManifest/
 * __testfixtures__/ForwardRef.tsx` documents three props with `/** Input label
 * *\/`-style JSDoc that `componentMetaExtractor.qa.test.ts:448` compares
 * string-for-string; a rule that told the author to delete those comments
 * would be telling them to break the test the file exists for.
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
  return /(^|\/)(tests?|__tests__|__mocks__|__fixtures__|__testfixtures__|fixtures?|e2e|integration)\//.test(
    normalized,
  );
}

/** True for a `*.stories.*` file, or anything inside a `stories/` tree. */
export function isStoryFile(filename: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  return STORY_FILE_RE.test(normalized) || STORY_DIR_RE.test(normalized);
}

/**
 * True for a file whose text an upstream owns: generator output, or a vendored
 * copy of someone else's source.
 *
 * The vendored half mirrors Python's `_paths.is_generated_path`, whose
 * `_GENERATED_DIR_NAMES` has always held `vendor` / `vendored`. `external/` is
 * the same category under the name Node projects use for it —
 * `nest/packages/microservices/external/mqtt-options.interface.ts` is a copy of
 * the MQTT.js typings, `@see https://github.com/mqttjs/MQTT.js/` at the top,
 * and editing its prose desynchronises the copy without improving anything.
 */
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
