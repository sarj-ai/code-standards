import assert from "node:assert/strict";
import test from "node:test";

import { matchesRuleSearch, normalizeRuleSearch } from "../src/lib/rule-search.ts";

await test("rule search accepts names, prose, mixed case, and multiple words", () => {
  const text = normalizeRuleSearch(
    "no-offset-pagination SQL · Use a cursor for large result sets.",
  );
  for (const query of [
    "OFFSET",
    "offset pagination",
    "SQL cursor",
    "no_offset",
    "  large   result  ",
    "",
  ]) {
    assert.ok(matchesRuleSearch(text, query), query);
  }
  assert.equal(matchesRuleSearch(text, "offset missing"), false);
  assert.equal(matchesRuleSearch(text, "<script>"), false);
});

await test("separators in rule IDs match ordinary search words", () => {
  assert.equal(normalizeRuleSearch("API/require_typed-response"), "api require typed response");
  assert.ok(matchesRuleSearch(normalizeRuleSearch("API/require_typed-response"), "typed-response"));
});
