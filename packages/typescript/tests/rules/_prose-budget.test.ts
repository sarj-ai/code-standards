import { describe, expect, it } from "vitest";

import { sentenceUnits } from "../../src/rules/_prose-budget.js";

describe("sentenceUnits", () => {
  it.each([
    ["See https://example.com/a. Continue there", 1],
    ["Run `first. Second.` once.", 1],
    ["Version 2.1 is stable.", 1],
    ["Use e.g. compact mode.", 1],
    ["Compare i.e. normalized values.", 1],
    ["Current vs. legacy behavior.", 1],
    ["Supports retries etc. by default.", 1],
    ["First fact. Second fact?", 2],
  ])("protects tokens and counts real boundaries in %s", (text, expected) => {
    expect(sentenceUnits(text)).toBe(expected);
  });

  it("counts unpunctuated list items", () => {
    expect(sentenceUnits("Modes:\n- fast path\n- safe path")).toBe(2);
  });
});
