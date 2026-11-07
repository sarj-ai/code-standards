/** @fileoverview production-derived-test-cases — the documentation and executable examples of `@sarj/production-derived-test-cases`. */

import type { RuleDocumentation } from "../documentation.js";

export const PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep an independent membership oracle when production collections supply test cases.",
  rationale: "A test table copied from the production allowed or supported collection changes together with that collection, so removed members silently remove their test cases.",
  remediation: "Declare a literal expected membership table, assert the production collection equals it, and drive cases from that table. Keep deliberate dynamic sweeps with an explained local suppression.",
  category: "testing",
  limitations: [
    "Checks direct first-party relative runtime imports named ALLOWED, ELIGIBLE, REQUIRED or SUPPORTED with underscore-delimited words, passed directly to Vitest each/for tables. Resolves test/it import aliases and unchanged local test.extend runners. Registries, enum introspection, third-party imports and test-support imports remain excluded.",
    "An unconditional module or directly registered test assertion using imported Vitest expect and toEqual/toStrictEqual against a literal array supplies an independent oracle. A stable local const literal table is also accepted when every read belongs to a recognized expectation or case table. Helper-indirected assertions and mutable/captured tables remain outside this bounded proof.",
    "This is a membership-contract review advisory, not a deletion instruction. It does not infer exhaustive coverage, read imported source or automatically remove dynamically generated tests. Generated/vendor files are excluded.",
  ],
  examples: [
    { id: "production-cases", title: "Missing production entries also disappear from these cases", outcome: "match", files: [{ path: "src/roles.test.ts", source: "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; test.each(SUPPORTED_ROLES)('%s', role => { expect(build(role)).toBeDefined(); });" }], focusPath: "src/roles.test.ts", expectedCount: 1, public: true },
    { id: "independent-membership", title: "An independent assertion notices missing entries", outcome: "no-match", files: [{ path: "src/roles.test.ts", source: "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; test('membership', () => { expect(SUPPORTED_ROLES).toEqual(['reader', 'writer']); }); test.each(SUPPORTED_ROLES)('%s', role => { expect(build(role)).toBeDefined(); });" }], focusPath: "src/roles.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
