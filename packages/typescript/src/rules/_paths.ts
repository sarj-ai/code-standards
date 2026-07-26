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
const GENERATED_FILE_RE = /([\\/]generated[\\/])|(\.gen\.[cm]?[jt]sx?$)|(\.generated\.[cm]?[jt]sx?$)|(\.d\.[cm]?ts$)/;

/**
 * True for a test file: a `*.test.*` / `*.spec.*` basename, or anything under a
 * `test/` / `tests/` / `__tests__/` / `__mocks__/` / `fixtures/` directory.
 */
export function isTestFile(filename: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  const base = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (/\.(test|spec|e2e|integration)\.[cm]?[jt]sx?$/.test(base)) {
    return true;
  }
  return /(^|\/)(tests?|__tests__|__mocks__|fixtures|e2e|integration)\//.test(normalized);
}

export function isStoryFile(filename: string): boolean {
  return STORY_FILE_RE.test(filename);
}

export function isGeneratedFile(filename: string, sourceText = ""): boolean {
  return GENERATED_FILE_RE.test(filename.replaceAll("\\", "/")) || /@generated\b/.test(sourceText.slice(0, 1024));
}

/**
 * True for one-off tooling files: anything under a `scripts/` directory or a
 * `*.mjs` file. Dev scripts run interactively and die with the terminal, so
 * production-hardening rules (e.g. fetch timeouts) do not apply there.
 */
export function isScriptFile(filename: string): boolean {
  return SCRIPT_FILE_RE.test(filename);
}
