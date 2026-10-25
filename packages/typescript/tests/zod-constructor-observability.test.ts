import { expect, it } from "vitest";
import { z } from "zod/v4";
import { z as legacyZod } from "zod/v3";

import nativeEnum from "../src/rules/no-zod-native-enum.js";
import multiLiteral from "../src/rules/prefer-multi-value-zod-literal.js";

function observeConstruction(build: () => void): readonly string[] {
  const observations: string[] = [];
  const previous = z.config().postProcessor;
  z.config({
    postProcessor: (schema: z.ZodType) => {
      observations.push(schema._zod.def.type);
    },
  });
  try {
    build();
    return observations;
  } finally {
    z.config({ postProcessor: previous });
  }
}

it("retains a supported hook's private literal and union construction sequence", () => {
  const original = observeConstruction(() => {
    z.union([z.literal(1), z.literal(2)]);
  });
  const proposed = observeConstruction(() => {
    z.literal([1, 2]);
  });
  expect(original).toEqual(["literal", "literal", "union"]);
  expect(proposed).toEqual(["literal"]);
  expect(multiLiteral.meta.fixable).toBeUndefined();
});

it("exposes an optional wrapper to a supported constructor hook", () => {
  const original = observeConstruction(() => {
    z.array(z.string()).optional().default([]);
  });
  const proposed = observeConstruction(() => {
    z.array(z.string()).default([]);
  });
  expect(original).toEqual(["string", "array", "optional", "default"]);
  expect(proposed).toEqual(["string", "array", "default"]);
});

it("observes the API frame even when native enum keys already equal their values", () => {
  const stacks: string[] = [];
  const previous = z.config().postProcessor;
  z.config({
    postProcessor: () => {
      stacks.push(new Error("schema construction").stack ?? "");
    },
  });
  try {
    z.nativeEnum({ active: "active" });
    z.enum({ active: "active" });
  } finally {
    z.config({ postProcessor: previous });
  }
  expect(stacks[0]).toContain("nativeEnum");
  expect(stacks[1]).not.toContain("nativeEnum");
  expect(nativeEnum.meta.fixable).toBeUndefined();
});

it("keeps the closed legacy construction free of supported error-map callbacks", () => {
  const observations: string[] = [];
  const previous = legacyZod.getErrorMap();
  legacyZod.setErrorMap((issue, context) => {
    observations.push(issue.code);
    return { message: context.defaultError };
  });
  try {
    const original = legacyZod.array(legacyZod.string()).optional().default([]);
    const proposed = legacyZod.array(legacyZod.string()).default([]);
    expect(observations).toEqual([]);
    expect(original.parse(undefined)).toEqual(proposed.parse(undefined));
    expect(original.parse(["α", "sample"])).toEqual(
      proposed.parse(["α", "sample"]),
    );
    expect(observations).toEqual([]);
  } finally {
    legacyZod.setErrorMap(previous);
  }
});
