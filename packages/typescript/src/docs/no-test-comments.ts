/** @fileoverview no-test-comments — the documentation and executable examples of `@sarj/no-test-comments`. */

import type { RuleDocumentation } from "../documentation.js";

export type Options = readonly [{ readonly allFiles?: boolean }];

export const NO_TEST_COMMENTS_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Express test behavior through names, fixtures and assertions instead of prose comments.",
  rationale: "Test comments duplicate or obscure behavior that executable setup and assertions should communicate.",
  remediation: "Move the explanation into a descriptive test or helper name, then remove the comment. Review and migrate legal notices and tool directives before removing frontend comments; preserve those contracts in non-frontend tests.",
  category: "testing",
  autofix: "safe",
  limitations: [
    "In frontend modules and frontend packages, every comment token is reported without automatic deletion, including directives and legal notices. The no-frontend-comments rule delegates recognized tests here. Non-frontend tests retain the existing directive/legal exceptions and safe fixes.",
    "Checks actual line and block comment tokens in recognized maintained test files, including test fixtures; strings and template text remain unchanged. Generated/vendor files are excluded.",
    "Legal notices, shebangs, TypeScript triple-slash references, coverage/build annotations and explicit lint/type/test/formatter directives remain allowed. Executable detect-secrets 1.5.0 allowlist/whitelist pragmas retain its case-sensitive delimiter, spacing, physical-line and next-line grammar; arbitrary pragma prose remains ordinary commentary. Rationale on an executable directive remains the owning tool's responsibility.",
    "The automatic fix removes comments and adjacent padding while retaining every line ending and necessary token boundary; it does not rename tests or remove executable statements. Bare integration/e2e directories and ambiguous hyphen/underscore test basenames require another concrete test-path signal or a runtime testing-framework import; ordinary production integration modules and rule implementations ending in -test are preserved.",
  ],
  examples: [
    { id: "narrated-assertion", title: "Put behavior in the test name", outcome: "match", files: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409); // Confirm the rejected request\n" }], fixedFiles: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409);\n" }], focusPath: "src/request.test.ts", expectedCount: 1, public: true },
    { id: "named-behavior", title: "The assertion expresses the behavior", outcome: "no-match", files: [{ path: "src/request.test.ts", source: "expect(result.status).toBe(409);" }], focusPath: "src/request.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation<Options>;
