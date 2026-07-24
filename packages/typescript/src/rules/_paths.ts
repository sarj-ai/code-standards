/**
 * @fileoverview Shared filename predicates for rules that exempt whole file
 * categories. One definition (mirroring the Python `_paths.py` extraction) so
 * the per-rule test-file regexes cannot drift apart again.
 */

const TEST_FILE_RE = /(\.(test|spec)\.)|([\\/]__tests__[\\/])/;

const SCRIPT_FILE_RE = /([\\/]scripts[\\/])|(\.mjs$)/;

/** True for test files: `*.test.*`, `*.spec.*`, or anything under `__tests__/`. */
export function isTestFile(filename: string): boolean {
  return TEST_FILE_RE.test(filename);
}

/**
 * True for one-off tooling files: anything under a `scripts/` directory or a
 * `*.mjs` file. Dev scripts run interactively and die with the terminal, so
 * production-hardening rules (e.g. fetch timeouts) do not apply there.
 */
export function isScriptFile(filename: string): boolean {
  return SCRIPT_FILE_RE.test(filename);
}
