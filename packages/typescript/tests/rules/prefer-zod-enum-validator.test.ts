// vitest: shared-module-graph
import { expect, it } from "vitest";

import rule from "../../src/rules/prefer-zod-enum-validator.js";
import { ruleTester } from "./_tester.js";

const PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Express closed string validators with a reusable Zod enum schema.",
  rationale: "Handwritten membership branches and parallel literal types repeat the accepted values and can drift. A named enum schema supplies validation and its inferred TypeScript union.",
  remediation: "Declare a module-level Schema = z.enum([…]), derive its type with z.infer<typeof Schema>, and use Schema.parse(value) or Schema.safeParse(value).success. Preserve any intentional error, fallback, or protocol behavior when migrating.",
  category: "maintainability",
  autofix: "none",
  requiresTypeInformation: false,
  references: ["https://zod.dev/api#enums", "https://zod.dev/basics#inferring-types"],
  limitations: [
    "Inspects synchronous single-parameter functions explicitly accepting unknown or string, whose complete body is a strict string-equality disjunction, an equivalent reject conjunction, or a closed switch that returns the input and throws otherwise. Boolean membership functions are also inspected.",
    "At least two distinct static string values are required. Membership collections, additional guards, coercion, normalization, transformed returns, methods, contextual parameter types, and multi-parameter functions are outside this bounded detector.",
    "Migration is manual because Zod errors, initialization and constructor hooks are observable; retain intentional failure behavior. A predicate must not be replaced with a throwing parse call. Test and generated files are excluded.",
  ],
  examples: [
    { id: "schema-validator", title: "Define validation and the type from one enum", outcome: "no-match", files: [{ path: "src/status.ts", source: "import { z } from 'zod'; const StatusSchema = z.enum(['ran', 'failed']); type Status = z.infer<typeof StatusSchema>; function status(value: unknown): Status { return StatusSchema.parse(value); }" }], focusPath: "src/status.ts", expectedCount: 0, public: true },
    { id: "manual-validator", title: "Replace a closed handwritten string parser", outcome: "match", files: [{ path: "src/status.ts", source: "type Status = 'ran' | 'failed'; function status(value: unknown): Status { if (value === 'ran' || value === 'failed') return value; throw new Error('Invalid status'); }" }], focusPath: "src/status.ts", expectedCount: 1, public: true },
  ],
} as const;

const RULE_TESTER = ruleTester();

RULE_TESTER.run("prefer-zod-enum-validator", rule, {
  valid: [
  {
    "name": "schema-parser",
    "code": "import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); function state(value:unknown){return StateSchema.parse(value);}"
  },
  {
    "name": "schema-predicate",
    "code": "import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); const isState=(value:unknown)=>StateSchema.safeParse(value).success;"
  },
  {
    "name": "single-discriminator",
    "code": "function isRan(value:unknown){return value === 'ran';}"
  },
  {
    "name": "duplicate-one-value",
    "code": "function isRan(value:unknown){return value === 'ran' || value === 'ran';}"
  },
  {
    "name": "loose-equality",
    "code": "function isState(value:unknown){return value == 'ran' || value == 'failed';}"
  },
  {
    "name": "numeric-domain",
    "code": "function isState(value:unknown){return value === 1 || value === 2;}"
  },
  {
    "name": "mixed-domain",
    "code": "function isState(value:unknown){return value === 'ran' || value === 2;}"
  },
  {
    "name": "conjunction-empty-domain",
    "code": "function isState(value:unknown){return value === 'ran' && value === 'failed';}"
  },
  {
    "name": "computed-value",
    "code": "function isState(value:unknown){return value === first || value === second;}"
  },
  {
    "name": "interpolated-template",
    "code": "function isState(value:unknown){return value === `ran${suffix}` || value === 'failed';}"
  },
  {
    "name": "member-discriminator",
    "code": "function isState(value:unknown){return value.kind === 'ran' || value.kind === 'failed';}"
  },
  {
    "name": "two-receivers",
    "code": "function isState(value:unknown){return value === 'ran' || other === 'failed';}"
  },
  {
    "name": "calls-in-condition",
    "code": "function isState(value:unknown){return normalize(value) === 'ran' || normalize(value) === 'failed';}"
  },
  {
    "name": "operational-if",
    "code": "function run(value:unknown){if(value === 'ran' || value === 'failed') dispatch(value);}"
  },
  {
    "name": "transformed-return",
    "code": "function state(value:unknown){if(value === 'ran' || value === 'failed') return value.toUpperCase();throw new Error();}"
  },
  {
    "name": "fallback-parser",
    "code": "function state(value:unknown){if(value === 'ran' || value === 'failed') return value;return 'unknown';}"
  },
  {
    "name": "side-effect",
    "code": "function state(value:unknown){log(value);if(value === 'ran' || value === 'failed') return value;throw new Error();}"
  },
  {
    "name": "branch-side-effect",
    "code": "function state(value:unknown){if(value === 'ran' || value === 'failed'){log(value);return value;}throw new Error();}"
  },
  {
    "name": "additional-guard",
    "code": "function state(value:unknown){if(typeof value==='string' && (value === 'ran' || value === 'failed'))return value;throw new Error();}"
  },
  {
    "name": "multiple-params",
    "code": "function isState(value:unknown, context:string){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "optional-param",
    "code": "function isState(value?:unknown){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "default-param",
    "code": "function isState(value:unknown='ran'){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "destructured-param",
    "code": "function isState({value}:any){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "generic-param",
    "code": "function isState<T>(value:unknown){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "any-param",
    "code": "function isState(value:any){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "contextual-param",
    "code": "const isState: (value:unknown)=>boolean = value => value === 'ran' || value === 'failed';"
  },
  {
    "name": "union-param",
    "code": "function isState(value:string|null){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "async-function",
    "code": "async function isState(value:unknown){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "generator-function",
    "code": "function* isState(value:unknown){return value === 'ran' || value === 'failed';}"
  },
  {
    "name": "class-method",
    "code": "class Validator { isState(value:unknown){return value === 'ran' || value === 'failed';} }"
  },
  {
    "name": "object-method",
    "code": "const validator={isState(value:unknown){return value === 'ran' || value === 'failed';}};"
  },
  {
    "name": "switch-no-default",
    "code": "function state(value:unknown){switch(value){case 'ran':case 'failed':return value;}}"
  },
  {
    "name": "switch-fallthrough-to-default",
    "code": "function state(value:unknown){switch(value){case 'ran':return value;case 'failed':default:throw new Error();}}"
  },
  {
    "name": "switch-transformed",
    "code": "function state(value:unknown){switch(value){case 'ran':case 'failed':return String(value);default:throw new Error();}}"
  },
  {
    "name": "switch-side-effect",
    "code": "function state(value:unknown){switch(value){case 'ran':log(value);return value;case 'failed':return value;default:throw new Error();}}"
  },
  {
    "name": "collection-membership",
    "code": "const isState=(value:string)=>['ran','failed'].includes(value);"
  },
  {
    "name": "type-only-union",
    "code": "type State='ran'|'failed';"
  },
  {
    "name": "inverse-predicate",
    "code": "const isOther=(value:unknown)=>value!=='ran' && value!=='failed';"
  },
  {
    "filename": "src/generated/state.ts",
    "code": "function state(value: unknown): RuleExecutionState { if (value === 'ran' || value === 'skipped' || value === 'untracked' || value === 'failed' || value === 'disabled' || value === 'ignored') return value; throw new Error('Invalid rule execution state'); }",
    "name": "generated-directory"
  },
  {
    "filename": "state.gen.mts",
    "code": "function state(value: unknown): RuleExecutionState { if (value === 'ran' || value === 'skipped' || value === 'untracked' || value === 'failed' || value === 'disabled' || value === 'ignored') return value; throw new Error('Invalid rule execution state'); }",
    "name": "generated-mts"
  },
  {
    "filename": "state.generated.cts",
    "code": "function state(value: unknown): RuleExecutionState { if (value === 'ran' || value === 'skipped' || value === 'untracked' || value === 'failed' || value === 'disabled' || value === 'ignored') return value; throw new Error('Invalid rule execution state'); }",
    "name": "generated-cts"
  },
  {
    "filename": "state.test.ts",
    "code": "function state(value: unknown): RuleExecutionState { if (value === 'ran' || value === 'skipped' || value === 'untracked' || value === 'failed' || value === 'disabled' || value === 'ignored') return value; throw new Error('Invalid rule execution state'); }",
    "name": "test-file"
  },
  {
    "filename": "src/state.ts",
    "code": "// @generated by schema-compiler\nfunction state(value: unknown): RuleExecutionState { if (value === 'ran' || value === 'skipped' || value === 'untracked' || value === 'failed' || value === 'disabled' || value === 'ignored') return value; throw new Error('Invalid rule execution state'); }",
    "name": "generated-header"
  }
],
  invalid: [
  {
    "name": "linked-six-state-parser",
    "code": "function state(value: unknown): RuleExecutionState { if (value === 'ran' || value === 'skipped' || value === 'untracked' || value === 'failed' || value === 'disabled' || value === 'ignored') return value; throw new Error('Invalid rule execution state'); }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "boolean-predicate",
    "code": "function isState(value: unknown): value is State { return value === 'ran' || value === 'failed'; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "boolean-return",
    "code": "function isState(value: string): boolean { return value === 'ran' || value === 'failed'; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "arrow-expression",
    "code": "const isState = (value: unknown) => value === 'ran' || value === 'failed';",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "arrow-block",
    "code": "const isState = (value: unknown) => { return value === 'ran' || value === 'failed'; };",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "function-expression",
    "code": "const isState = function(value: unknown) { return value === 'ran' || value === 'failed'; };",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "parser-if-else",
    "code": "function state(value: unknown) { if(value === 'ran' || value === 'failed') return value; else throw new Error('invalid'); }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "parser-block-branches",
    "code": "function state(value: unknown) { if(value === 'ran' || value === 'failed') { return value; } throw new Error('invalid'); }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "reject-conjunction",
    "code": "function state(value: unknown) { if(value !== 'ran' && value !== 'failed') throw new Error('invalid'); return value; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "reject-if-else",
    "code": "function state(value: unknown) { if(value !== 'ran' && value !== 'failed') { throw new Error('invalid'); } else { return value; } }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "boolean-if",
    "code": "function isState(value: unknown) { if(value === 'ran' || value === 'failed') return true; return false; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "boolean-reject-if",
    "code": "function isState(value: unknown) { if(value !== 'ran' && value !== 'failed') return false; else return true; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "switch-group",
    "code": "function state(value: unknown) { switch(value) { case 'ran': case 'failed': return value; default: throw new Error('invalid'); } }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "switch-separate",
    "code": "function state(value: unknown) { switch(value) { case 'ran': return value; case 'failed': return value; default: throw new Error('invalid'); } }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "reversed-comparisons",
    "code": "function isState(value: unknown) { return 'ran' === value || 'failed' === value; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "static-templates",
    "code": "function isState(value: unknown) { return value === `ran` || value === `failed`; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "erased-wrappers",
    "code": "const isState = (value: unknown) => (value as string) === ('ran' as const) || value === ('failed' satisfies string);",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "exported-parser",
    "code": "export function state(value: string) { if(value === 'ran' || value === 'failed') return value; throw new Error(); }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "three-values",
    "code": "function isState(value: unknown) { return value === 'ran' || (value === 'skipped' || value === 'failed'); }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  },
  {
    "name": "duplicate-plus-distinct",
    "code": "function isState(value: unknown) { return value === 'ran' || value === 'ran' || value === 'failed'; }",
    "output": null,
    "errors": [
      {
        "messageId": "useEnumSchema"
      }
    ]
  }
],
});

RULE_TESTER.run("executes the documented examples", rule, {
  valid: [
    { name: "schema-validator", filename: "src/status.ts", code: PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION.examples[0].files[0].source },
  ],
  invalid: [
    { name: "manual-validator (output: null covers the original verifyAndFix no-fix check)", filename: "src/status.ts", code: PREFER_ZOD_ENUM_VALIDATOR_DOCUMENTATION.examples[1].files[0].source, output: null, errors: [{ messageId: "useEnumSchema" }] },
  ],
});

it("requires review rather than changing observable failure behavior automatically", () => {
  expect(rule.meta?.fixable).toBeUndefined();
  expect(rule.meta?.hasSuggestions).not.toBe(true);
});
