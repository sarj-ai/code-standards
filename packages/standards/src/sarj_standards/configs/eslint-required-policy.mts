import { createRequire } from "node:module";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

import type { ESLint as NativeESLint, Linter } from "eslint";

const require = createRequire(resolve("package.json"));
const { ESLint } = require("eslint") as typeof import("eslint");
const tseslint =
  require("typescript-eslint") as typeof import("typescript-eslint");
const pluginRequire = createRequire(require.resolve("@sarj/eslint-plugin"));
const comments = pluginRequire(
  "@eslint-community/eslint-plugin-eslint-comments",
) as NativeESLint.Plugin;
const sarj = require("@sarj/eslint-plugin") as NativeESLint.Plugin & {
  readonly default?: NativeESLint.Plugin;
};
const PREFIX = "@eslint-community/eslint-comments/";
const PROTECTED_RULES = [
  "require-description",
  "no-unlimited-disable",
  "no-use",
  "disable-enable-pair",
  "no-aggregating-enable",
  "no-duplicate-disable",
  "no-unused-enable",
  "no-restricted-disable",
].map((name) => PREFIX + name);

// This is the full gate's non-waivable floor. Ordinary lint still owns its
// complete project configuration, parser services and local exceptions.
const REQUIRED_RULES: Linter.RulesRecord = {
  [PREFIX + "require-description"]: ["error", { ignore: [] }],
  [PREFIX + "no-unlimited-disable"]: "error",
  [PREFIX + "no-use"]: [
    "error",
    {
      allow: [
        "eslint-disable-line",
        "eslint-disable-next-line",
        "eslint-env",
        "exported",
        "global",
        "globals",
      ],
    },
  ],
  [PREFIX + "disable-enable-pair"]: ["error", { allowWholeFile: false }],
  [PREFIX + "no-aggregating-enable"]: "error",
  [PREFIX + "no-duplicate-disable"]: "error",
  [PREFIX + "no-unused-enable"]: "error",
  [PREFIX + "no-restricted-disable"]: [
    "error",
    ...PROTECTED_RULES,
    "no-console",
    "react-hooks/exhaustive-deps",
    "@sarj/no-vague-suppression-description",
    "@typescript-eslint/ban-ts-comment",
  ],
  "@sarj/no-vague-suppression-description": "error",
  "@typescript-eslint/ban-ts-comment": [
    "error",
    {
      "ts-check": false,
      "ts-expect-error": "allow-with-description",
      "ts-ignore": true,
      "ts-nocheck": true,
      minimumDescriptionLength: 3,
    },
  ],
};

export async function requiredSuppressionResults(
  files: string[],
): Promise<NativeESLint.LintResult[]> {
  const absoluteFiles = files.map((file) => resolve(file));
  if (absoluteFiles.length === 0) return [];
  // A provider can lint sibling tooling outside its package. The syntax-only
  // floor has no project services, so root it at the inputs' common ancestor.
  let sourceRoot = dirname(absoluteFiles[0] ?? process.cwd());
  for (const file of absoluteFiles) {
    let fromRoot = relative(sourceRoot, file);
    while (
      fromRoot === ".." ||
      fromRoot.startsWith(`..${sep}`) ||
      isAbsolute(fromRoot)
    ) {
      const parent = dirname(sourceRoot);
      if (parent === sourceRoot)
        throw new Error(
          "Required policy inputs do not share a filesystem root",
        );
      sourceRoot = parent;
      fromRoot = relative(sourceRoot, file);
    }
  }
  const eslint = new ESLint({
    cwd: sourceRoot,
    overrideConfigFile: true,
    ignore: false,
    warnIgnored: false,
    cache: false,
    applySuppressions: false,
    overrideConfig: {
      files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
      languageOptions: {
        parser: tseslint.parser,
        parserOptions: {
          tsconfigRootDir: sourceRoot,
          project: false,
          projectService: false,
          ecmaFeatures: { jsx: true },
        },
      },
      plugins: {
        "@eslint-community/eslint-comments": comments,
        "@typescript-eslint": tseslint.plugin,
        "@sarj": sarj.default ?? sarj,
      },
      rules: REQUIRED_RULES,
      linterOptions: {
        noInlineConfig: true,
        reportUnusedDisableDirectives: "off",
        reportUnusedInlineConfigs: "off",
      },
    },
  });
  const results = await eslint.lintFiles(absoluteFiles);
  const covered = new Set(results.map((result) => resolve(result.filePath)));
  if (absoluteFiles.some((file) => !covered.has(file))) {
    throw new Error(
      "Required suppression policy did not analyze every selected source file",
    );
  }
  return results.map((result) => ({
    ...result,
    // Ignore ESLint's advisory that a source directive has no effect in this
    // pass. The ordinary pass already applies and validates local exceptions.
    messages: result.messages
      .filter((message) => message.ruleId !== null || message.fatal === true)
      .map((message) => ({ ...message, sarjRequiredSourcePolicy: true })),
  }));
}
