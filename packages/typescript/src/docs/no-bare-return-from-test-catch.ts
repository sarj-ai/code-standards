/** @fileoverview no-bare-return-from-test-catch — the documentation and executable examples of `@sarj/no-bare-return-from-test-catch`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION = {
  summary: "Disallow a bare return from a test catch block when it skips a later assertion.",
  rationale: "An unasserted catch return can swallow a failure and skip later assertions; the complete test result also depends on other assertions and hooks.",
  remediation: "Rethrow the error, assert on it, or use the runner's explicit skip mechanism when the capability is optional.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only bare returns owned by an inline supported test callback and followed lexically by a framework assertion are reported, including each/for tables and runIf/skipIf builders. Custom builders and indirect callback references are excluded. A runner skip suppresses the finding only when it is an unconditional earlier statement in the return's block. Vitest imports and unshadowed runner globals support TestContext.skip on the first ordinary-test parameter or second for-table parameter, including a directly destructured skip alias; each-table data arguments, reassigned bindings, overwritten skip methods and dynamic skip conditions are excluded."],
  examples: [
    { id: "rethrow", title: "Preserve the failure", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "test('decodes', () => { try { decode(); } catch (error) { throw error; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "bare-return", title: "Do not silently pass", outcome: "match", files: [{ path: "src/codec.test.ts", source: "test('decodes', () => { try { decode(); } catch { return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
    { id: "table-bare-return", scenarioId: "table-catch", title: "Case tables must preserve failures", outcome: "match", files: [{ path: "src/codec.test.ts", source: "test.each(['valid', 'invalid'])('decodes %s', (input) => { try { decode(input); } catch { return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
    { id: "table-rethrow", scenarioId: "table-catch", title: "Each table case propagates its failure", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "test.each(['valid', 'invalid'])('decodes %s', (input) => { try { decode(input); } catch (error) { throw error; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "table-context-skip", scenarioId: "context-skip", title: "A Vitest context skip preserves an optional table case", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "import {test, expect} from 'vitest'; test.for(['optional'])('decodes %s', (input, context) => { try { decode(input); } catch { context.skip('codec unavailable'); return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "table-context-false-skip", scenarioId: "context-skip", title: "A false skip condition does not preserve the failure", outcome: "match", files: [{ path: "src/codec.test.ts", source: "import {test, expect} from 'vitest'; test.for(['optional'])('decodes %s', (input, context) => { try { decode(input); } catch { context.skip(false); return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
