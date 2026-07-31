/**
 * @fileoverview _paths — shared file-kind predicates, so "is this a test / script / generated file?" is answered in exactly one place.
 *
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/_paths.md
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
// A BANNER match is safe and universal in a way a PATH match is not: no
// hand-written file claims to be generator output. Subject-scoped on purpose —
// the file itself has to be what the claim is ABOUT. See the evidence file.
const GENERATED_MARKER_RE =
  /(?:@generated\b|this file (?:is|was|has been)[\w\s,'-]{0,40}?generated|auto-?generated file\b|generated (?:with|by)|generated (?:graphql )?types|do not edit(?: directly| manually)?|do not (?:modify|change) this file)/i;

/**
 * True for a test file: a `*.test.*` / `*.spec.*` basename, the `-test` /
 * `_test` suffix forms of the same, or anything under a `test/` / `tests/` /
 * `__tests__/` / `__mocks__/` / `fixtures/` / `__fixtures__/` /
 * `__testfixtures__/` directory.
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
