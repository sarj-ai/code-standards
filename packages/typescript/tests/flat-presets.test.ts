// vitest: shared-module-graph
















import { ESLint, Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin, {
  ADVISORY_RULES,
  APPLICATION_ONLY_RULES,
  RECOMMENDED_RULES,
  RULES,
  STRICT_RULES,
  advisoryRules,
  recommendedRules,
  rules,
  strictRules,
} from "../src/index.js";
import { LIBRARY_POLICY } from "../src/library-policy.js";
import { rulesOf, warningStageEslintRules } from "./_config.js";

const PRESETS = ["recommended", "strict"] as const;
const PREVIOUS_STRICT_RULE_ORDER = [
  "@sarj/no-discarded-validation-result",
  "@sarj/no-generic-json-parser",
  "@sarj/no-mutating-container-transform",
  "@sarj/no-mutating-input-with-result",
  "@sarj/no-negative-only-http-status-assertion",
  "@sarj/no-redundant-local-alias",
  "@sarj/no-return-disposed-resource",
  "@sarj/no-test-comments",
  "@sarj/prefer-dependency-interface",
  "@sarj/prefer-test-fixture-reuse",
  "@sarj/production-derived-test-cases",
  "@sarj/require-constrained-schema-integer",
  "@sarj/require-jwt-lifetime",
  "@sarj/no-excess-jsx-props",
  "@sarj/no-redundant-consumer-union",
  "@sarj/prefer-minimal-parameter-contract",
  "@sarj/named-child-schema-type",
  "@sarj/no-conditional-empty-object-spread",
  "@sarj/prefer-typed-reflection",
  "@sarj/no-broad-return-type",
  "@sarj/no-reduce-accumulator-copy",
  "@sarj/no-known-value-widening",
  "@sarj/no-invalid-typed-mutation",
  "@sarj/no-contradictory-type-predicate",
  "@sarj/no-partial-type-predicate",
  "@sarj/no-boolean-selector-parameter",
  "@sarj/no-invalid-zod-custom-parse",
  "@sarj/no-contradictory-overload-return",
  "@sarj/require-button-accessible-name",
  "@sarj/require-camelcase-properties",
  "@sarj/require-svg-accessible-name",
  "@sarj/prefer-logical-tailwind-utilities",
  "@sarj/no-unlocalized-toast",
  "@sarj/no-unlocalized-jsx-attributes",
  "@sarj/no-unlocalized-jsx-text",
  "no-restricted-imports",
  "@sarj/no-restricted-library-load",
  "@sarj/prefer-native-random-uuid",
  "@sarj/prefer-shadcn-primitives",
  "@sarj/excessive-commentary",
  "@sarj/no-excessive-cognitive-complexity",
  "@sarj/interface-contract-members-private",
  "@sarj/iac-source-coupled-test",
  "@sarj/duplicate-test-body",
  "@sarj/enforce-file-structure",
  "@sarj/no-client-side-data-fetching",
  "@sarj/no-comment-cruft",
  "@sarj/no-cors-wildcard-with-credentials",
  "@sarj/no-dynamic-sql",
  "@sarj/no-enum",
  "@sarj/no-fat-try-blocks",
  "@sarj/no-hand-rolled-sleep",
  "@sarj/no-hand-rolled-spinner",
  "@sarj/no-insecure-random-id",
  "@sarj/no-exception-text-in-5xx-response",
  "@sarj/no-json-stringify-error",
  "@sarj/no-impossible-zod-literal-bounds",
  "@sarj/no-in-operator-on-built-in-collections",
  "@sarj/no-log-only-catch",
  "@sarj/no-bare-return-from-test-catch",
  "@sarj/no-bespoke-api-case-conversion",
  "@sarj/no-detached-global-fetch",
  "@sarj/no-json-stringify-object-equality",
  "@sarj/no-dangerously-allow-svg",
  "@sarj/no-credential-in-browser-storage",
  "@sarj/no-numeric-search-param-coercion",
  "@sarj/prefer-native-fetch-in-server-actions",
  "@sarj/no-duplicate-lifecycle-refresh-listeners",
  "@sarj/no-long-comment",
  "@sarj/no-vague-suppression-description",
  "@sarj/no-generic-single-export-module",
  "@sarj/no-offset-pagination",
  "@sarj/no-positional-tuple-return",
  "@sarj/no-production-browser-source-maps",
  "@sarj/no-raw-env",
  "@sarj/no-raw-fetch-outside-clients",
  "@sarj/no-repeated-string-literal",
  "@sarj/no-redundant-optional-array-default",
  "@sarj/no-router-refresh-polling",
  "@sarj/no-restated-comment",
  "@sarj/no-restated-jsdoc",
  "@sarj/no-secret-in-log",
  "@sarj/no-server-env-in-client-component",
  "@sarj/no-server-file-uploads",
  "@sarj/no-select-star",
  "@sarj/no-sentinel-return-on-catch",
  "@sarj/no-silent-promise-catch",
  "@sarj/no-sleep-in-test-body",
  "@sarj/no-storage-in-stateless-modules",
  "@sarj/no-string-concat-in-loop",
  "@sarj/no-tautological-expect",
  "@sarj/no-duplicate-test-case",
  "@sarj/no-typed-doc-sections",
  "@sarj/no-trailing-value-narration",
  "@sarj/no-declaration-comment-wall",
  "@sarj/no-union-in-comment",
  "@sarj/no-type-member-comment-wall",
  "@sarj/no-unnecessary-use-client",
  "@sarj/no-unsafe-mock-casting",
  "@sarj/no-unsafe-test-double-cast",
  "@sarj/no-first-party-module-mock",
  "@sarj/no-zod-native-enum",
  "@sarj/test-loops-over-literal-cases",
  "@sarj/prefer-constant-time-secret-compare",
  "@sarj/prefer-ecmascript-private-members",
  "@sarj/prefer-discriminated-union",
  "@sarj/prefer-input-group-search",
  "@sarj/prefer-millisecond-control-duration-schema",
  "@sarj/prefer-immutable-module-constant",
  "@sarj/prefer-module-level-constant",
  "@sarj/prefer-module-level-schema",
  "@sarj/prefer-module-level-refined-schema",
  "@sarj/prefer-multi-value-zod-literal",
  "@sarj/prefer-named-callback-domain",
  "@sarj/prefer-nominal-id-types",
  "@sarj/prefer-named-complex-return-type",
  "@sarj/prefer-node-crypto-hash",
  "@sarj/prefer-node-fs-promises",
  "@sarj/prefer-non-nullable-collection",
  "@sarj/prefer-nullish-filter-predicate",
  "@sarj/prefer-await-in-async-return",
  "@sarj/prefer-schema-for-api-payload",
  "@sarj/prefer-shared-zod-enum",
  "@sarj/prefer-switch-for-repeated-equality",
  "@sarj/prefer-semantic-colors",
  "@sarj/prefer-server-actions",
  "@sarj/prefer-whole-object-assertion",
  "@sarj/repeated-static-call-cases",
  "@sarj/prefer-zod-infer",
  "@sarj/prefer-zod-parse-output-type",
  "@sarj/require-assert-never",
  "@sarj/require-fetch-timeout",
  "@sarj/require-explicit-contract-implementation",
  "@sarj/require-explicit-service-contract",
  "@sarj/require-interface-for-exported-class",
  "@sarj/require-port-for-service",
  "@sarj/require-sql-access-class",
  "@sarj/require-static-next-matcher",
  "@sarj/require-use-form-default-values",
  "@sarj/require-use-server-in-actions-file",
  "@sarj/require-zod-form-validation",
  "@sarj/store-insert-requires-on-conflict",
  "@sarj/stepdown",
  "@sarj/source-coupled-test",
  "@sarj/sole-export-matches-filename",
  "@sarj/test-phase-label-comment",
  "@sarj/require-pascal-case-zod-schema-name",
] as const;
const PREVIOUS_RECOMMENDED_RULE_ORDER = [
  "@sarj/no-excess-jsx-props",
  "@sarj/no-redundant-consumer-union",
  "@sarj/prefer-minimal-parameter-contract",
  "@sarj/named-child-schema-type",
  "@sarj/no-conditional-empty-object-spread",
  "@sarj/prefer-typed-reflection",
  "@sarj/no-broad-return-type",
  "@sarj/no-reduce-accumulator-copy",
  "@sarj/no-known-value-widening",
  "@sarj/no-invalid-typed-mutation",
  "@sarj/no-contradictory-type-predicate",
  "@sarj/no-partial-type-predicate",
  "@sarj/no-boolean-selector-parameter",
  "@sarj/no-invalid-zod-custom-parse",
  "@sarj/no-contradictory-overload-return",
  "@sarj/require-button-accessible-name",
  "@sarj/require-camelcase-properties",
  "@sarj/require-svg-accessible-name",
  "@sarj/prefer-logical-tailwind-utilities",
  "@sarj/no-unlocalized-toast",
  "@sarj/no-unlocalized-jsx-attributes",
  "@sarj/no-unlocalized-jsx-text",
  "no-restricted-imports",
  "@sarj/no-restricted-library-load",
  "@sarj/no-redundant-local-alias",
  "@sarj/prefer-test-fixture-reuse",
  "@sarj/no-negative-only-http-status-assertion",
  "@sarj/no-mutating-input-with-result",
  "@sarj/no-return-disposed-resource",
  "@sarj/no-discarded-validation-result",
  "@sarj/require-jwt-lifetime",
  "@sarj/prefer-dependency-interface",
  "@sarj/no-generic-json-parser",
  "@sarj/require-constrained-schema-integer",
  "@sarj/production-derived-test-cases",
  "@sarj/no-test-comments",
  "@sarj/no-mutating-container-transform",
  "@sarj/prefer-native-random-uuid",
  "@sarj/prefer-shadcn-primitives",
  "@sarj/excessive-commentary",
  "@sarj/no-excessive-cognitive-complexity",
  "@sarj/interface-contract-members-private",
  "@sarj/iac-source-coupled-test",
  "@sarj/duplicate-test-body",
  "@sarj/enforce-file-structure",
  "@sarj/no-client-side-data-fetching",
  "@sarj/no-comment-cruft",
  "@sarj/no-cors-wildcard-with-credentials",
  "@sarj/no-dynamic-sql",
  "@sarj/no-fat-try-blocks",
  "@sarj/no-hand-rolled-sleep",
  "@sarj/no-hand-rolled-spinner",
  "@sarj/no-insecure-random-id",
  "@sarj/no-exception-text-in-5xx-response",
  "@sarj/no-json-stringify-error",
  "@sarj/no-impossible-zod-literal-bounds",
  "@sarj/no-in-operator-on-built-in-collections",
  "@sarj/no-log-only-catch",
  "@sarj/no-bare-return-from-test-catch",
  "@sarj/no-bespoke-api-case-conversion",
  "@sarj/no-detached-global-fetch",
  "@sarj/no-json-stringify-object-equality",
  "@sarj/no-dangerously-allow-svg",
  "@sarj/no-credential-in-browser-storage",
  "@sarj/no-numeric-search-param-coercion",
  "@sarj/prefer-native-fetch-in-server-actions",
  "@sarj/no-duplicate-lifecycle-refresh-listeners",
  "@sarj/no-long-comment",
  "@sarj/no-vague-suppression-description",
  "@sarj/no-generic-single-export-module",
  "@sarj/no-offset-pagination",
  "@sarj/no-positional-tuple-return",
  "@sarj/no-production-browser-source-maps",
  "@sarj/no-repeated-string-literal",
  "@sarj/no-redundant-optional-array-default",
  "@sarj/no-router-refresh-polling",
  "@sarj/no-restated-comment",
  "@sarj/no-restated-jsdoc",
  "@sarj/no-secret-in-log",
  "@sarj/no-server-env-in-client-component",
  "@sarj/no-server-file-uploads",
  "@sarj/no-select-star",
  "@sarj/no-sentinel-return-on-catch",
  "@sarj/no-silent-promise-catch",
  "@sarj/no-sleep-in-test-body",
  "@sarj/no-string-concat-in-loop",
  "@sarj/no-tautological-expect",
  "@sarj/no-duplicate-test-case",
  "@sarj/no-typed-doc-sections",
  "@sarj/no-trailing-value-narration",
  "@sarj/no-declaration-comment-wall",
  "@sarj/no-union-in-comment",
  "@sarj/no-type-member-comment-wall",
  "@sarj/no-unnecessary-use-client",
  "@sarj/no-unsafe-mock-casting",
  "@sarj/no-unsafe-test-double-cast",
  "@sarj/no-first-party-module-mock",
  "@sarj/no-zod-native-enum",
  "@sarj/test-loops-over-literal-cases",
  "@sarj/prefer-constant-time-secret-compare",
  "@sarj/prefer-ecmascript-private-members",
  "@sarj/prefer-discriminated-union",
  "@sarj/prefer-input-group-search",
  "@sarj/prefer-millisecond-control-duration-schema",
  "@sarj/prefer-immutable-module-constant",
  "@sarj/prefer-module-level-constant",
  "@sarj/prefer-module-level-schema",
  "@sarj/prefer-module-level-refined-schema",
  "@sarj/prefer-multi-value-zod-literal",
  "@sarj/prefer-named-callback-domain",
  "@sarj/prefer-nominal-id-types",
  "@sarj/prefer-named-complex-return-type",
  "@sarj/prefer-node-crypto-hash",
  "@sarj/prefer-node-fs-promises",
  "@sarj/prefer-non-nullable-collection",
  "@sarj/prefer-nullish-filter-predicate",
  "@sarj/prefer-await-in-async-return",
  "@sarj/prefer-schema-for-api-payload",
  "@sarj/prefer-shared-zod-enum",
  "@sarj/prefer-switch-for-repeated-equality",
  "@sarj/prefer-semantic-colors",
  "@sarj/prefer-server-actions",
  "@sarj/prefer-whole-object-assertion",
  "@sarj/repeated-static-call-cases",
  "@sarj/prefer-zod-infer",
  "@sarj/prefer-zod-parse-output-type",
  "@sarj/require-assert-never",
  "@sarj/require-fetch-timeout",
  "@sarj/require-explicit-contract-implementation",
  "@sarj/require-explicit-service-contract",
  "@sarj/require-interface-for-exported-class",
  "@sarj/require-port-for-service",
  "@sarj/require-sql-access-class",
  "@sarj/require-static-next-matcher",
  "@sarj/require-use-form-default-values",
  "@sarj/require-use-server-in-actions-file",
  "@sarj/require-zod-form-validation",
  "@sarj/store-insert-requires-on-conflict",
  "@sarj/stepdown",
  "@sarj/source-coupled-test",
  "@sarj/sole-export-matches-filename",
  "@sarj/test-phase-label-comment",
  "@sarj/require-pascal-case-zod-schema-name",
] as const;
const PREVIOUS_OPTION_SETTINGS = {
  "@sarj/prefer-logical-tailwind-utilities": { enabled: false },
  "@sarj/no-unlocalized-toast": { enabled: false },
  "@sarj/no-unlocalized-jsx-attributes": { enabled: false },
  "@sarj/no-unlocalized-jsx-text": { enabled: false },
  "@sarj/no-restricted-library-load": { libraries: LIBRARY_POLICY },
  "@sarj/no-fat-try-blocks": { max: 5 },
  "@sarj/prefer-multi-value-zod-literal": { zodMajorVersion: 4 },
  "@sarj/prefer-semantic-colors": { requireSemanticTokens: true },
} as const;

it("keeps every preset value and the previous public key order", () => {
  expect(Object.keys(STRICT_RULES)).toEqual(PREVIOUS_STRICT_RULE_ORDER);
  expect(Object.keys(RECOMMENDED_RULES)).toEqual(
    PREVIOUS_RECOMMENDED_RULE_ORDER,
  );
  const warningNames = new Set(warningStageEslintRules());
  for (const [name, setting] of Object.entries(STRICT_RULES)) {
    if (name === "no-restricted-imports" || Object.hasOwn(PREVIOUS_OPTION_SETTINGS, name)) continue;
    expect(setting).toBe(warningNames.has(name) ? "warn" : "error");
  }
  for (const name of Object.keys(PREVIOUS_OPTION_SETTINGS)) {
    if (!isConfiguredRuleName(name)) throw new Error("Unknown baseline configured rule.");
    expect(RECOMMENDED_RULES[name]).toEqual(["error", PREVIOUS_OPTION_SETTINGS[name]]);
    expect(STRICT_RULES[name]).toEqual(["error", PREVIOUS_OPTION_SETTINGS[name]]);
  }
});

it("retains independent option tuples and intentionally shared library data", () => {
  for (const name of Object.keys(PREVIOUS_OPTION_SETTINGS)) {
    if (!isConfiguredRuleName(name)) throw new Error("Unknown baseline configured rule.");
    expect(RECOMMENDED_RULES[name]).not.toBe(STRICT_RULES[name]);
    expect(RECOMMENDED_RULES[name][1]).not.toBe(STRICT_RULES[name][1]);
  }
  expect(RECOMMENDED_RULES["@sarj/no-restricted-library-load"][1].libraries).toBe(LIBRARY_POLICY);
  expect(STRICT_RULES["@sarj/no-restricted-library-load"][1].libraries).toBe(LIBRARY_POLICY);
  expect(RECOMMENDED_RULES["no-restricted-imports"]).toBe(STRICT_RULES["no-restricted-imports"]);
  expect(RECOMMENDED_RULES["no-restricted-imports"][1].paths)
    .toBe(STRICT_RULES["no-restricted-imports"][1].paths);
  expect(RECOMMENDED_RULES["no-restricted-imports"][1].patterns)
    .toBe(STRICT_RULES["no-restricted-imports"][1].patterns);
});

function isConfiguredRuleName(name: string): name is keyof typeof PREVIOUS_OPTION_SETTINGS {
  return Object.hasOwn(PREVIOUS_OPTION_SETTINGS, name);
}

it("retains export aliases and configuration getter object lifetimes", () => {
  expect(plugin.rules).toBe(RULES);
  expect(rules).toBe(RULES);
  expect(advisoryRules).toBe(ADVISORY_RULES);
  expect(recommendedRules).toBe(RECOMMENDED_RULES);
  expect(strictRules).toBe(STRICT_RULES);
  const first = plugin.configs;
  const second = plugin.configs;
  expect(first).not.toBe(second);
  for (const preset of PRESETS) {
    expect(first[preset]).not.toBe(second[preset]);
    expect(first[preset].plugins).not.toBe(second[preset].plugins);
    expect(first[preset].plugins["@sarj"]).toBe(plugin);
    expect(first[preset].rules).toBe(second[preset].rules);
  }
  expect(first.recommended.rules).toBe(RECOMMENDED_RULES);
  expect(first.strict.rules).toBe(STRICT_RULES);
});

describe("configs.recommended / configs.strict are flat config", () => {
  it.each(PRESETS)("%s loads through ESLint without throwing", async (name) => {
    const eslint = new ESLint({
      overrideConfigFile: true,
      overrideConfig: [
        { files: ["**/*.ts"] },
        plugin.configs[name],
      ] as Linter.Config[],
    });
    const resolved: unknown = await eslint.calculateConfigForFile("src/index.ts");
    const configured = Object.keys(rulesOf(resolved));


    expect(configured.length).toBeGreaterThan(40);
    expect(configured.every((rule) => rule.startsWith("@sarj/") || rule === "no-restricted-imports")).toBe(true);
  });

  it.each(PRESETS)("%s declares plugins as an object, not an array", (name) => {
    const preset = plugin.configs[name];
    expect(Array.isArray(preset.plugins)).toBe(false);
    expect(Object.keys(preset.plugins)).toEqual(["@sarj"]);
  });

  it.each(PRESETS)("%s carries rules and nothing that fights a host config", (name) => {



    expect(Object.keys(plugin.configs[name]).sort()).toEqual([
      "name",
      "plugins",
      "rules",
    ]);
  });

  it("strict wires every rule the plugin ships", () => {










    const known = Object.entries(plugin.rules)
      .filter(([, rule]) => rule.meta.deprecated === undefined)
      .map(([rule]) => `@sarj/${rule}`);
    const missing = known.filter((rule) => !(rule in STRICT_RULES));
    expect(missing).toEqual([]);

    const wiredAliases = Object.entries(plugin.rules)
      .filter(([, rule]) => rule.meta.deprecated !== undefined)
      .map(([rule]) => `@sarj/${rule}`)
      .filter((rule) => rule in STRICT_RULES);
    expect(wiredAliases).toEqual([]);
  });

  it("keeps legacy profile metadata empty and library policy effective", () => {
    expect(APPLICATION_ONLY_RULES).toEqual([]);
    expect(STRICT_RULES["@sarj/no-restricted-library-load"][1].libraries.length).toBeGreaterThan(0);
  });

  it.each([
    ["import client from 'axios';", "no-restricted-imports"],
    ["const client = import('axios');", "@sarj/no-restricted-library-load"],
    ["const client = require('axios/lib/client');", "@sarj/no-restricted-library-load"],
    ["import upload from 'multer';", "no-restricted-imports"],
    ["export { default } from 'multer/storage/memory';", "no-restricted-imports"],
    ["const upload = import('formidable');", "@sarj/no-restricted-library-load"],
    ["const upload = require('busboy');", "@sarj/no-restricted-library-load"],
    ["import upload from '@fastify/multipart';", "no-restricted-imports"],
    ["const upload = require('express-fileupload');", "@sarj/no-restricted-library-load"],
    ["const upload = import('multiparty');", "@sarj/no-restricted-library-load"],
    ["import storage from '@aws-sdk/lib-storage';", null],
    ["import outbound from 'form-data';", null],
    ["const form = new FormData(); form.set('title', 'Document');", null],
    ["const file = new File(['content'], 'document.txt');", null],
    ["import client from 'ky';", null],
  ])("enforces the native library policy for %s", (source, expected) => {
    const messages = new Linter().verify(source, {
      plugins: { "@sarj": plugin },
      rules: {
        "no-restricted-imports": STRICT_RULES["no-restricted-imports"],
        "@sarj/no-restricted-library-load": STRICT_RULES["@sarj/no-restricted-library-load"],
      },
    });
    expect(messages.map(message => message.ruleId)).toEqual(expected === null ? [] : [expected]);
  });

  it("recommended is a subset of strict, never the other way round", () => {
    const extra = Object.keys(RECOMMENDED_RULES).filter(
      (rule) => !(rule in STRICT_RULES),
    );
    expect(extra).toEqual([]);
  });

  it("keeps managed fetch error strict-only without expanding recommended activation", () => {
    expect(RECOMMENDED_RULES).not.toHaveProperty("@sarj/no-raw-fetch-outside-clients");
    expect(STRICT_RULES["@sarj/no-raw-fetch-outside-clients"]).toBe("error");
  });

  it.each([
    "@sarj/no-trailing-value-narration",
    "@sarj/no-type-member-comment-wall",
    "@sarj/no-positional-tuple-return",
    "@sarj/no-sentinel-return-on-catch",
    "@sarj/no-string-concat-in-loop",
    "@sarj/duplicate-test-body",
    "@sarj/no-log-only-catch",
    "@sarj/prefer-non-nullable-collection",
    "@sarj/repeated-static-call-cases",
    "@sarj/test-loops-over-literal-cases",
    "@sarj/no-offset-pagination",
    "@sarj/no-silent-promise-catch",
    "@sarj/prefer-immutable-module-constant",
    "@sarj/prefer-module-level-constant",
    "@sarj/prefer-module-level-schema",
    "@sarj/stepdown",
    "@sarj/prefer-schema-for-api-payload",
    "@sarj/require-zod-form-validation",
    "@sarj/no-typed-doc-sections",
    "@sarj/no-union-in-comment",
  ])("preserves error enforcement for %s", (rule) => {
    expect(RECOMMENDED_RULES[rule]).toBe("error");
    expect(STRICT_RULES[rule]).toBe("error");
  });

  it("strict is at least as strict as recommended, rule for rule", () => {
    const severityOf = (value: unknown): unknown =>
      Array.isArray(value) ? value[0] : value;
    const weaker = Object.entries(RECOMMENDED_RULES)
      .filter(([rule, recommended]) => {
        const strict = (STRICT_RULES as Record<string, unknown>)[rule];
        return severityOf(recommended) === "error" && severityOf(strict) !== "error";
      })
      .map(([rule]) => rule);
    expect(weaker).toEqual([]);
  });

  it.each(PRESETS)("%s treats only calibrated advisory rules as warnings", (name) => {
    const entries = Object.entries(plugin.configs[name].rules);
    const nonErrors = entries
      .filter(([, setting]) => {
        const severity = Array.isArray(setting)
          ? (setting as readonly unknown[])[0]
          : setting;
        return severity !== "error";
      })
      .map(([rule]) => rule);
    expect(ADVISORY_RULES).toEqual(warningStageEslintRules());
    expect(nonErrors.toSorted()).toEqual([...ADVISORY_RULES]);
  });

  it.each(PRESETS)("%s makes a sole-export filename mismatch blocking", (name) => {
    const messages = new Linter().verify("export function parseOrder() {}", {
      plugins: { "@sarj": plugin },
      rules: {
        "@sarj/sole-export-matches-filename": plugin.configs[name].rules["@sarj/sole-export-matches-filename"],
      },
    }, "src/orders.js");
    expect(messages).toEqual([
      expect.objectContaining({ ruleId: "@sarj/sole-export-matches-filename", severity: 2 }),
    ]);
  });
});
