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

/**
 * True for a test file: a `*.test.*` / `*.spec.*` basename, or anything under a
 * `test/` / `tests/` / `__tests__/` / `__mocks__/` / `fixtures/` directory.
 */
export function isTestFile(filename: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  const base = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (/\.(test|spec)\.[cm]?[jt]sx?$/.test(base)) {
    return true;
  }
  return /(^|\/)(tests?|__tests__|__mocks__|fixtures)\//.test(normalized);
}

/**
 * True for one-off tooling files: anything under a `scripts/` directory or a
 * `*.mjs` file. Dev scripts run interactively and die with the terminal, so
 * production-hardening rules (e.g. fetch timeouts) do not apply there.
 */
export function isScriptFile(filename: string): boolean {
  return SCRIPT_FILE_RE.test(filename);
}
