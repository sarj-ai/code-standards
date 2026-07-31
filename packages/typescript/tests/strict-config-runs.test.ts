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

  it("accepts PascalCase React component names", async () => {
    const namingFindings = (await lint("widget.tsx")).filter(
      (message) => message.ruleId === "@typescript-eslint/naming-convention",
    );
    expect(namingFindings).toEqual([]);
  });

  it("keeps every configured react rule active on ESLint 10", async () => {
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
      expect(leftovers.length).toBeGreaterThan(0);
    }
  });

  it("runs a React rule through the ESLint compatibility layer", async () => {
    const messages = await lint("widget.tsx");
    expect(messages.every((message) => message.fatal !== true)).toBe(true);
  });
});
