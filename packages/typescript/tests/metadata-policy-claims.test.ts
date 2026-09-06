import { expect, test } from "vitest";

import { NO_ENUM_DOCUMENTATION } from "../src/rules/no-enum.js";
import { NO_FAT_TRY_BLOCKS_DOCUMENTATION } from "../src/rules/no-fat-try-blocks.js";
import { NO_UNSAFE_MOCK_CASTING_DOCUMENTATION } from "../src/rules/no-unsafe-mock-casting.js";
import { NO_VAGUE_SUPPRESSION_DESCRIPTION_DOCUMENTATION } from "../src/rules/no-vague-suppression-description.js";
import { PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION } from "../src/rules/prefer-await-in-async-return.js";
import { PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION } from "../src/rules/prefer-named-complex-return-type.js";
import { PREFER_NODE_CRYPTO_HASH_DOCUMENTATION } from "../src/rules/prefer-node-crypto-hash.js";
import { REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION } from "../src/rules/require-interface-for-exported-class.js";
import { REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION } from "../src/rules/require-static-next-matcher.js";

test.each([
  ["enum policy", NO_ENUM_DOCUMENTATION, "const-enum", "manual"],
  ["recovery heuristic", NO_FAT_TRY_BLOCKS_DOCUMENTATION, "syntactically", "not a proof"],
  ["mock setup", NO_UNSAFE_MOCK_CASTING_DOCUMENTATION, "does not create or verify", "type helper"],
  ["suppression vocabulary", NO_VAGUE_SUPPRESSION_DESCRIPTION_DOCUMENTATION, "Missing descriptions", "not proof"],
  ["async rewrite", PREFER_AWAIT_IN_ASYNC_RETURN_DOCUMENTATION, "catch boundaries", "no scheduling equivalence"],
  ["nested return shapes", PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION, "generic wrappers", "not assumed semantically transparent"],
  ["hash conversion", PREFER_NODE_CRYPTO_HASH_DOCUMENTATION, "digest() returns a Buffer", "Runtime support"],
  ["class contract policy", REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION, "structural compatibility", "architecture policy"],
  ["Next static syntax", REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION, "Literal matcher validity", "complete framework schema"],
] as const)("%s documents the manual-review boundary", (_name, documentation, first, second) => {
  const text = JSON.stringify(documentation);
  expect(text).toContain(first);
  expect(text).toContain(second);
});
