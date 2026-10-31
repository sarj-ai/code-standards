import { expect, it } from "vitest";

import { commentLineEndings, type CommentRemoval } from "../../src/rules/_comment-edits.js";

it.each(["\n", "\r\n", "\r", "\u2028", "\u2029"])("retains the exact terminator in an owned removal span %s", ending => {
  const source = `left/* prose${ending}more */right`;
  const removal: CommentRemoval = { range: [source.indexOf("/*"), source.indexOf("*/") + 2] };
  expect(commentLineEndings(source, removal)).toBe(ending);
});

it("retains an existing CRLF alongside Unicode separators", () => {
  const source = "left/* prose\r\nmore\u2028last\u2029*/right";
  const removal: CommentRemoval = { range: [source.indexOf("/*"), source.indexOf("*/") + 2] };
  expect(commentLineEndings(source, removal)).toBe("\r\n\u2028\u2029");
});

it.each([
  { name: "internal bare CR and separate LF", prefix: "left", comment: "/* prose\rmore\n*/", suffix: "right" },
  { name: "right-neighbor LF after an extracted CR", prefix: "left", comment: "/* prose\rmore */", suffix: "\nright" },
  { name: "left-neighbor CR before an extracted LF", prefix: "left\r", comment: "/* prose\nmore */", suffix: "right" },
])("refuses a changed CRLF token sequence: $name", ({ prefix, comment, suffix }) => {
  const source = prefix + comment + suffix;
  const removal: CommentRemoval = { range: [prefix.length, prefix.length + comment.length] };
  expect(commentLineEndings(source, removal)).toBeNull();
});

it("preserves every Unicode separator from a full own-line removal range", () => {
  const source = "/* prose\u2028more\u2029*/\nconst value = 1;";
  const removal: CommentRemoval = { range: [0, source.indexOf("const")] };
  expect(commentLineEndings(source, removal)).toBe("\u2028\u2029\n");
});

it("keeps an inline removal without a terminator usable", () => {
  const source = "/* prose */";
  const removal: CommentRemoval = { range: [0, source.length] };
  expect(commentLineEndings(source, removal)).toBe("");
});
