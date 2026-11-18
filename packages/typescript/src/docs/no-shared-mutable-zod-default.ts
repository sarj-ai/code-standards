/** @fileoverview no-shared-mutable-zod-default — authored documentation and executable examples. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SHARED_MUTABLE_ZOD_DEFAULT_DOCUMENTATION = {
  "defaultLevel": "warning",
  "summary": "Return a fresh mutable value from each Zod default factory.",
  "rationale": "Zod 4 returns function defaults directly. A factory returning one captured mutable object lets one parsed result mutate defaults observed by later parses.",
  "remediation": "Allocate a fresh array, object or collection in the factory. Preserve any intended immutable shared values; do not blindly introduce a shallow clone for nested state.",
  "category": "correctness",
  "limitations": [
    "Only inline arrow/function factories are analyzed. Named or aliased callables and direct eval/Function code abstain; no interprocedural factory ownership or freeze inference is attempted.",
    "Checks explicit Zod 4 imports, or bare Zod imports with zodMajorVersion: 4. Explicit Zod 3 imports always abstain. Stable captured array/object literals and unmodified native Map/Set/Date allocations and bounded local captured-value/schema aliases are recognized.",
    "Fresh allocations, scalars, non-function defaults, unresolved factories and visible namespace/schema replacement or escape abstain. Source-visible Object.freeze calls protect flat primitive arrays/objects only; any such freeze causes conservative abstention without inferring execution order. Nested freeze reports require an unchanged direct mutable literal child or native Map/Set/Date; opaque or frozen children abstain.",
    "An outer readonly wrapper is checked only when a reachable mutable child is positively established. Other output-processing suffixes abstain because they can replace the default; metadata-only describe/brand preserve the check. Prefix transforms do not protect a later default in Zod 4. No automatic clone or deep-copy policy is invented.",
    "A captured binding returned by distinct inline factories abstains conservatively. Captured-value mutations, property uses and opaque escapes abstain rather than guessing later object shape or freeze behavior. A factory return is recognized only inside the proven default factory; nested freeze reports require native freeze semantics."
  ],
  "examples": [
    {
      "id": "declared-contract",
      "title": "Preserve the declared boundary",
      "outcome": "no-match",
      "files": [
        {
          "path": "app.ts",
          "source": "import { z } from 'zod/v4'; z.array(z.string()).default(() => []);"
        }
      ],
      "focusPath": "app.ts",
      "expectedCount": 0,
      "public": true
    },
    {
      "id": "demonstrated-gap",
      "title": "Detect the demonstrated gap",
      "outcome": "match",
      "files": [
        {
          "path": "app.ts",
          "source": "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).default(() => shared);"
        }
      ],
      "focusPath": "app.ts",
      "expectedCount": 1,
      "public": true
    }
  ]
} as const satisfies RuleDocumentation;
