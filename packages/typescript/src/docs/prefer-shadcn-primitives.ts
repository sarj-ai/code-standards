/** @fileoverview prefer-shadcn-primitives — the documentation and executable examples of `@sarj/prefer-shadcn-primitives`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SHADCN_PRIMITIVES_DOCUMENTATION = {
  summary: "Require visible raw JSX controls to use the corresponding shared shadcn primitive.",
  rationale: "Shared primitives centralize interaction, accessibility, and visual behavior across the product.",
  remediation: "Replace the raw visible control with the corresponding shared shadcn component.",
  category: "style",
  limitations: [
    "Native multiple selects and controls with possibly enabled hidden attributes are excluded. Unknown JSX spreads can hide controls; visual equivalence is not inferred.",
    "Hidden and file inputs, unassociated labels, and non-control semantic elements are excluded.",
    "Tests and the shared components/ui primitive implementation tree are excluded.",
    "Package-local project detection is opt-in and fails closed unless components.json, one unambiguous tsconfig/jsconfig alias, the exact primitive module, and its expected export all exist.",
  ],
  examples: [
    { id: "shared-button", title: "Use a shared button", outcome: "no-match", files: [{ path: "src/form.tsx", source: "import { Button } from '@/components/ui/button'; const action = <Button>Save</Button>;" }], focusPath: "src/form.tsx", expectedCount: 0, public: true },
    { id: "raw-button", title: "Do not use a raw button", outcome: "match", files: [{ path: "src/form.tsx", source: "import { Card } from '@/components/ui/card'; const action = <button>Save</button>;" }], focusPath: "src/form.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
