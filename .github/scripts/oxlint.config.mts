import type { OxlintConfig } from "oxlint";

// The repository tooling gate: ESLint's recommended rules and typescript-eslint's
// recommended-type-checked rules, as their native Oxlint ports. It lints these
// CI helpers and, through packages/standards/oxlint.config.mts, the Standards
// TypeScript helpers; packages/typescript/oxlint.config.mts extends it with
// every @sarj rule. Type-aware rules type each file through the repository's
// root tsconfig.json, which references packages/typescript/tsconfig.tools.json.
// The import is type-only, so Node loads this file without resolving `oxlint`.

// typescript-eslint turns these core rules off for TypeScript, whose compiler
// already reports them; JavaScript keeps them.
const JAVASCRIPT_ONLY = [
  "constructor-super",
  "getter-return",
  "no-class-assign",
  "no-const-assign",
  "no-dupe-class-members",
  "no-dupe-keys",
  "no-func-assign",
  "no-import-assign",
  "no-new-native-nonconstructor",
  "no-obj-calls",
  "no-redeclare",
  "no-setter-return",
  "no-this-before-super",
  "no-undef",
  "no-unreachable",
  "no-unsafe-negation",
  "no-with",
] as const;

// no-octal and no-dupe-args have no port; both are syntax errors in modules.
const CORE = [
  "for-direction",
  "no-array-constructor",
  "no-async-promise-executor",
  "no-case-declarations",
  "no-compare-neg-zero",
  "no-cond-assign",
  "no-constant-binary-expression",
  "no-constant-condition",
  "no-control-regex",
  "no-debugger",
  "no-delete-var",
  "no-dupe-else-if",
  "no-duplicate-case",
  "no-empty",
  "no-empty-character-class",
  "no-empty-pattern",
  "no-empty-static-block",
  "no-ex-assign",
  "no-extra-boolean-cast",
  "no-fallthrough",
  "no-global-assign",
  "no-invalid-regexp",
  "no-irregular-whitespace",
  "no-loss-of-precision",
  "no-misleading-character-class",
  "no-nonoctal-decimal-escape",
  "no-prototype-builtins",
  "no-regex-spaces",
  "no-self-assign",
  "no-shadow-restricted-names",
  "no-sparse-arrays",
  "no-unassigned-vars",
  "no-unexpected-multiline",
  "no-unsafe-finally",
  "no-unsafe-optional-chaining",
  "no-unused-expressions",
  "no-unused-labels",
  "no-unused-private-class-members",
  "no-unused-vars",
  "no-useless-assignment",
  "no-useless-backreference",
  "no-useless-catch",
  "no-useless-escape",
  "no-var",
  "prefer-const",
  "prefer-rest-params",
  "prefer-spread",
  "preserve-caught-error",
  "require-yield",
  "use-isnan",
  "valid-typeof",
] as const;

const TYPESCRIPT = [
  "typescript/await-thenable",
  "typescript/ban-ts-comment",
  "typescript/no-array-delete",
  "typescript/no-base-to-string",
  "typescript/no-duplicate-enum-values",
  "typescript/no-duplicate-type-constituents",
  "typescript/no-empty-object-type",
  "typescript/no-explicit-any",
  "typescript/no-extra-non-null-assertion",
  "typescript/no-floating-promises",
  "typescript/no-for-in-array",
  "typescript/no-implied-eval",
  "typescript/no-misused-new",
  "typescript/no-misused-promises",
  "typescript/no-namespace",
  "typescript/no-non-null-asserted-optional-chain",
  "typescript/no-redundant-type-constituents",
  "typescript/no-require-imports",
  "typescript/no-this-alias",
  "typescript/no-unnecessary-type-assertion",
  "typescript/no-unnecessary-type-constraint",
  "typescript/no-unsafe-argument",
  "typescript/no-unsafe-assignment",
  "typescript/no-unsafe-call",
  "typescript/no-unsafe-declaration-merging",
  "typescript/no-unsafe-enum-comparison",
  "typescript/no-unsafe-function-type",
  "typescript/no-unsafe-member-access",
  "typescript/no-unsafe-return",
  "typescript/no-unsafe-unary-minus",
  "typescript/no-wrapper-object-types",
  "typescript/only-throw-error",
  "typescript/prefer-as-const",
  "typescript/prefer-namespace-keyword",
  "typescript/prefer-promise-reject-errors",
  "typescript/require-await",
  "typescript/restrict-plus-operands",
  "typescript/restrict-template-expressions",
  "typescript/triple-slash-reference",
  "typescript/unbound-method",
] as const;

const turn = (rules: readonly string[], level: "error" | "off"): Record<string, "error" | "off"> =>
  Object.fromEntries(rules.map((rule) => [rule, level]));

const config: OxlintConfig = {
  plugins: ["eslint", "typescript"],
  categories: { correctness: "off" },
  env: { builtin: true },
  options: { typeAware: true, denyWarnings: true, reportUnusedDisableDirectives: "error" },
  rules: turn([...CORE, ...TYPESCRIPT], "error"),
  overrides: [
    {
      files: ["**/*.{js,cjs,mjs}"],
      env: { node: true },
      rules: { ...turn(JAVASCRIPT_ONLY, "error"), ...turn(TYPESCRIPT, "off") },
    },
  ],
};

export default config;
