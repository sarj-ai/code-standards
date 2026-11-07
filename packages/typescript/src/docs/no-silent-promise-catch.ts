/** @fileoverview no-silent-promise-catch — the documentation and executable examples of `@sarj/no-silent-promise-catch`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SILENT_PROMISE_CATCH_DOCUMENTATION = {
  summary: "Disallow `.catch()` and second-argument `.then()` handlers that silently swallow a rejection; log, rethrow, or handle the error.",
  rationale: "A swallowed rejection hides failures and gives callers an indistinguishable fallback value.",
  remediation: "Log, rethrow, or explicitly recover from the rejection; explain intentional teardown suppression.",
  category: "correctness",
  limitations: ["Test files, teardown calls, explanatory comments, non-function handlers, and handlers that consume or report the error are excluded. Empty statements are ignored when proving a whole handler is silent.", "Recognized imported Zod construction chains and their stable local aliases are excluded, including URL schemas and primitive bigint, boolean, number and string coercion. Other untyped catch-like APIs are not proven to be Promises.", "Computed methods resolve literal syntax and stable local string aliases in lexical scope. Function-derived, object-derived and mutated computed keys remain unproven.", "A following then link is accepted as recovery except for directly invoked, nonoptional, one-argument nonasync arrow identities returning the same binding without effects. A later meaningful then handler preserves the recovery exclusion."],
  examples: [
    { id: "reported-rejection", title: "Report the rejection", outcome: "no-match", files: [{ path: "src/load.ts", source: "load().catch((error) => logger.error({ error }, 'load failed'));" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "silent-rejection", title: "Do not swallow the rejection", outcome: "match", files: [{ path: "src/load.ts", source: "load().catch(() => null);" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
    { id: "stable-computed-catch", scenarioId: "computed-method-scope", title: "Report a rejection through a stable computed method", outcome: "match", files: [{ path: "src/load.ts", source: "const method = 'catch'; Promise.reject(new Error('lost'))[method](() => null);" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
    { id: "stable-computed-body-parser", scenarioId: "computed-method-scope", title: "Preserve a recognized optional body parse fallback", outcome: "no-match", files: [{ path: "src/load.ts", source: "const method = 'json'; new Response('')[method]().catch(() => null);" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
