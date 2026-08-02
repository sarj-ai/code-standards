import { describe, expect, it } from "vitest";

import {
  BARE_LABEL_RE,
  WALL_DEFAULTS,
  WALL_SCHEMA,
  carriesValue,
  commentBody,
  isLabel,
  isTagsOnly,
  isWall,
  knownTokens,
  labelStems,
  novelWords,
} from "../../src/rules/_comment-wall.js";

describe("comment-wall thresholds", () => {
  it("keeps the shared defaults and schema in step", () => {
    expect(WALL_DEFAULTS).toEqual({
      minCommentedMembers: 3,
      minCommentedRatio: 0.6,
      minRestatedRatio: 0.75,
      maxNovelWords: 1,
    });
    expect(Object.keys(WALL_SCHEMA.properties)).toEqual(Object.keys(WALL_DEFAULTS));
  });

  it.each([
    [3, 3, 3, true],
    [3, 2, 2, false],
    [5, 2, 2, false],
    [4, 4, 3, true],
    [4, 4, 2, false],
  ])(
    "judges %i members, %i comments and %i restatements as wall=%s",
    (members, commented, restated, expected) => {
      expect(isWall(members, commented, restated, WALL_DEFAULTS)).toBe(expected);
    },
  );
});

describe("comment-wall value floor", () => {
  it.each([
    ["external reference", "tracked in CORE-42"],
    ["value-bearing tag", "The host. @alpha"],
    ["documented default", "The mode defaults to safe"],
    ["digit", "The 1-based index"],
    ["unit", "The timeout in seconds"],
    ["quoted example", 'The mode, e.g. "safe"'],
    ["banner", "--- section ---"],
    ["non-ASCII prose", "اسم الشركة"],
  ])("preserves a comment carrying a %s", (_kind, body) => {
    expect(carriesValue(body)).toBe(true);
  });

  it("does not preserve a bare restatement", () => {
    expect(carriesValue("The database host")).toBe(false);
  });
});

describe("comment-wall labels and tokens", () => {
  it("normalises line and JSDoc bodies alike", () => {
    expect(commentBody({ value: " links " } as never)).toBe("links");
    expect(commentBody({ value: "*\n * links\n " } as never)).toBe("links");
  });

  it("distinguishes labels, tag directives and prose", () => {
    expect(BARE_LABEL_RE.test("clientMiddleware")).toBe(true);
    expect(labelStems("ClientLinks")).toBe("client link");
    expect(isLabel("Mimir")).toBe(true);
    expect(isLabel("Partial match")).toBe(false);
    expect(isTagsOnly("@ignore @internal")).toBe(true);
    expect(isTagsOnly("The host. @internal")).toBe(false);
  });

  it("counts only content absent from the member source", () => {
    const known = knownTokens("createUserRecords?: boolean");
    expect(novelWords("Creates the user record", known)).toBe(0);
    expect(novelWords("Creates atomic user records", known)).toBe(1);
    expect(novelWords("Creates atomic durable user records", known)).toBe(2);
  });
});
