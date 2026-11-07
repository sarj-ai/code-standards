/** @fileoverview no-mutating-container-transform — the documentation and executable examples of `@sarj/no-mutating-container-transform`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_MUTATING_CONTAINER_TRANSFORM_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Return array replacements without mutating borrowed array inputs.",
  rationale: "A returned array does not undo writes visible through the caller's original aliases. Copying only after mutation leaves the caller changed.",
  remediation: "Copy before changing the array and return the replacement, or use an explicit in-place command returning void. Preserve scalar command/result contracts.",
  category: "correctness",
  limitations: [
    "Checks explicit array-valued return annotations and primitive-element array parameters, including Array<T> and Promise<Array<T>> forms. Untyped JavaScript, named application types, arbitrary objects, nested descendants, generic elements and scalar-returning command APIs remain outside the rule.",
    "Tracks direct aliases and rebindings in linear statements and structured if branches. Unknown joins discard provenance; literal false branches are ignored. Loops, try blocks, nested functions and opaque statement forms cause the function to be excluded.",
    "Reports direct indexed/length writes, indexed deletion and standard array mutator calls. Unknown helper calls and reflective mutation are not inferred; fresh local copies are preserved. Generated/vendor files are excluded. No automatic ownership-changing rewrite is offered.",
  ],
  examples: [
    { id: "borrowed-sort", title: "Returning an array does not hide the mutation", outcome: "match", files: [{ path: "src/order.ts", source: "function ordered(values: number[]): number[] { values.sort(); return values; }" }], focusPath: "src/order.ts", expectedCount: 1, public: true },
    { id: "copied-sort", title: "Copy before mutating", outcome: "no-match", files: [{ path: "src/order.ts", source: "function ordered(values: number[]): number[] { const result = [...values]; result.sort(); return result; }" }], focusPath: "src/order.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
