import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { validateCatalog } from "../src/lib/catalog-validation.ts";
import { parseReference } from "../src/lib/parse-reference.ts";
import { parseCatalog } from "../src/lib/third-party-catalog.ts";
import { parseSearchIndex } from "../src/lib/parse-search-index.ts";

await test("rejects malformed search entries before rendering their fields", () => {
  const entry = { anchor: "rule-one", displayId: "one", family: null, href: "/one/", summary: "First rule" };
  assert.equal(parseSearchIndex({ entries: [entry] })[0]?.searchText, "one first rule");
  assert.throws(() => parseSearchIndex({ entries: [{ ...entry, summary: 42 }] }));
  assert.throws(() => parseSearchIndex({ entries: [null] }));
  assert.throws(() => parseSearchIndex({ entries: [{}] }));
});

await test("validates nested CLI options rather than trusting the envelope", async () => {
  const value: unknown = JSON.parse(await readFile(new URL("../../../packages/standards/src/sarj_standards/configs/cli-reference.v1.json", import.meta.url), "utf8"));
  const reference = parseReference(value);
  assert.ok(reference.commands.length > 0);
  const command = reference.commands[0];
  assert.ok(command);
  const option = { kind: "option", names: ["--verbose"], metavar: null, summary: "Verbose output", choices: [], required: false, repeatable: false };
  assert.doesNotThrow(() => parseReference({ ...reference, commands: [{ ...command, options: [option] }] }));
  assert.throws(() => parseReference({ ...reference, commands: [{ ...command, options: [{ ...option, required: "true" }] }] }), TypeError);
});

await test("retains catalog relationships after structural schema validation", async () => {
  const raw: unknown = JSON.parse(await readFile(new URL("../../../packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json", import.meta.url), "utf8"));
  const value = validateCatalog(raw);
  assert.equal(value, raw);
  const first = value.rules[0];
  assert.ok(first);
  const example = first.examples[0];
  assert.ok(example);
  assert.throws(() => { validateCatalog({ ...value, rules: [first, first] }); }, /duplicate key/u);
  assert.throws(() => { validateCatalog({ ...value, rules: [{ ...first, examples: [{ ...example, expectedCount: "1" }, ...first.examples.slice(1)] }, ...value.rules.slice(1)] }); }, TypeError);
});

await test("retains strict fields and cross-provider checks in the third-party catalog", async () => {
  const value: unknown = JSON.parse(await readFile(new URL("../src/generated/third-party-rules.v1.json", import.meta.url), "utf8"));
  const catalog = parseCatalog(value);
  const first = catalog.rules[0];
  assert.ok(first);
  assert.throws(() => parseCatalog({ ...catalog, extra: true }), TypeError);
  assert.throws(() => parseCatalog({ ...catalog, rules: [{ ...first, provider: "absent" }] }), /unknown provider/u);
  assert.throws(() => parseCatalog({ ...catalog, rules: [{ ...first, hasSuggestions: "true" }, ...catalog.rules.slice(1)] }), TypeError);
});
