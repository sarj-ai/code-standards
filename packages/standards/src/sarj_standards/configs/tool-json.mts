import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(resolve("package.json"));
const { z } = require("zod") as typeof import("zod");

// Empty object validation checks the protocol container without reading getters.
const RecordSchema = z.object({});
const StringsSchema = z.array(z.string());

export function record(value: unknown, label: string): Record<string, unknown> {
  assert.ok(RecordSchema.validate(value), `${label} must be an object`);
  return value;
}

export function strings(value: unknown, label: string): string[] {
  assert.ok(
    StringsSchema.validate(value),
    `${label} must be a string array`,
  );
  return value;
}
