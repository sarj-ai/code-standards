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
  it.each([
    "react-hooks/error-boundaries",
    "react-hooks/globals",
    "react-hooks/immutability",
    "react-hooks/purity",
    "react-hooks/refs",
    "react-hooks/set-state-in-render",
    "react/no-object-type-as-default-prop",
    "react/no-unknown-property",
  ])("enables %s as an error", async (rule) => {
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: strictConfig as Linter.Config[],
    });
    const config = await eslint.calculateConfigForFile(
      resolve(FIXTURE_DIR, "widget.tsx"),
    );
    expect(config?.rules?.[rule]?.[0]).toBe(2);
  });

  it("requires explicit button types inside design-system primitives", () => {
    const primitiveConfig = (strictConfig as Linter.Config[]).find(
      (entry) =>
        entry.files?.includes("**/components/ui/**") &&
        entry.files.includes("**/components/design-system/**"),
    );
    expect(primitiveConfig?.rules?.["react/button-has-type"]).toBe("error");
  });

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
   * The config shipped with no `ignores`, so `eslint .` linted build output.
   *
   * Measured over 175,852 deduplicated files: 24.4% of all `@sarj/*` findings
   * landed on generated paths. The two fixtures below are byte-identical and
   * both violate; only their directory differs, so a pass here means the
   * ignore is doing the work and nothing else is.
   */
  it("ignores build output and still lints the identical authored file", async () => {
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: strictConfig as Linter.Config[],
      warnIgnored: false,
    });

    const [authored] = await eslint.lintFiles([
      resolve(FIXTURE_DIR, "src/authored.ts"),
    ]);
    const authoredRules = (authored?.messages ?? []).map((m) => m.ruleId);
    expect(authoredRules).toContain("@sarj/no-enum");

    // Same bytes under `lib/`. `lintFiles` on an explicitly named ignored path
    // returns a result with zero messages, so assert on the messages rather
    // than on the result count.
    const compiled = await eslint.lintFiles([
      resolve(FIXTURE_DIR, "lib/compiled.ts"),
    ]);
    expect(compiled.flatMap((r) => r.messages)).toEqual([]);

    // The ignore must be a GLOBAL ignore: an entry that grows a `files` key
    // stops ignoring anything, and nothing else in the config would notice.
    const globalIgnores = (strictConfig as Linter.Config[]).filter(
      (entry) => entry.ignores !== undefined && entry.files === undefined,
    );
    expect(globalIgnores.length).toBe(1);
  });

  /**
   * The 18 react rules were dropped wholesale because eslint-plugin-react calls
   * `context.getFilename()`, removed in ESLint 10. Dropping them swapped a crash
   * for silence: every consumer got zero React coverage. `@eslint/compat`'s
   * `fixupPluginRules` restores the removed context APIs, so the rules run.
   */
  it("keeps every react/* key live through the compat adapter", async () => {
    const major = Number.parseInt(ESLint.version.split(".")[0] ?? "0", 10);
    if (major < 10) return; // guard inactive on ESLint 9; nothing to assert

    // A react/* key is only safe when the plugin is registered AND its removed
    // context APIs are restored -- otherwise it is "Definition for rule not
    // found", or a crash, at consumer lint time.
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: strictConfig as Linter.Config[],
    });
    for (const probe of ["example.ts", "widget.tsx"]) {
      const resolved = await eslint.calculateConfigForFile(
        resolve(FIXTURE_DIR, probe),
      );
      const live = Object.keys(resolved.rules ?? {}).filter((rule) =>
        rule.startsWith("react/"),
      );
      expect(
        live.length,
        `${probe}: react rules were dropped again -- consumers lose React coverage silently`,
      ).toBeGreaterThan(0);
    }
  });

  it("fails once eslint-plugin-react supports ESLint 10, so the adapter expires", async () => {
    const major = Number.parseInt(ESLint.version.split(".")[0] ?? "0", 10);
    if (major < 10) return;

    // `lib/util/version.js` is what calls the removed `context.getFilename()`.
    // This probes the RAW plugin, not the fixed-up one, so it is an honest
    // upstream check: when a release fixes it this stops throwing, this test
    // fails, and the @eslint/compat wrapper gets deleted rather than living on.
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
      "eslint-plugin-react now runs on ESLint 10 -- drop fixupPluginRules from eslint.strict.mjs",
    ).toBe(true);
  });
});
