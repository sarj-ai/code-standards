/** @fileoverview no-sentinel-return-on-catch — the documentation and executable examples of `@sarj/no-sentinel-return-on-catch`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SENTINEL_RETURN_ON_CATCH_DOCUMENTATION = {
  summary: "Disallow swallowing a caught error by returning an empty sentinel unless the error is handled or the sentinel is part of the function contract.",
  rationale: "An unreported fallback makes operational failure indistinguishable from a legitimate empty result.",
  remediation: "Rethrow, report the error before returning, or model expected absence with an explicit predicate, safe-parse, or result contract.",
  category: "correctness",
  limitations: ["Recognized predicate, safe-parse, normal-path sentinel, deliberate parse, generated-client, and configured logging patterns are excluded. Locally shadowed undefined bindings are not treated as sentinels; recognized handling patterns are not a proof that every control-flow path handles the error."],
  examples: [
    { id: "reported-fallback", title: "Report an error before returning a fallback", outcome: "no-match", files: [{ path: "src/load.ts", source: "function load() { try { return read(); } catch (error) { logger.warn('load failed', error); return null; } }" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "silent-fallback", title: "Do not turn an unreported error into absence", outcome: "match", files: [{ path: "src/load.ts", source: "function load() { try { return read(); } catch { return null; } }" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
