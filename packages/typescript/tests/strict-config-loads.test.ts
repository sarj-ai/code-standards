/**
 * Actually LOADS the shipped ESLint config.
 *
 * `strict-config-sync.test.ts` next door compares rule NAMES by parsing the
 * config as text; it never executes it, and `make lint` is ruff-only. So the
 * whole class of "the config is syntactically fine and semantically broken"
 * shipped undetected:
 *
 *   - a rule option that does not match the rule's schema
 *     ("unicorn/relative-url-style": ["error", "bogus"]),
 *   - a rule renamed or removed upstream
 *     ("unicorn/throw-new-error-RENAMED"),
 *   - a plugin that no longer exports what the config imports.
 *
 * Every one of those is a hard TypeError the moment ESLint normalises the
 * config, and a silent nothing until then. Both fault shapes above were
 * injected into the real config while writing this test and both failed it, so
 * the guard is verified rather than assumed.
 *
 * `calculateConfigForFile` is the cheapest call that forces full normalisation:
 * it resolves every config object, merges the `files`-scoped blocks for the
 * given path, and validates every rule id and every rule option against its
 * schema. It does NOT parse the file, so this stays fast and needs no tsconfig,
 * no type information, and no fixture source.
 *
 * The config is imported directly (rather than via `overrideConfigFile`) so that
 * Vitest's resolver applies: `vitest.config.ts` aliases `@sarj/eslint-plugin` to
 * this package's own `src/index.ts`, which means the test runs against the
 * working tree instead of a stale `dist/` and needs no build step. Every other
 * plugin the config imports is a real devDependency here.
 */

import { ESLint, type Linter } from "eslint";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import applicationConfig, {
  createConfig as createApplicationConfig,
} from "../../lint-configs/src/sarj_lint_configs/configs/eslint.application.mjs";
import strictConfig, {
  createConfig as createStrictConfig,
} from "../../lint-configs/src/sarj_lint_configs/configs/eslint.strict.mjs";

/**
 * Paths chosen to exercise every `files:`-scoped block in the config, because a
 * bad option inside an override only surfaces when that override merges in:
 * the base block, the `.tsx` filename-case + better-tailwindcss overrides, the
 * test-file relaxations, the design-system exemption, and the env
 * source-of-truth block that switches `@sarj/no-raw-env` off.
 */
const PROBE_PATHS = [
  "src/index.ts",
  "src/components/thing.tsx",
  "src/thing.test.ts",
  "src/components/ui/button.tsx",
  "src/env/server-env.ts",
  "vite.config.ts",
] as const;
const NESTED_MONOREPO_ROOT = new URL("fixtures/nested-monorepo/", import.meta.url);
const UNTYPED_ROOT = new URL("fixtures/no-type-project/", import.meta.url);
type ConfigFactory = (options?: {
  tsconfigRootDir?: string | URL;
  projectService?: boolean | object;
}) => Linter.Config[];
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createStrictConfig],
  ["application", createApplicationConfig],
];
const STRICT_CONFIG_FACTORY = createStrictConfig as unknown as ConfigFactory;

function parserOptionsOf(config: Linter.Config[]): Record<string, unknown> {
  const options = config.find(
    (entry) => entry.languageOptions?.parserOptions?.tsconfigRootDir !== undefined,
  )?.languageOptions?.parserOptions;
  if (options === undefined) throw new Error("typed parser options are missing");
  return options as Record<string, unknown>;
}

async function configFor(filePath: string): Promise<Linter.Config> {
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: strictConfig as Linter.Config[],
    cwd: process.cwd(),
  });
  return (await eslint.calculateConfigForFile(filePath)) as Linter.Config;
}

describe("the shipped eslint.strict.mjs actually loads", () => {
  it.each(CONFIG_FACTORIES)("%s discovers nested workspace type projects", (_name, createConfig) => {
    const config = createConfig({ tsconfigRootDir: NESTED_MONOREPO_ROOT });
    const parserOptions = parserOptionsOf(config);

    expect(parserOptions.projectService).toBe(true);
    expect(parserOptions.tsconfigRootDir).toBe(fileURLToPath(NESTED_MONOREPO_ROOT));
    // Detection must keep typed rules active; merely setting parserOptions while
    // spreading UNTYPED_RULE_OVERRIDES would still produce a false clean result.
    const configured = config.find(
      (entry) => entry.rules?.["@typescript-eslint/await-thenable"] !== undefined,
    );
    expect(configured?.rules?.["@typescript-eslint/await-thenable"]).not.toBe("off");
  });

  it.each(CONFIG_FACTORIES)("%s degrades deliberately for an untyped root", (_name, createConfig) => {
    const config = createConfig({ tsconfigRootDir: UNTYPED_ROOT });
    expect(parserOptionsOf(config).projectService).toBe(false);
    const configured = [...config].reverse().find(
      (entry) => entry.rules?.["@typescript-eslint/await-thenable"] !== undefined,
    );
    expect(configured?.rules?.["@typescript-eslint/await-thenable"]).toBe("off");
  });

  it.each(CONFIG_FACTORIES)("%s normalizes its effective untyped config", async (_name, createConfig) => {
    const config = createConfig({ tsconfigRootDir: UNTYPED_ROOT });
    const eslint = new ESLint({
      cwd: fileURLToPath(UNTYPED_ROOT),
      overrideConfigFile: true,
      overrideConfig: config,
    });
    const configured = (await eslint.calculateConfigForFile("src/index.ts")) as Linter.Config;
    expect(configured?.rules?.["@typescript-eslint/await-thenable"]).toEqual([0]);
  });

  it("honors explicit project-service options without mutating the default export", () => {
    const projectService = { allowDefaultProject: ["eslint.config.mjs"] };
    const configured = STRICT_CONFIG_FACTORY({
      tsconfigRootDir: NESTED_MONOREPO_ROOT,
      projectService,
    });

    expect(parserOptionsOf(configured).projectService).toBe(projectService);
    expect(parserOptionsOf(strictConfig as Linter.Config[]).projectService).not.toBe(projectService);
  });

  it("globally ignores generated output", async () => {
    const eslint = new ESLint({
      overrideConfigFile: true,
      overrideConfig: strictConfig as Linter.Config[],
      cwd: process.cwd(),
    });
    expect(await eslint.calculateConfigForFile("dist/generated.js")).toBeUndefined();
    expect(await eslint.calculateConfigForFile(".astro/generated.d.ts")).toBeUndefined();
  });

  it.each(PROBE_PATHS)(
    "resolves without error for %s",
    async (filePath) => {
      const resolved = await configFor(filePath);
      // A config that resolved to nothing would pass a "did not throw" assertion
      // while linting nothing at all, which is the failure this file exists for.
      expect(Object.keys(resolved.rules ?? {}).length).toBeGreaterThan(100);
    },
  );

  /**
   * The overrides have to still WIN after merging. Asserting only that the
   * config loads would let a `files:` glob rot into matching nothing.
   */
  it("applies the files-scoped overrides it declares", async () => {
    // ESLint normalises severities to numbers by the time a config is
    // computed: 0 = off, 2 = error.
    const envConfig = await configFor("src/env/server-env.ts");
    expect(envConfig.rules?.["@sarj/no-raw-env"]).toEqual([0]);

    // A severity-only override keeps the options the earlier block set, so
    // compare the severity slot rather than the whole entry.
    const designSystemConfig = await configFor("src/components/ui/button.tsx");
    const forbidElements = designSystemConfig.rules?.["react/forbid-elements"];
    expect((forbidElements as unknown[])[0]).toBe(0);

    const plainConfig = await configFor("src/index.ts");
    expect(plainConfig.rules?.["@sarj/no-raw-env"]).toEqual([2]);

    const testConfig = await configFor("src/example.test.ts");
    expect(
      testConfig.rules?.["@typescript-eslint/consistent-type-assertions"]?.[0],
    ).toBe(0);
    expect(
      testConfig.rules?.["@typescript-eslint/no-unsafe-type-assertion"]?.[0],
    ).toBe(0);
    expect(testConfig.rules?.["@typescript-eslint/require-await"]?.[0]).toBe(0);
    expect(testConfig.rules?.["no-await-in-loop"]?.[0]).toBe(0);
    expect(plainConfig.rules?.["@typescript-eslint/require-await"]?.[0]).toBe(2);
    expect(plainConfig.rules?.["no-await-in-loop"]?.[0]).toBe(2);
    expect(plainConfig.rules?.["promise/prefer-await-to-then"]?.[0]).toBe(1);
    expect(plainConfig.rules?.["@typescript-eslint/member-ordering"]?.[0]).toBe(1);
    expect(plainConfig.rules?.["perfectionist/sort-classes"]?.[0]).toBe(0);
    expect(plainConfig.rules?.["@typescript-eslint/no-explicit-any"]?.[0]).toBe(2);
    expect(plainConfig.rules?.["@typescript-eslint/consistent-type-assertions"]?.[0]).toBe(2);
    expect(plainConfig.rules?.["simple-import-sort/imports"]?.[0]).toBe(2);
    expect(plainConfig.rules?.["simple-import-sort/exports"]?.[0]).toBe(2);

    // Component identifiers are PascalCase, while component filenames remain
    // kebab-case under the shared filename policy.
    const tsxConfig = await configFor("src/components/thing.tsx");
    const tsxNaming = tsxConfig.rules?.[
      "@typescript-eslint/naming-convention"
    ] as [number, ...Array<{ selector?: string; format?: string[] | null }>];
    const tsxDefaultNaming = tsxNaming
      .slice(1)
      .find((option) => option.selector === "default");
    expect(tsxDefaultNaming?.format).toContain("PascalCase");
    const tsxFilenameCase = tsxConfig.rules?.["unicorn/filename-case"] as
      | [number, { cases: Record<string, boolean> }]
      | undefined;
    expect(tsxFilenameCase?.[1].cases.kebabCase).toBe(true);
    expect(tsxFilenameCase?.[1].cases.pascalCase).toBeUndefined();
    const baseFilenameCase = plainConfig.rules?.["unicorn/filename-case"] as
      | [number, { cases: Record<string, boolean> }]
      | undefined;
    expect(baseFilenameCase?.[1].cases.pascalCase).toBeUndefined();
  });

  it("scopes shadcn primitive guidance outside design-system implementations", () => {
    const entries = applicationConfig as Linter.Config[];
    const globalEntry = entries.find(
      (entry) =>
        entry.rules?.["@sarj/prefer-shadcn-primitives"] === "warn",
    );
    expect(globalEntry).toBeDefined();

    const designSystemEntry = entries.find(
      (entry) =>
        entry.files?.includes("**/components/ui/**") &&
        entry.rules?.["@sarj/prefer-shadcn-primitives"] === "off",
    );
    expect(designSystemEntry).toBeDefined();
    expect(designSystemEntry?.files).toEqual(
      expect.arrayContaining([
        "**/*.{test,spec,e2e}.{js,jsx,ts,tsx}",
        "**/fixtures/**",
        "**/e2e-apps/**",
        "**/perf-regression/**",
      ]),
    );
  });

  /**
   * Every rule id the config names must exist in a loaded plugin. ESLint already
   * throws on an unknown id during normalisation, so this is belt-and-braces for
   * the shape it does NOT throw on: a rule that resolved but is deprecated
   * upstream, which is the step before removal and the last chance to notice.
   */
  it("enables no rule that its plugin has marked deprecated", async () => {
    const resolved = await configFor("src/components/thing.tsx");
    const plugins = (resolved as unknown as { plugins: Record<string, { rules?: Record<string, { meta?: { deprecated?: unknown } }> }> }).plugins;

    const deprecated = Object.keys(resolved.rules ?? {}).flatMap((ruleId) => {
      const lastSlash = ruleId.lastIndexOf("/");
      if (lastSlash === -1) return [];
      const pluginName = ruleId.slice(0, lastSlash);
      const ruleName = ruleId.slice(lastSlash + 1);
      const rule = plugins[pluginName]?.rules?.[ruleName];
      return rule?.meta?.deprecated !== undefined && rule.meta.deprecated !== false
        ? [ruleId]
        : [];
    });
    expect(deprecated).toEqual([]);
  });
});
