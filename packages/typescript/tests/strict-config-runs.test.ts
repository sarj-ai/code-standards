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

import {
  createConfig as createApplicationConfig,
} from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import strictConfig, {
  createConfig as createStrictConfig,
} from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";
import { rulesOf } from "./_config.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE_DIR = resolve(HERE, "fixtures/runs");
const NESTED_MONOREPO_DIR = resolve(HERE, "fixtures/nested-monorepo");
type ConfigFactory = (options?: {
  tsconfigRootDir?: string | URL;
  projectService?: boolean | object;
  syntaxOnlyConfigFiles?: string[];
}) => Linter.Config[];
const STRICT_CONFIG_FACTORY = createStrictConfig as unknown as ConfigFactory;
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createStrictConfig],
  ["application", createApplicationConfig],
];

async function lint(file: string): Promise<Linter.LintMessage[]> {
  const eslint = new ESLint({
    cwd: FIXTURE_DIR,
    overrideConfigFile: true,
    overrideConfig: strictConfig as Linter.Config[],
  });
  const results = await eslint.lintFiles([resolve(FIXTURE_DIR, file)]);
  return results.flatMap((result) => result.messages);
}

function severity(setting: unknown): unknown {
  return Array.isArray(setting) ? setting[0] : setting;
}

const ESLINT_MAJOR = Number.parseInt(ESLint.version.split(".")[0] ?? "0", 10);

describe("the shipped eslint.strict.mjs can actually lint", () => {
  it("keeps typed diagnostics live in a nested monorepo package", async () => {
    const eslint = new ESLint({
      cwd: NESTED_MONOREPO_DIR,
      overrideConfigFile: true,
      overrideConfig: STRICT_CONFIG_FACTORY({
        tsconfigRootDir: NESTED_MONOREPO_DIR,
      }),
    });
    const [result] = await eslint.lintFiles([
      resolve(NESTED_MONOREPO_DIR, "packages/example/src/index.ts"),
    ]);
    const fatal = result?.messages.filter((message) => message.fatal === true) ?? [];
    expect(fatal).toEqual([]);
    expect(result?.messages.map((message) => message.ruleId)).toContain(
      "@typescript-eslint/await-thenable",
    );
  });

  it.each(CONFIG_FACTORIES)(
    "%s lints an excluded Vite config with syntax-aware rules",
    async (_name, createConfig) => {
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: createConfig({ tsconfigRootDir: NESTED_MONOREPO_DIR }),
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/vite.config.ts"),
      ]);

      expect(result?.messages.filter((message) => message.fatal === true)).toEqual([]);
      expect(result?.messages.map((message) => message.ruleId)).toContain("@sarj/no-enum");
      expect(result?.messages.map((message) => message.ruleId)).not.toContain(
        "@typescript-eslint/await-thenable",
      );
    },
  );

  it.each(CONFIG_FACTORIES)(
    "%s lints dependency-cruiser config without requiring project ownership",
    async (_name, createConfig) => {
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: createConfig({ tsconfigRootDir: NESTED_MONOREPO_DIR }),
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/.dependency-cruiser.cjs"),
      ]);

      expect(result?.messages.filter((message) => message.fatal === true)).toEqual([]);
      expect(result?.messages.map((message) => message.ruleId)).toContain("no-var");
      expect(result?.messages.map((message) => message.ruleId)).not.toContain(
        "@typescript-eslint/await-thenable",
      );
    },
  );

  it.each(CONFIG_FACTORIES)(
    "%s lints shared ESLint config without requiring project ownership",
    async (_name, createConfig) => {
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: createConfig({ tsconfigRootDir: NESTED_MONOREPO_DIR }),
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/eslint.config.base.js"),
      ]);

      expect(result?.messages.filter((message) => message.fatal === true)).toEqual([]);
      expect(result?.messages.map((message) => message.ruleId)).toContain("no-var");
      expect(result?.messages.map((message) => message.ruleId)).not.toContain(
        "@typescript-eslint/await-thenable",
      );
    },
  );

  it.each(CONFIG_FACTORIES)(
    "%s keeps an owned generic config type-aware by default",
    async (_name, createConfig) => {
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: createConfig({ tsconfigRootDir: NESTED_MONOREPO_DIR }),
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/src/domain.config.ts"),
      ]);

      expect(result?.messages.filter((message) => message.fatal === true)).toEqual([]);
      expect(result?.messages.map((message) => message.ruleId)).toContain(
        "@typescript-eslint/await-thenable",
      );
    },
  );

  it.each(CONFIG_FACTORIES)(
    "%s limits member ordering to class accessibility bands",
    async (_name, createConfig) => {
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: createConfig({ tsconfigRootDir: NESTED_MONOREPO_DIR }),
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/src/member-ordering.ts"),
      ]);

      expect(result?.messages.map((message) => message.ruleId)).not.toContain(
        "@typescript-eslint/member-ordering",
      );
    },
  );

  it.each(CONFIG_FACTORIES)(
    "%s requires module constants to use UPPER_CASE without renaming function APIs",
    async (_name, createConfig) => {
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: createConfig({ tsconfigRootDir: NESTED_MONOREPO_DIR }),
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/src/constant-naming.ts"),
      ]);
      const namingMessages = result?.messages.filter(
        (message) => message.ruleId === "@typescript-eslint/naming-convention",
      );

      expect(namingMessages?.map((message) => message.message)).toEqual([
        "Variable name `moduleMetadata` must match one of the following formats: UPPER_CASE",
      ]);
    },
  );

  it.each(CONFIG_FACTORIES)(
    "%s lets consumers keep an owned Vite config type-aware",
    async (_name, createConfig) => {
      const config = createConfig({
        syntaxOnlyConfigFiles: [],
        tsconfigRootDir: NESTED_MONOREPO_DIR,
      });
      expect(config.some((entry) => entry.files?.length === 0)).toBe(false);
      const eslint = new ESLint({
        cwd: NESTED_MONOREPO_DIR,
        overrideConfigFile: true,
        overrideConfig: config,
      });

      const [result] = await eslint.lintFiles([
        resolve(NESTED_MONOREPO_DIR, "packages/example/src/vite.config.ts"),
      ]);

      expect(result?.messages.filter((message) => message.fatal === true)).toEqual([]);
      expect(result?.messages.map((message) => message.ruleId)).toContain(
        "@typescript-eslint/await-thenable",
      );
    },
  );

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
    const config: unknown = await eslint.calculateConfigForFile(
      resolve(FIXTURE_DIR, "widget.tsx"),
    );
    const setting = rulesOf(config)[rule];
    expect(severity(setting)).toBe(2);
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

  it("gives cross-accessibility ordering one diagnostic owner", async () => {
    const messages = await lint("stepdown-conflict.ts");
    const ordering = messages.filter((message) =>
      ["@typescript-eslint/member-ordering", "@sarj/stepdown", "perfectionist/sort-classes"].includes(message.ruleId ?? ""),
    );
    expect(ordering.map((message) => message.ruleId)).toEqual(["@typescript-eslint/member-ordering"]);
  });

  it("covers constructors and accessors without a stepdown ownership gap", async () => {
    const messages = await lint("stepdown-callable-conflicts.ts");
    const ordering = messages.filter((message) =>
      ["@typescript-eslint/member-ordering", "@sarj/stepdown", "perfectionist/sort-classes"].includes(message.ruleId ?? ""),
    );
    expect(ordering.map((message) => message.ruleId)).toEqual([
      "@typescript-eslint/member-ordering",
      "@typescript-eslint/member-ordering",
      "@typescript-eslint/member-ordering",
    ]);
  });

  it("enforces explicit await for a direct typed async return", async () => {
    const ruleIds = (await lint("promise-probe.ts")).map((message) => message.ruleId);
    expect(ruleIds).toContain("@sarj/prefer-await-in-async-return");
    expect(ruleIds).not.toContain("promise/prefer-await-to-then");
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

  it.each(CONFIG_FACTORIES)("%s ignores Yarn Plug'n'Play runtime files", async (_name, factory) => {
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: factory(),
      warnIgnored: false,
    });

    const generated = await eslint.lintFiles([
      resolve(FIXTURE_DIR, ".pnp.cjs"),
      resolve(FIXTURE_DIR, ".pnp.loader.mjs"),
    ]);

    expect(generated.flatMap((result) => result.messages)).toEqual([]);
  });

  /**
   * The 18 react rules were dropped wholesale because eslint-plugin-react calls
   * `context.getFilename()`, removed in ESLint 10. Dropping them swapped a crash
   * for silence: every consumer got zero React coverage. `@eslint/compat`'s
   * `fixupPluginRules` restores the removed context APIs, so the rules run.
   */
  it.runIf(ESLINT_MAJOR >= 10)("keeps every react/* key live through the compat adapter", async () => {
    // A react/* key is only safe when the plugin is registered AND its removed
    // context APIs are restored -- otherwise it is "Definition for rule not
    // found", or a crash, at consumer lint time.
    const eslint = new ESLint({
      cwd: FIXTURE_DIR,
      overrideConfigFile: true,
      overrideConfig: strictConfig as Linter.Config[],
    });
    const probes = await Promise.all(
      ["example.ts", "widget.tsx"].map(async (probe) => ({
        probe,
        resolved: await eslint.calculateConfigForFile(resolve(FIXTURE_DIR, probe)) as unknown,
      })),
    );
    expect(probes.map(({ probe }) => probe)).toEqual(["example.ts", "widget.tsx"]);
    expect(probes.every(({ resolved }) =>
      Object.keys(rulesOf(resolved)).some((rule) => rule.startsWith("react/"))
    )).toBe(true);
  });

  it.runIf(ESLINT_MAJOR >= 10)("fails once eslint-plugin-react supports ESLint 10, so the adapter expires", async () => {
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
