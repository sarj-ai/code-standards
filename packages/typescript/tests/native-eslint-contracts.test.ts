import type { ESLintUtils, JSONSchema } from "@typescript-eslint/utils";
import { Linter } from "eslint";
import { expect, it } from "vitest";

import { createRule, type RuleDocumentation } from "../src/rules/_docs.js";
import { createNativeRule, type NativeRuleContext } from "../src/rules/_eslint-rule.js";

type Options = readonly [{ readonly enabled: boolean }];

function ruleUrl(name: string): string {
  return `https://example.invalid/rules/${name}`;
}

function metadata(): ESLintUtils.RuleWithMetaAndName<Options, "probe">["meta"] {
  return {
    type: "problem",
    docs: { description: "Check native rule contracts" },
    schema: [{ type: "object", properties: { enabled: { type: "boolean" } } }],
    messages: { probe: "Probe." },
  };
}

it("normalizes legacy defaults while exposing partial host options", () => {
  const defaults: Options = [{ enabled: false }];
  let raw: boolean | undefined;
  let normalized: boolean | undefined;
  const rule = createNativeRule<Options, "probe">({
    name: "legacy-defaults",
    meta: metadata(),
    defaultOptions: defaults,
    create(this: void, context, [options]) {
      expect(this).toBeUndefined();
      raw = context.options[0]?.enabled;
      normalized = options.enabled;
      return {};
    },
  }, ruleUrl);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(raw).toBeUndefined();
  expect(normalized).toBe(false);
  expect(rule.defaultOptions).toBe(defaults);
  expect(Object.hasOwn(rule.meta, "defaultOptions")).toBe(false);
});

it("owns outer metadata arrays while retaining nested default and schema aliases", () => {
  const nested = { enabled: false };
  const defaults: [{ enabled: boolean }] = [nested];
  const schema: JSONSchema.JSONSchema4[] = [{ type: "object" }];
  const observed: boolean[] = [];
  const rule = createNativeRule<Options, "probe">({
    name: "owned-defaults",
    meta: { ...metadata(), schema, defaultOptions: defaults },
    create(_context, [options]) { observed.push(options.enabled); return {}; },
  }, ruleUrl);
  expect(rule.meta.defaultOptions).not.toBe(defaults);
  expect(rule.meta.defaultOptions?.[0]).toBe(nested);
  expect(rule.meta.schema).not.toBe(schema);
  expect(Array.isArray(rule.meta.schema) && rule.meta.schema[0]).toBe(schema[0]);
  defaults[0] = { enabled: true };
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(observed).toEqual([false]);
});

it("keeps missing and JavaScript explicit-undefined metadata distinct", () => {
  const absentMeta = { type: "problem", docs: { description: "Absent" }, schema: [], messages: { probe: "Probe." } } satisfies ESLintUtils.RuleWithMetaAndName<readonly [], "probe">["meta"];
  const undefinedMeta = { ...absentMeta };
  Object.defineProperty(undefinedMeta, "defaultOptions", { value: undefined, enumerable: true });
  const absent = createNativeRule<readonly [], "probe">({
    name: "absent", meta: absentMeta, create() { return {}; },
  }, ruleUrl);
  const explicit = createNativeRule<readonly [], "probe">({
    name: "explicit", meta: undefinedMeta, create() { return {}; },
  }, ruleUrl);
  expect(Object.hasOwn(absent.meta, "defaultOptions")).toBe(false);
  expect(Object.hasOwn(explicit.meta, "defaultOptions")).toBe(true);
  expect(explicit.meta.defaultOptions).toBeUndefined();
});

it("snapshots own descriptor and default getters once", () => {
  let metadataReads = 0, defaultReads = 0;
  const defaults: Options = [{ enabled: false }];
  const values = { ...metadata(), get defaultOptions() { defaultReads += 1; return defaults; } };
  const rule = createNativeRule<Options, "probe">({
    name: "getter-defaults",
    get meta() { metadataReads += 1; return values; },
    create(_context, [options]) { expect(options.enabled).toBe(false); return {}; },
  }, ruleUrl);
  expect(metadataReads).toBe(1);
  expect(defaultReads).toBe(1);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
});

it("honors required metadata defaults declared by a prototype getter", () => {
  let observed: boolean | undefined;
  class Metadata {
    readonly type = "problem";
    readonly docs = { description: "Prototype metadata" };
    readonly schema: JSONSchema.JSONSchema4[] = [{ type: "object" }];
    readonly messages = { probe: "Probe." };
    get defaultOptions(): Options { return [{ enabled: false }]; }
  }
  const rule = createNativeRule<Options, "probe">({
    name: "inherited-metadata", meta: new Metadata(),
    create(_context, [options]) { observed = options.enabled; return {}; },
  }, ruleUrl);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(observed).toBe(false);
  expect(rule.meta.defaultOptions).toEqual([{ enabled: false }]);
});

it("honors required legacy defaults and create methods on a descriptor prototype", () => {
  let observed: boolean | undefined;
  class Definition {
    readonly name = "inherited-legacy";
    readonly meta = metadata();
    get defaultOptions(): Options { return [{ enabled: false }]; }
    create(this: void, _context: NativeRuleContext<"probe", Options>, [options]: Options) {
      observed = options.enabled;
      return {};
    }
  }
  const rule = createNativeRule<Options, "probe">(new Definition(), ruleUrl);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(observed).toBe(false);
});

it("honors non-enumerable metadata and legacy default tuples", () => {
  const observed: boolean[] = [];
  const defaults: Options = [{ enabled: false }];
  const values = { ...metadata(), defaultOptions: defaults };
  Object.defineProperty(values, "defaultOptions", { enumerable: false });
  const metadataRule = createNativeRule<Options, "probe">({
    name: "hidden-metadata", meta: values,
    create(_context, [options]) { observed.push(options.enabled); return {}; },
  }, ruleUrl);
  const definition = {
    name: "hidden-legacy", meta: metadata(), defaultOptions: defaults,
    create(_context: NativeRuleContext<"probe", Options>, [options]: Options) { observed.push(options.enabled); return {}; },
  };
  Object.defineProperty(definition, "defaultOptions", { enumerable: false });
  const legacyRule = createNativeRule<Options, "probe">(definition, ruleUrl);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { metadataRule, legacyRule } } },
    rules: { "probe/metadataRule": "error", "probe/legacyRule": "error" },
  })).toEqual([]);
  expect(observed).toEqual([false, false]);
});

it("documented wrapper reads its documentation getter once", () => {
  let documentationReads = 0;
  const summary = "Snapshot documented native rule configuration";
  const documentation = {
    summary,
    rationale: "Documentation getters may have observable behavior.",
    remediation: "Read the authored documentation once and retain native rule metadata.",
    category: "maintainability",
  } as const satisfies RuleDocumentation<readonly []>;
  const defaults: readonly [] = [];
  const schema: JSONSchema.JSONSchema4[] = [];
  const rule = createRule<readonly [], "probe">({
    name: "documented-getter",
    get documentation() {
      documentationReads += 1;
      if (documentationReads !== 1) throw new Error("The authored documentation getter was evaluated more than once.");
      return documentation;
    },
    meta: { type: "problem", docs: { description: summary }, schema, messages: { probe: "Probe." } },
    defaultOptions: defaults,
    create() { return {}; },
  });
  expect(documentationReads).toBe(1);
  expect(rule.documentation?.summary).toBe(summary);
  expect(Object.keys(rule)).not.toContain("documentation");
  expect(Object.getOwnPropertyDescriptor(rule, "documentation")).toMatchObject({ enumerable: false, configurable: false, writable: false });
  expect(rule.defaultOptions).toBe(defaults);
  expect(rule.meta.schema).not.toBe(schema);
  expect(Object.hasOwn(rule.meta, "defaultOptions")).toBe(false);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(documentationReads).toBe(1);
});

it("documented wrapper snapshots inherited private-brand getters and retains metadata default priority", () => {
  let documentationReads = 0, nameReads = 0, metadataReads = 0, defaultReads = 0;
  const summary = "Retain native prototype contracts through documented rules";
  const documentation = {
    summary,
    rationale: "Native descriptors can expose fields through prototype getters.",
    remediation: "Snapshot native fields from their original receiver once.",
    category: "maintainability",
  } as const satisfies RuleDocumentation<Options>;
  const legacyDefaults: Options = [{ enabled: false }];
  const metadataDefaults: [{ enabled: boolean }] = [{ enabled: true }];
  const schema: JSONSchema.JSONSchema4[] = [{ type: "object", properties: { enabled: { type: "boolean" } } }];
  const observed: boolean[] = [];
  class Definition {
    readonly #name = "documented-prototype";
    readonly #documentation = documentation;
    readonly #metadata = { ...metadata(), docs: { description: summary }, schema, defaultOptions: metadataDefaults };
    readonly #defaults = legacyDefaults;
    get name(): string { nameReads += 1; return this.#name; }
    get documentation(): RuleDocumentation<Options> { documentationReads += 1; return this.#documentation; }
    get meta(): ESLintUtils.RuleWithMetaAndName<Options, "probe">["meta"] { metadataReads += 1; return this.#metadata; }
    get defaultOptions(): Options { defaultReads += 1; return this.#defaults; }
    create(this: void, _context: NativeRuleContext<"probe", Options>, [options]: Options) {
      observed.push(options.enabled);
      return {};
    }
  }
  const rule = createRule<Options, "probe">(new Definition());
  expect([documentationReads, nameReads, metadataReads, defaultReads]).toEqual([1, 1, 1, 1]);
  expect(rule.documentation?.summary).toBe(summary);
  expect(rule.defaultOptions).toBe(legacyDefaults);
  expect(rule.meta.defaultOptions).not.toBe(metadataDefaults);
  expect(rule.meta.defaultOptions?.[0]).toBe(metadataDefaults[0]);
  expect(rule.meta.schema).not.toBe(schema);
  expect(Array.isArray(rule.meta.schema) && rule.meta.schema[0]).toBe(schema[0]);
  metadataDefaults[0] = { enabled: false };
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(observed).toEqual([true]);
  expect([documentationReads, nameReads, metadataReads, defaultReads]).toEqual([1, 1, 1, 1]);
});

it("documented wrapper retains non-enumerable native descriptor fields", () => {
  let documentationReads = 0;
  const summary = "Retain non-enumerable native rule fields";
  const documentation = {
    summary,
    rationale: "Enumerability does not determine native descriptor ownership.",
    remediation: "Read declared native fields directly and attach documentation separately.",
    category: "maintainability",
  } as const satisfies RuleDocumentation<Options>;
  const defaults: Options = [{ enabled: false }];
  const schema: JSONSchema.JSONSchema4[] = [{ type: "object", properties: { enabled: { type: "boolean" } } }];
  const observed: boolean[] = [];
  const definition = {
    name: "documented-non-enumerable",
    get documentation() {
      documentationReads += 1;
      if (documentationReads !== 1) throw new Error("Non-enumerable documentation was evaluated more than once.");
      return documentation;
    },
    meta: { ...metadata(), docs: { description: summary }, schema },
    defaultOptions: defaults,
    create(_context: NativeRuleContext<"probe", Options>, [options]: Options) { observed.push(options.enabled); return {}; },
  };
  for (const key of ["name", "documentation", "meta", "defaultOptions", "create"] as const) {
    Object.defineProperty(definition, key, { enumerable: false });
  }
  const rule = createRule<Options, "probe">(definition);
  expect(rule.name).toBe("documented-non-enumerable");
  expect(rule.documentation?.summary).toBe(summary);
  expect(Object.getOwnPropertyDescriptor(rule, "documentation")).toMatchObject({ enumerable: false, configurable: false, writable: false });
  expect(rule.defaultOptions).toBe(defaults);
  expect(Object.hasOwn(rule.meta, "defaultOptions")).toBe(false);
  expect(rule.meta.schema).not.toBe(schema);
  expect(Array.isArray(rule.meta.schema) && rule.meta.schema[0]).toBe(schema[0]);
  expect(new Linter().verify("const value = 1;", {
    plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
  })).toEqual([]);
  expect(observed).toEqual([false]);
  expect(documentationReads).toBe(1);
});
