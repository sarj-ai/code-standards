import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { RULES } from "../src/index.js";
import { createRule } from "../src/rules/_docs.js";

const SUMMARY = "Track native rule execution.";

function probe(
  required: boolean | null,
  failure: "none" | "create" | "visitor" = "none",
) {
  return createRule<readonly [], "probe">({
    name: "execution-probe",
    documentation: {
      summary: SUMMARY,
      rationale:
        "Expose whether the engine completed a requested semantic check.",
      remediation: "Supply the required parser services.",
      category: "maintainability",
      requiresTypeInformation: required,
    },
    meta: {
      type: "problem",
      docs: { description: SUMMARY },
      schema: [],
      messages: { probe: "Probe." },
    },
    defaultOptions: [],
    create(context) {
      if (failure === "create") throw new Error("probe create failed");
      if (required === true && !context.sourceCode.parserServices?.program)
        return {};
      return {
        Identifier() {
          if (failure === "visitor") throw new Error("probe visitor failed");
        },
      };
    },
  });
}

function lint(rule: ReturnType<typeof probe>, enabled = true) {
  return new Linter().verify(
    "const value = 1;",
    {
      files: ["**/*.ts"],
      languageOptions: { parser },
      plugins: { probe: { rules: { rule } } },
      rules: { "probe/rule": enabled ? "warn" : "off" },
    },
    { filename: "input.ts" },
  );
}

describe("observed rule execution", () => {
  it("records a completed syntax check even when there are no findings", () => {
    const rule = probe(false);
    const tracker = rule.trackExecution();
    expect(lint(rule)).toEqual([]);
    expect(tracker.finish()).toEqual([
      expect.objectContaining({
        execution: "ran",
        requiresTypeInformation: false,
      }),
    ]);
    expect(Object.keys(rule)).not.toContain("trackExecution");
  });

  it("reports missing type information without claiming a clean semantic check", () => {
    const rule = probe(true);
    const tracker = rule.trackExecution();
    expect(lint(rule)).toEqual([]);
    expect(tracker.finish()).toEqual([
      expect.objectContaining({
        execution: "skipped",
        reason: "missing-type-information",
        requiresTypeInformation: true,
      }),
    ]);
  });

  it("keeps undeclared requirements untracked", () => {
    const rule = probe(null);
    const tracker = rule.trackExecution();
    expect(lint(rule)).toEqual([]);
    expect(tracker.finish()).toEqual([
      expect.objectContaining({
        execution: "untracked",
        reason: "requirements-not-declared",
      }),
    ]);
  });

  it("does not invent execution for a disabled rule", () => {
    const rule = probe(false);
    const tracker = rule.trackExecution();
    expect(lint(rule, false)).toEqual([]);
    expect(tracker.finish()).toEqual([]);
  });

  it.each(["create", "visitor"] as const)(
    "preserves a native %s failure",
    (failure) => {
      const rule = probe(false, failure);
      const tracker = rule.trackExecution();
      expect(() => lint(rule)).toThrow("probe " + failure + " failed");
      expect(tracker.finish()).toEqual([
        expect.objectContaining({ execution: "failed" }),
      ]);
      expect(rule.trackExecution().finish()).toEqual([]);
    },
  );

  it("prevents overlapping sessions without replacing the active collection", () => {
    const rule = probe(false);
    const tracker = rule.trackExecution();
    expect(() => rule.trackExecution()).toThrow("already active");
    lint(rule);
    expect(tracker.finish()).toEqual([
      expect.objectContaining({ execution: "ran" }),
    ]);
    expect(() => tracker.finish()).toThrow("already finished");
  });
});

it.each([
  "no-first-party-module-mock",
  "no-reduce-accumulator-copy",
  "no-known-value-widening",
  "no-generic-json-parser",
  "prefer-typed-reflection",
  "no-growing-array-spread-in-loop",
] as const)("%s retains adopted provenance and capabilities", (name) => {
  const documentation = RULES[name].documentation;
  expect([true, false]).toContain(documentation?.requiresTypeInformation);
  expect(
    documentation?.references.some((reference) =>
      reference.startsWith(
        "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/",
      ),
    ),
  ).toBe(true);
});
