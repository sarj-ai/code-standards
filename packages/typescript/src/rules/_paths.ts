/**
 * @fileoverview _paths — shared file-kind predicates, so "is this a test / script / generated file?" is answered in exactly one place.
 *
 * A path joins a shared default only if its NAME makes a claim true for every rule; anything one rule needs alone is a named gate that rule opts into.
 *
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/_paths.md
 */

const SCRIPT_FILE_RE = /([\\/]scripts[\\/])|(\.mjs$)/;

const STORY_FILE_RE = /\.stories\.[cm]?[jt]sx?$/i;
// Gate `storyTree`. Storybook's own `stories_vue3-vite-default-ts/` spelling
// included. Not a default: plenty of repos keep ordinary first-party components
// under `stories/`, and to a rule about `process.env` those are production.
const STORY_TREE_RE = /(^|\/)stories(?:[_-][^/]*)?\//i;

// `vendor` / `vendored` / `third[-_]?party` are shared, mirroring Python's
// `_GENERATED_DIR_NAMES`: the directory name is itself the claim that an
// upstream owns the text, and that claim holds for every rule.
const GENERATED_FILE_RE =
  /([\\/](?:generated|openapi-gen|graphql[\\/]types|vendor|vendored|third[-_]?party)[\\/])|(\.gen\.[cm]?[jt]sx?$)|(\.generated\.[cm]?[jt]sx?$)|(\.d\.[cm]?ts$)|(\.types\.[cm]?ts$)/;
// Gate `externalTree`. Some `external/` trees really are a copy of someone
// else's typings, but `src/services/external/` is first-party outbound
// integration in most repos — the place a raw `process.env` read or an untimed
// `fetch` matters most — so this cannot be a shared default.
const EXTERNAL_TREE_RE = /[\\/]external[\\/]/;

// A BANNER match is safe and universal in a way a PATH match is not: no
// hand-written file claims to be generator output. Subject-scoped on purpose —
// the file itself has to be what the claim is ABOUT. See the evidence file.
const GENERATED_MARKER_RE =
  /(?:@generated\b|this file (?:is|was|has been)[\w\s,'-]{0,40}?generated|auto-?generated file\b|generated (?:with|by)|generated (?:graphql )?types|do not edit(?: directly| manually)?|do not (?:modify|change) this file)/i;

const TEST_BASENAME_RE = /[.\-_](test|spec|e2e)\.[cm]?[jt]sx?$/;
const TEST_INTEGRATION_BASENAME_RE = /\.integration\.[cm]?[jt]sx?$/;
// `__fixtures__` / `__testfixtures__` are shared: the same category as the
// `fixtures/` that has always been here, spelled the way jscodeshift and
// Storybook spell it.
const TEST_DIR_RE = /(^|\/)(tests?|__tests__|__mocks__|fixtures|__fixtures__|__testfixtures__|e2e|integration)\//;
// Gate `fixtureTree`: the SINGULAR `fixture/`. `src/fixture/seed.ts` is a
// production database seeder in several repos, so exempting it from every
// consumer of `isTestFile` is a scope change nobody asked for.
const FIXTURE_TREE_RE = /(^|\/)fixture\//;

/**
 * Extra path gates `isGeneratedFile` honours on request. Not a default: see the
 * evidence document.
 */
export type GeneratedPathGate = "externalTree";

/** Extra path gates `isTestFile` honours on request. */
export type TestPathGate = "fixtureTree";

/** Extra path gates `isStoryFile` honours on request. */
export type StoryPathGate = "storyTree";

/**
 * True for a test file: a `*.test.*` / `*.spec.*` basename, the `-test` /
 * `_test` suffix forms of the same, or anything under a `test/` / `tests/` /
 * `__tests__/` / `__mocks__/` / `fixtures/` / `__fixtures__/` /
 * `__testfixtures__/` / `e2e/` / `integration/` directory.
 *
 * Pass `["fixtureTree"]` to also exempt the singular `fixture/`.
 */
export function isTestFile(filename: string, gates: readonly TestPathGate[] = []): boolean {
  const normalized = filename.replaceAll("\\", "/");
  const base = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (TEST_BASENAME_RE.test(base) || TEST_INTEGRATION_BASENAME_RE.test(base)) {
    return true;
  }
  if (TEST_DIR_RE.test(normalized)) {
    return true;
  }
  return gates.includes("fixtureTree") && FIXTURE_TREE_RE.test(normalized);
}

/**
 * True for a `*.stories.*` file. Pass `["storyTree"]` to also match anything
 * inside a `stories/` tree.
 */
export function isStoryFile(filename: string, gates: readonly StoryPathGate[] = []): boolean {
  const normalized = filename.replaceAll("\\", "/");
  if (STORY_FILE_RE.test(normalized)) {
    return true;
  }
  return gates.includes("storyTree") && STORY_TREE_RE.test(normalized);
}

/**
 * True for a file whose text an upstream owns: generator output or a vendored
 * copy by path, or any file whose own header declares it generated.
 *
 * The banner arm is universal. The path arm defaults to generator output and
 * vendored trees; `["externalTree"]` adds `external/`.
 */
export function isGeneratedFile(
  filename: string,
  sourceText = "",
  gates: readonly GeneratedPathGate[] = [],
): boolean {
  const normalized = filename.replaceAll("\\", "/");
  if (GENERATED_FILE_RE.test(normalized)) {
    return true;
  }
  if (gates.includes("externalTree") && EXTERNAL_TREE_RE.test(normalized)) {
    return true;
  }
  return GENERATED_MARKER_RE.test(sourceText.slice(0, 2048));
}

/**
 * True for one-off tooling files: anything under a `scripts/` directory or a
 * `*.mjs` file. Dev scripts run interactively and die with the terminal, so
 * production-hardening rules (e.g. fetch timeouts) do not apply there.
 */
export function isScriptFile(filename: string): boolean {
  return SCRIPT_FILE_RE.test(filename);
}
