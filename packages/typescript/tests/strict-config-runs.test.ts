/**
 * Runs the shipped config over real files, which `calculateConfigForFile` cannot.
 *
 * `strict-config-loads.test.ts` next door normalises the config: it resolves
 * every config object and validates every rule id and option against its schema.
 * What it never does is LOAD a rule's implementation, so a plugin that is
 * installable, importable, schema-valid and still broken passes it.
 *
 * That is not hypothetical. `eslint-plugin-react@7.37.5` — the newest published
 * release — calls `context.getFilename()`, removed in ESLint 10, and this config
 * requires ESLint 10 (its unicorn floor pulls `>= 10.4`). Every react rule threw
 * `TypeError: contextOrFilename.getFilename is not a function` on the first file
 * linted, while every existing test passed. A consumer following the README hit
 * a stack trace with no way to tell a broken shared config from their own
 * mistake — and copying the file and deleting imports is the fastest way out of
 * that, which is how vendoring starts.
 *
 * `lintFiles` is the only call that proves the config works. It is slower than
 * `calculateConfigForFile`, so this file lints two small fixtures rather than a
 * corpus: one `.ts` and one `.tsx`, because the `.tsx`-scoped overrides bring in
 * blocks the `.ts` path never merges.
 */

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import strictConfig from "../../lint-configs/src/sarj_lint_configs/configs/eslint.strict.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE_DIR = resolve(HERE, "fixtures/runs");

async function lint(file: string): Promise<Linter.LintMessage[]> {
  const eslint = new ESLint({
    cwd: FIXTURE_DIR,
    overrideConfigFile: true,
    overrideConfig: strictConfig as Linter.Config[],
  });
  const results = await eslint.lintFiles([resolve(FIXTURE_DIR, file)]);
  return results.flatMap((result) => result.messages);
}

describe("the shipped eslint.strict.mjs can actually lint", () => {
  it.each(["example.ts", "widget.tsx"])(
    "lints %s without a rule throwing",
    async (file) => {
      const messages = await lint(file);
      // ESLint surfaces a crashed rule as a fatal message rather than a throw
      // for some failure modes, so assert on both paths.
      const fatal = messages.filter((message) => message.fatal === true);
      expect(fatal).toEqual([]);
    },
  );

  it("reports real findings, so a silent pass cannot be mistaken for success", async () => {
    const ruleIds = new Set((await lint("example.ts")).map((m) => m.ruleId));
    expect(ruleIds.has("@sarj/no-enum")).toBe(true);
    // A type-aware rule must fire too, or `projectService` failed to find a
    // tsconfig and the entire typed half of the config was inert.
    expect(
      [...ruleIds].some((rule) => rule?.startsWith("@typescript-eslint/")),
    ).toBe(true);
  });

  /**
   * The react guard is a workaround with an expiry date. When
   * eslint-plugin-react ships ESLint 10 support this test fails, which is the
   * prompt to delete the guard rather than leave 18 rules quietly disabled
   * forever — the exact "written but inert" failure the rule set exists to catch.
   */
  it("drops every react/* key while the guard is active", async () => {
    const major = Number.parseInt(ESLint.version.split(".")[0] ?? "0", 10);
    if (major < 10) return; // guard inactive on ESLint 9; nothing to assert

    // A leftover `react/*` key with the plugin unregistered is "Definition for
    // rule not found" at consumer lint time -- swapping one broken config for
    // another.
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: strictConfig as Linter.Config[],
    });
    for (const probe of ["example.ts", "widget.tsx"]) {
      const resolved = await eslint.calculateConfigForFile(
        resolve(FIXTURE_DIR, probe),
      );
      const leftovers = Object.keys(resolved.rules ?? {}).filter((rule) =>
        rule.startsWith("react/"),
      );
      expect(leftovers).toEqual([]);
    }
  });

  it("fails once eslint-plugin-react supports ESLint 10, so the guard expires", async () => {
    const major = Number.parseInt(ESLint.version.split(".")[0] ?? "0", 10);
    if (major < 10) return;

    // `lib/util/version.js` is what calls the removed `context.getFilename()`.
    // Running one react rule for real is the only honest expiry check: when a
    // release fixes it this stops throwing, this test fails, and the guard --
    // plus 18 quietly disabled rules -- gets deleted instead of living forever.
    const { default: react } = await import("eslint-plugin-react");
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: [
        {
          files: ["**/*.tsx"],
          plugins: { react },
          rules: { "react/no-unstable-nested-components": "error" },
        },
      ] as Linter.Config[],
    });
    const [result] = await eslint.lintFiles([resolve(FIXTURE_DIR, "widget.tsx")]);
    const fatal = (result?.messages ?? []).filter((m) => m.fatal === true);
    expect(
      fatal.length > 0,
      "eslint-plugin-react now runs on ESLint 10 -- delete the guard in eslint.strict.mjs",
    ).toBe(true);
  });
});
