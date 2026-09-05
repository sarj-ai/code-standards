import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_RESTATED_COMMENT_DOCUMENTATION } from "../../src/rules/no-restated-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-restated-comment", rule, {
  valid: [
    { name: "keeps a value and inferred-type group label", code: "// number branding\nconst numberSchema = z.number().brand<42>();\ntype NumberSchema = z.infer<typeof numberSchema>;\nassertEqual<NumberSchema, number>();" },
    { name: "keeps a symbol and type-query group label", code: "// symbol branding\nconst MyBrand: unique symbol = Symbol('hello');\ntype MyBrand = typeof MyBrand;\nassertEqual<MyBrand, symbol>();" },
    { name: "keeps a camel-case one-word heading", code: "/// bigInt\nconst bigIntSchema = z.bigint();\ntest('bigInt', () => parse(bigIntSchema));" },
    { name: "keeps a type-table heading", code: "// $ZodPromise\nz.promise(z.string()) satisfies z.core.$ZodPromise;" },
    { name: "keeps punctuated branch-label prose", code: "// Token lists.\nreturn areEqualTokenLists(left, right);" },
    { name: "conservatively keeps labels within sibling test groups", code: "test('decode', async () => {\n// Async decode\nconst decodedResult = await decodeAsync(input);\nexpect(decodedResult).toEqual(input);\n});\ntest('encode', () => {});" },
    { name: "conservatively keeps labels within sibling type-test groups", code: "test('brands', () => {\n// number branding\nconst numberSchema = z.number().brand();\ntype NumberSchema = typeof numberSchema;\n});\ntest('other', () => {});" },
    { name: "conservatively excludes enclosing function sibling groups", code: "function first() {\n// Serialize key\nreturn serialize(key);\n}\nfunction second() {}" },
    { name: "conservatively excludes enclosing block sibling groups", code: "if (ready) {\n// Serialize key\nreturn serialize(key);\n}\nif (other) {}" },
    { name: "keeps restriction prose", code: "// Serialize only key\nconst key = serialize(input);" },
    { name: "keeps conditional prose", code: "// Serialize key if cached\nconst key = serialize(cache);" },
    { name: "keeps ordering prose", code: "// Cleanup after send\nreturn sendAfterCleanup();" },
    { name: "keeps repetition prose", code: "// Serialize key again\nconst key = serialize(input);" },
    { name: "keeps source direction", code: "// Serialize key from payload\nconst payload = serialize(key);" },
    { name: "keeps destination direction", code: "// Serialize key to payload\nconst key = serialize(payload);" },
    { name: "keeps per-item restrictions", code: "// Serialize every key\nconst key = serialize(input);" },
    { name: "keeps an immediate sibling group label", code: "// Serialize key\nconst key = serialize(input);\nconst value = transform(input);" },
    { name: "ignores a neighboring statement as evidence", code: "// hashed user\nrun(); const hashedUser = value;" },
    { name: "ignores literal payload as evidence", code: "// serialized values\nrecord(\"serialized values\");" },
    { name: "ignores template text as evidence", code: "// serialized values\nrecord(`serialized values`);" },
    { name: "ignores inline comment text as evidence", code: "// payload key\nconst result = transform(input /* payload key */);" },
    { name: "ignores a trailing block comment as evidence", code: "// issue path length\nreturn fn(value); /* issue path length */" },
    { name: "accepts the documented reason comment", code: NO_RESTATED_COMMENT_DOCUMENTATION.examples[0].files[0].source },
    { name: "accepts the result of the deletion suggestion", code: "const key = serialize(input);" },
    // One unmatched word means the comment carries something the code does not.
    {
      name: "keeps a comment when one content word is absent from the code",
      code: "// serialize the vault key\nconst [key] = serialize(bankKey);\nreturn null;",
    },
    // No prefix matching — `valid` is not `validate`, `config` is not `configure`.
    { code: "// valid config\nvalidate(configureAll());\nreturn null;" },
    // A single content word labels a thing; it does not restate a statement.
    { code: "// Hashing\nhash(b);\nreturn null;" },
    {
      name: "keeps a question even when its words appear in the statement",
      code: "// cached page data?\nconst pageData = getCachedPageData();\nreturn null;",
    },
    // The protected class is an exemption floor.
    { code: "// serialize key (PLT-812)\nconst key = serialize(k);\nreturn null;" },
    { code: "// serialize key — see https://example.com/keys\nconst key = serialize(k);\nreturn null;" },
    { code: "// serialize key every 30 seconds\nconst key = serialize(k);\nreturn null;" },
    { code: "// serialize key because the cache is keyed on it\nconst key = serialize(k);\nreturn null;" },
    // Modality, a colon lead-in, inline emphasis, a bare negation.
    { code: "// can also serialize key\nconst key = serialize(k);\nreturn null;" },
    { code: "// serialize key:\nconst key = serialize(k);\nreturn null;" },
    { code: "// serialize *key*\nconst key = serialize(k);\nreturn null;" },
    // zod/packages/zod/src/v4/classic/tests/refine.test.ts:546 — a NEGATIVE
    // property that the positive spelling below cannot state.
    { code: "// no issues with confirmPassword\nreturn payload.issues.every(hasNoConfirmPassword);" },
    // A run of `//` lines is a paragraph, not a label for the next statement.
    { code: "// why we do this at all\n// serialize key\nconst key = serialize(k);\nreturn null;" },
    // A comment above a block labels a region.
    { code: "// serialize key\nfunction serializeKey() { return 1; }" },
    { code: "// serialize key\nif (serializeKey()) { doIt(); }" },
    {
      name: "keeps a label above a multi-line statement",
      code: "// cached page data\nconst pageData = getCachedPageData(\n  pageKey,\n);\nreturn null;",
    },
    {
      name: "keeps a block comment because only one-line labels are in scope",
      code: "/* cached page data */\nconst pageData = getCachedPageData();\nreturn null;",
    },
    // A label heading a run of siblings of the same kind provides the grouping.
    // zod/packages/zod/src/v4/classic/tests/assignability.test.ts is a whole
    // table of these; it alone produced 89 hits before the sibling test worked.
    {
      code: "// $ZodString\nz.string() satisfies z.core.$ZodString;\nz.number() satisfies z.core.$ZodNumber;",
    },
    // A data declaration is labelled, not narrated.
    {
      name: "keeps a label above a plain data declaration",
      code: "// profile status\nconst profileStatus = STATUS;\nreturn null;",
    },
    // Commented-out code and banners belong to `no-comment-cruft`.
    { code: "// const key = serialize(k);\nconst key = serialize(k);\nreturn null;" },
    { code: "// ==== serialize ====\nconst key = serialize(k);\nreturn null;" },
    // A directive.
    { code: "// sarj-noqa: deliberate\nconst key = serialize(k);\nreturn null;" },
    // Non-ASCII prose the tokenizer cannot read.
    { code: "// تحديث المفتاح\nconst key = serialize(k);\nreturn null;" },
    // `no-comment-cruft` already owns the verb-led statement-head shape, so this
    // rule stays quiet on it rather than reporting the same comment twice.
    { code: "// increment the counter\ncounter += 1;\nreturn null;" },
    // A generated file mirrors its generator.
    {
      code: "// @generated by openapi\n// serialize key\nconst key = serialize(k);\nreturn null;",
      filename: "api.ts",
    },
    {
      name: "keeps prose one word beyond the eight-word budget",
      code: "// cached page data result output value item record entry\nconst cachedPageDataResultOutputValueItemRecordEntry = getCachedPageDataResultOutputValueItemRecordEntry();\nreturn null;",
    },
  ],
  invalid: [
    { name: "does not group an unrelated type query", code: "// Serialize key\nconst key = serialize(input);\ntype Payload = typeof other;", errors: [{ messageId: "restatesLineBelow", suggestions: 1 }] },
    {
      name: "uses identifiers inside template interpolations but not template text",
      code: "// serialized values\nreturn `${serializeValues(input)}`;",
      errors: [{ messageId: "restatesLineBelow", suggestions: 1 }],
    },
    {
      name: "does not treat a preceding trailing comment as a paragraph",
      code: "run(); // trace\n// Serialize key\nconst key = serialize(input);",
      output: null,
      errors: [{ messageId: "restatesLineBelow", suggestions: [{ messageId: "deleteComment", output: "run(); // trace\nconst key = serialize(input);" }] }],
    },
    {
      name: "does not treat a trailing comment as a prose paragraph",
      code: "// Serialize key\nconst key = serialize(input); // trace",
      output: null,
      errors: [{ messageId: "restatesLineBelow", suggestions: [{ messageId: "deleteComment", output: "const key = serialize(input); // trace" }] }],
    },
    {
      name: "offers whole-line deletion without applying an autofix",
      code: NO_RESTATED_COMMENT_DOCUMENTATION.examples[1].files[0].source,
      output: null,
      errors: [
        {
          messageId: "restatesLineBelow",
          suggestions: [
            {
              messageId: "deleteComment",
              output: "const key = serialize(input);",
            },
          ],
        },
      ],
    },
    {
      code: "// Serialize key\nconst [key] = serialize(_k);\nreturn null;",
      errors: [{ messageId: "restatesLineBelow", suggestions: 1 }],
    },
    {
      code: "// issue path length\nconst issues = sortByPathLength(error.issues);\nreturn null;",
      errors: [{ messageId: "restatesLineBelow", suggestions: 1 }],
    },
    {
      name: "preserves CRLF while deleting an indented comment line",
      code: "function collect() {\r\n\t// issue path length\r\n\treturn sortByPathLength(error.issues);\r\n}",
      output: null,
      errors: [
        {
          messageId: "restatesLineBelow",
          suggestions: [
            {
              messageId: "deleteComment",
              output: "function collect() {\r\n\treturn sortByPathLength(error.issues);\r\n}",
            },
          ],
        },
      ],
    },
    {
      code: "// Get the cached page data\nconst pageData = pageKey ? getCache().data : undefined;\nreturn null;",
      errors: [{ messageId: "restatesLineBelow", suggestions: 1 }],
    },
    // The trailing-`e` strip makes the inflection fold symmetric, so
    // `serialized` and `serialize` land on the same stem.
    {
      code: "// serialized values\nconst out = serializeValues(input);\nreturn null;",
      errors: [{ messageId: "restatesLineBelow", suggestions: 1 }],
    },
    {
      name: "reports a restatement at the eight-word budget",
      code: "// cached page data result output value item record\nconst cachedPageDataResultOutputValueItemRecord = getCachedPageDataResultOutputValueItemRecord();\nreturn null;",
      errors: [{ messageId: "restatesLineBelow", suggestions: 1 }],
    },
  ],
});
