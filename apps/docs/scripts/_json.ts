import assert from "node:assert/strict";
import { z } from "zod";

const RecordSchema = z.record(z.string(), z.unknown());
const TextSchema = z.string();

export function record(value: unknown, label: string): Record<string, unknown> {
  const result = RecordSchema.safeParse(value);
  assert.ok(result.success, `${label} must be an object`);
  return result.data;
}

export function array(value: unknown, label: string): unknown[] {
  assert.ok(Array.isArray(value), `${label} must be an array`);
  return value;
}

export function text(value: unknown, label: string): string {
  const result = TextSchema.safeParse(value);
  assert.ok(result.success, `${label} must be a string`);
  return result.data;
}
