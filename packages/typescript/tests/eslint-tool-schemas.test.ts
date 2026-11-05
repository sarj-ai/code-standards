import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import { describe, expect, it } from "vitest";

import {
  CallableSchema,
  DeclaredRequirementSchema,
  FileExecutionsSchema,
  RuleExecutionStateSchema,
  SelectedRequestSchema,
  SuppressionsSchema,
} from "../../standards/src/sarj_standards/configs/eslint-tool-schemas.mts";
import { record, strings } from "../../standards/src/sarj_standards/configs/tool-json.mts";

const ROW = { ruleId: "@sarj/probe", filePath: "input.ts", execution: "ran", requiresTypeInformation: false };

describe("declarative execution protocol", () => {
  it.each([undefined, "true", 0, {}, []])("treats undeclared native requirements as unknown: %j", (value) => {
    expect(DeclaredRequirementSchema.parse(value)).toBe(null);
  });
  it.each(["ran", "skipped", "untracked", "failed", "disabled", "ignored"])("accepts execution state %s", (value) => {
    expect(RuleExecutionStateSchema.parse(value)).toBe(value);
  });
  it.each(["", "RAN", "other", null, undefined, 0, true, {}, []])("rejects values outside the state enum: %j", (value) => {
    expect(RuleExecutionStateSchema.safeParse(value).success).toBe(false);
  });
  it("normalizes paths, projects fields, and omits an absent reason", () => {
    expect(FileExecutionsSchema.parse([{ ...ROW, privateField: "hidden" }])).toEqual([{ ...ROW, filePath: resolve("input.ts") }]);
    expect(FileExecutionsSchema.parse([{ ...ROW, reason: undefined }])[0]).not.toHaveProperty("reason");
  });
  it.each([true, false, null])("accepts the tri-state type-information contract: %j", (requiresTypeInformation) => {
    expect(FileExecutionsSchema.parse([{ ...ROW, requiresTypeInformation, reason: "missing-type-information" }])[0]).toMatchObject({ requiresTypeInformation, reason: "missing-type-information" });
  });
  it.each([
    { ...ROW, ruleId: "" }, { ...ROW, filePath: "" }, { ...ROW, execution: "other" },
    { ...ROW, requiresTypeInformation: "false" }, { ...ROW, requiresTypeInformation: undefined },
    { ...ROW, reason: "" }, { ...ROW, reason: null }, null,
  ])("rejects a malformed execution row: %j", (row) => {
    expect(FileExecutionsSchema.safeParse([row]).success).toBe(false);
  });
  it.each([null, {}, "[]", [undefined]])("rejects malformed execution collections: %j", (rows) => {
    expect(FileExecutionsSchema.safeParse(rows).success).toBe(false);
  });
});

describe("declarative selected requests and suppressions", () => {
  it("preserves permissive flags and nullish collection defaults", () => {
    expect(SelectedRequestSchema.parse({ config: null, rules: [], full: "true", failOnWarnings: 1, upstreamRules: null })).toEqual({
      config: null, rules: [], full: false, consoleOutput: false, failOnWarnings: false,
      passOnUnpruned: false, suppressionsLocation: null, upstreamRules: [], upstreamAdvisories: [],
    });
  });
  it("retains real booleans, paths and explicit rule selections", () => {
    expect(SelectedRequestSchema.parse({ config: "eslint.config.mjs", suppressionsLocation: "ledger.json", rules: ["probe"], full: true, upstreamRules: ["no-debugger"] })).toMatchObject({
      config: "eslint.config.mjs", suppressionsLocation: "ledger.json", full: true, rules: ["probe"], upstreamRules: ["no-debugger"],
    });
  });
  it.each([
    {}, { config: null }, { config: 3, rules: [] }, { config: null, rules: "probe" },
    { config: null, rules: [1] }, { config: null, rules: [], upstreamRules: "probe" },
    { config: null, rules: [], suppressionsLocation: 1 },
  ])("rejects malformed selected requests: %j", (request) => {
    expect(SelectedRequestSchema.safeParse(request).success).toBe(false);
  });
  it("parses the nested suppression contract and drops unused payload fields", () => {
    expect(SuppressionsSchema.parse({ "input.ts": { "@sarj/probe": { count: 0, note: "ignored" } } })).toEqual({ "input.ts": { "@sarj/probe": { count: 0 } } });
  });
  it.each([-1, 0.5, "1", null, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])("rejects an invalid suppression count: %j", (count) => {
    expect(SuppressionsSchema.safeParse({ "input.ts": { "@sarj/probe": { count } } }).success).toBe(false);
  });
});

describe("opaque native capabilities", () => {
  it("keeps callable identity and its receiver rather than wrapping the function", () => {
    const finish = function(this: { readonly value: number }) { return this.value; };
    const session = record({ value: 7, finish }, "session");
    const candidate = session["finish"];
    if (!CallableSchema.validate(candidate)) throw new Error("Expected callable");
    expect(candidate).toBe(finish);
    expect(candidate.call(session)).toBe(7);
  });
  it("accepts a callable from another realm", () => {
    const value: unknown = runInNewContext("(() => 7)");
    expect(CallableSchema.validate(value)).toBe(true);
  });
  it.each([{}, [], null, undefined, "function"]) ("rejects non-callable capabilities: %j", (value) => {
    expect(CallableSchema.validate(value)).toBe(false);
  });
  it("preserves a record's identity, prototype, non-enumerable members and getters", () => {
    const value = Object.create({ inherited: 7 }) as Record<string, unknown>;
    Object.defineProperty(value, "hidden", { value: 1 });
    Object.defineProperty(value, "getter", { enumerable: true, get() { throw new Error("Do not read capability getters during container validation"); } });
    expect(record(value, "capability")).toBe(value);
    expect(record(value, "capability")["inherited"]).toBe(7);
    expect(record(value, "capability")["hidden"]).toBe(1);
  });
  it.each([null, [], "object", 1, () => 1])("rejects non-record containers: %j", (value) => {
    expect(() => record(value, "capability")).toThrow("capability must be an object");
  });
  it("preserves a validated string array's identity", () => {
    const value = ["a", "b"];
    expect(strings(value, "rules")).toBe(value);
  });
  it.each([[1], [null], "a", {}, null])("rejects non-string arrays: %j", (value) => {
    expect(() => strings(value, "rules")).toThrow("rules must be a string array");
  });
});
