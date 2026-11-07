/** @fileoverview prefer-whole-object-assertion — the documentation and executable examples of `@sarj/prefer-whole-object-assertion`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_WHOLE_OBJECT_ASSERTION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Collapse consecutive assertions on one object into a whole-object assertion so related mismatches are reported together.",
  rationale: "One whole-object assertion presents related expectations together and produces a complete structural diff.",
  remediation: "Consider one `toMatchObject` assertion for ordinary data objects. Preserve missing-property checks, identity, and getter or proxy behavior when deciding whether to combine assertions.",
  category: "testing",
  aliases: ["strict-test-assertions"],
  autofix: "none",
  limitations: ["Undefined-property assertions are excluded because whole-object matching can require previously absent properties. Indexed runs with an immediately adjacent literal exact-length assertion are excluded; non-adjacent length checks and intentional prefix contracts remain manual review. No automatic rewrite: grouping can change observable getter or proxy reads."],
  examples: [
    { id: "whole-object", title: "Assert the object once", outcome: "no-match", files: [{ path: "src/user.test.ts", source: "expect(user).toMatchObject({ id: 1, name: 'Ada' });" }], focusPath: "src/user.test.ts", expectedCount: 0, public: true },
    { id: "member-run", title: "Consider grouping related data properties", outcome: "match", files: [{ path: "src/user.test.ts", source: "expect(user.id).toBe(1);\nexpect(user.name).toBe('Ada');" }], focusPath: "src/user.test.ts", expectedCount: 1, public: true },
    { id: "indexed-prefix", scenarioId: "array-length", title: "Review the collection contract before combining indexed assertions", outcome: "match", files: [{ path: "src/user.test.ts", source: "expect(users[0]).toEqual('Ada');\nexpect(users[1]).toEqual('Grace');" }], focusPath: "src/user.test.ts", expectedCount: 1, public: true },
    { id: "length-and-prefix", scenarioId: "array-length", title: "A separate exact length can accompany an intentional prefix contract", outcome: "no-match", files: [{ path: "src/user.test.ts", source: "expect(users).toHaveLength(3);\nexpect(users[0]).toEqual('Ada');\nexpect(users[1]).toEqual('Grace');" }], focusPath: "src/user.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
