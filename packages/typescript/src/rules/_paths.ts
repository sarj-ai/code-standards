/**
 * @fileoverview _paths — shared file-kind predicates, so "is this a test / script / generated file?" is answered in exactly one place.
 *
 * A path joins a shared default only if its NAME makes a claim true for every rule; anything one rule needs alone is a named gate that rule opts into.
 *
 */

const SCRIPT_FILE_RE = /([\\/]scripts[\\/])|(\.mjs$)/;

const STORY_FILE_RE = /\.stories\.[cm]?[jt]sx?$/i;
// `storyTree` includes Storybook's suffixed directories. It stays opt-in because
// some repositories keep production components under `stories/`.
const STORY_TREE_RE = /(^|\/)stories(?:[_-][^/]*)?\//i;

// These directory names explicitly identify upstream-owned code, so every rule
// may safely ignore them.
const GENERATED_FILE_RE =
  /((?:^|[\\/])(?:generated|__generated__|openapi-gen|graphql[\\/]types|vendor|vendored|third[-_]?party)[\\/])|(\.gen\.[cm]?[jt]sx?$)|(\.generated\.[cm]?[jt]sx?$)|(\.d\.[cm]?ts$)/i;
// `externalTree` stays opt-in because `external/` often contains first-party
// integration code.
const EXTERNAL_TREE_RE = /[\\/]external[\\/]/;

// A banner must claim that the file itself is generated. This avoids treating
// prose about generated values or warnings as generated-file declarations.
const GENERATED_MARKER_RE =
  /(?:@generated\b|this file (?:is|was|has been)[\w\s,'-]{0,40}?generated|auto-?generated file\b|code\s+generated (?:with|by)|^generated\s+(?:with|by)\b|generated (?:graphql )?types|\bgenerated\b.*\bdo not edit\b|\bdo not edit\b.*\bgenerated\b|do not (?:modify|change) this file)/i;
const DO_NOT_EDIT_RE = /^do not edit(?: directly| manually)?[.!]?$/i;
const AI_ATTRIBUTION_RE =
  /\b(?:@?generated|authored|written)(?:\s+\w+){0,2}\s+(?:by|with|using|via)\s+(?:an?\s+)?(?:ai|llm|openai|anthropic|chatgpt|chat-gpt|claude|codex|(?:github\s+)?copilot|gemini|gpt\s*-?\s*\d[\w.]*|cursor|amazon\s+q|language\s+model|assistant)\b/i;
const TEST_BASENAME_RE = /[.\-_](test|spec|e2e)\.[cm]?[jt]sx?$/;
const TEST_INTEGRATION_BASENAME_RE = /\.integration\.[cm]?[jt]sx?$/;
// Double-underscore fixture directories are alternate spellings of `fixtures/`.
const TEST_DIR_RE = /(^|\/)(tests?|__tests__|__mocks__|fixtures|__fixtures__|__testfixtures__|e2e|integration)\//;
// Singular `fixture/` stays opt-in because it can contain production seeders.
const FIXTURE_TREE_RE = /(^|\/)fixture\//;

/** Extra path gates that `isGeneratedFile` honours on request. */
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
 * The banner arm is universal; the path arm defaults to generator output and
 * vendored trees, while `["externalTree"]` adds `external/`.
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
  const headerBodies = leadingCommentBodies(sourceText.slice(0, 2048));
  const nonAi = headerBodies.filter((body) => !AI_ATTRIBUTION_RE.test(body));
  if (nonAi.some((body) => GENERATED_MARKER_RE.test(body))) {
    return true;
  }
  return !headerBodies.some((body) => AI_ATTRIBUTION_RE.test(body)) &&
    headerBodies.some((body) => DO_NOT_EDIT_RE.test(body));
}

/** Read only leading comment trivia, so strings and comments after code cannot claim ownership. */
function leadingCommentBodies(sourceText: string): string[] {
  const bodies: string[] = [];
  let index = 0;
  if (sourceText.startsWith("#!")) {
    const shebangEnd = sourceText.indexOf("\n");
    index = shebangEnd === -1 ? sourceText.length : shebangEnd + 1;
  }
  while (index < sourceText.length) {
    while (/\s/u.test(sourceText[index] ?? "")) index++;
    if (sourceText.startsWith("//", index)) {
      const end = sourceText.indexOf("\n", index + 2);
      const stop = end === -1 ? sourceText.length : end;
      bodies.push(sourceText.slice(index + 2, stop).trim());
      index = stop;
      continue;
    }
    if (sourceText.startsWith("/*", index)) {
      const end = sourceText.indexOf("*/", index + 2);
      if (end === -1) break;
      bodies.push(
        ...sourceText
          .slice(index + 2, end)
          .split("\n")
          .map((line) => line.replace(/^\s*\*?\s?/u, "").trim())
          .filter((line) => line.length > 0),
      );
      index = end + 2;
      continue;
    }
    // Some callers pass an extracted JSDoc body rather than a full file.
    if (sourceText[index] === "*") {
      const end = sourceText.indexOf("\n", index + 1);
      const stop = end === -1 ? sourceText.length : end;
      bodies.push(sourceText.slice(index + 1, stop).trim());
      index = stop;
      continue;
    }
    break;
  }
  return bodies;
}

/**
 * True for one-off tooling files: anything under a `scripts/` directory or a
 * `*.mjs` file. Dev scripts run interactively and die with the terminal, so
 * production-hardening rules (e.g. fetch timeouts) do not apply there.
 */
export function isScriptFile(filename: string): boolean {
  return SCRIPT_FILE_RE.test(filename);
}
