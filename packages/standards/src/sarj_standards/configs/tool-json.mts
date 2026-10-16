import assert from "node:assert/strict";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function record(value: unknown, label: string): Record<string, unknown> {
  assert.ok(isRecord(value), `${label} must be an object`);
  return value;
}

export function strings(value: unknown, label: string): string[] {
  assert.ok(
    Array.isArray(value) &&
      value.every((item: unknown) => typeof item === "string"),
    `${label} must be a string array`,
  );
  return value;
}
