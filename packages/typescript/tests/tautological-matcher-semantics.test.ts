import assert from "node:assert/strict";
import { expect, test } from "vitest";

test("a diagnostic message preserves the outcome and reports the failing observation", () => {
  const check = (actual: boolean): void => { expect(actual, "service was not ready").toBe(true); };
  assert.doesNotThrow(() => check(true));
  assert.throws(() => check(false), /service was not ready/);
});

test("an exception assertion observes the inner matcher contract", () => {
  assert.doesNotThrow(() => expect(() => expect(true).toBe(true)).not.toThrow());
  assert.throws(() => expect(() => expect(false).toBe(true)).not.toThrow());
});

test("a visible matcher override and equality tester can reject identical literals", () => {
  expect.extend({ toBe: () => ({ pass: false, message: () => "custom identity contract" }) });
  assert.throws(() => expect(true).toBe(true), /custom identity contract/);
  expect.addEqualityTesters([() => false]);
  assert.throws(() => expect({ ready: true }).toEqual({ ready: true }));
  assert.throws(() => expect("ready").toStrictEqual("ready"));
});
