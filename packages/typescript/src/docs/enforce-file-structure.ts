/** @fileoverview enforce-file-structure — the documentation and executable examples of `@sarj/enforce-file-structure`. */

import type { RuleDocumentation } from "../documentation.js";

export const ENFORCE_FILE_STRUCTURE_DOCUMENTATION = {
  summary: "Require imports before body statements and require `use server` to be the first statement.",
  rationale:
    "Interleaved imports obscure module dependencies, while a displaced `use server` string is not an active directive.",
  remediation:
    "Move `use server` to the first statement when present, then place imports before declarations and executable statements.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "The rule skips tests and generated files, treats re-exports as neutral, and does not order body declarations. Only misplaced import type declarations in comment-free files are automatically moved; runtime imports and directive activation remain manual.",
  ],
  examples: [
    {
      id: "imports-first",
      title: "Imports precede module declarations",
      outcome: "no-match",
      files: [{ path: "src/component.ts", source: "import { z } from 'zod';\nexport const schema = z.string();" }],
      focusPath: "src/component.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "import-after-declaration",
      title: "An import follows a module declaration",
      outcome: "match",
      files: [{ path: "src/component.ts", source: "export const x = 1;\nimport { z } from 'zod';" }],
      focusPath: "src/component.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; const value = 1; import type { Foo } from \"foo\";" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; import type { Foo } from \"foo\";\nconst value = 1; " }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
