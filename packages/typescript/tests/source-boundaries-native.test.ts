import { expect, it } from "vitest";
import { stockLint } from "./_stock-cli.js";

it.each([
  [
    "no-known-value-widening",
    "let failure: unknown; try { failure = new Error('response'); } catch (error) { failure = error; }",
    0,
  ],
  [
    "no-known-value-widening",
    "let failure: unknown = new Error('response'); try { run(); } catch (error) { failure = error; }",
    0,
  ],
  [
    "no-known-value-widening",
    "let failure: unknown; failure = new Error('known');",
    1,
  ],
  [
    "no-known-value-widening",
    "const external: unknown = 1; let failure: unknown; failure = new Error('response'); failure = external;",
    1,
  ],
  [
    "no-known-value-widening",
    "const external: unknown = 1; const value: unknown = external;",
    2,
  ],
  [
    "no-known-value-widening",
    "let failure: unknown; failure = new Error('known'); function nested() { let failure: unknown; failure = read(); }",
    1,
  ],
  [
    "prefer-typed-reflection",
    'function readType(value: object): unknown { return Reflect.get(value, "type"); }',
    0,
  ],
  [
    "prefer-typed-reflection",
    'type Boundary = object; function readType(value: Boundary): unknown { return Reflect.get(value, "type"); }',
    0,
  ],
  [
    "prefer-typed-reflection",
    'function readType(value: { type: string }): unknown { return Reflect.get(value, "type"); }',
    1,
  ],
  [
    "prefer-typed-reflection",
    'type Boundary = object; function readType() { type Boundary = { type: string }; const value: Boundary = read(); return Reflect.get(value, "type"); }',
    1,
  ],
] as const)(
  "%s preserves the source boundary in %s",
  (ruleId, source, count) => {
    const result = stockLint(ruleId, source);
    expect(result.diagnostics).toHaveLength(count);
    expect(result.status).toBe(count === 0 ? 0 : 1);
  },
);
