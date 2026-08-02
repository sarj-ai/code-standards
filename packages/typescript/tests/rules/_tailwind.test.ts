import { describe, expect, it } from "vitest";

import { classTokens, tailwindBase } from "../../src/rules/_tailwind.js";

describe("tailwindBase", () => {
  it("removes chained variants and a leading important marker", () => {
    expect(tailwindBase("hover:dark:!bg-red-500")).toBe("bg-red-500");
  });

  it("removes variant names containing digits and hyphens", () => {
    expect(tailwindBase("2xl:focus-visible:bg-red-500")).toBe("bg-red-500");
  });

  it("preserves colons inside arbitrary values", () => {
    expect(tailwindBase("hover:bg-[url(http://example.com/a:b)]")).toBe(
      "bg-[url(http://example.com/a:b)]",
    );
  });
});

describe("classTokens", () => {
  it("splits all whitespace and removes empty tokens", () => {
    expect(classTokens("  bg-primary\n\ttext-foreground  ")).toEqual([
      "bg-primary",
      "text-foreground",
    ]);
  });
});
