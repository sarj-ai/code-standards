/** @fileoverview prefer-typed-cli — authored documentation and executable examples. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_TYPED_CLI_DOCUMENTATION = {
  "defaultLevel": "warning",
  "summary": "Declare Node CLI arguments with a typed parsing contract.",
  "rationale": "Raw positional and option lookups scatter a command contract across individual uses. A declared parser makes positional meanings, options and defaults visible together.",
  "remediation": "Use the existing citty library policy or an adequate schema-declaring native parser. Preserve positional meanings, option aliases, defaults and exit behavior.",
  "category": "maintainability",
  "limitations": [
    "Checks source-proven process.argv user-argument indexes and at/includes/indexOf option lookups, including node:process value imports, stable local aliases and nonnegative slice offsets. Executable/script path indexes and opaque forwarding are allowed.",
    "Direct parse/safeParse argument sinks and their Async variants (including JSON transport and opaque schema objects) abstain as a parsing-ownership boundary, including nullish/empty fallback expressions. This does not certify actual typing or validation. Data-flow through stored argument aliases and arbitrary parser functions is not inferred; script payload validation remains a separate coverage gap.",
    "Does not infer CLI contracts through arbitrary functions, dynamic indexes, destructuring or imported wrapper returns. Source-visible namespace mutation, escaped process namespaces, eval, shadowed imports and generated sources abstain. No automatic CLI rewrite."
  ],
  "examples": [
    {
      "id": "declared-contract",
      "title": "Preserve the declared boundary",
      "outcome": "no-match",
      "files": [
        {
          "path": "app.ts",
          "source": "import { defineCommand, runMain } from 'citty'; runMain(defineCommand({ args: { service: { type: 'positional', required: true } }, run({ args }) { deploy(args.service); } }));"
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
          "source": "deploy(process.argv[2]);"
        }
      ],
      "focusPath": "app.ts",
      "expectedCount": 1,
      "public": true
    }
  ]
} as const satisfies RuleDocumentation;
