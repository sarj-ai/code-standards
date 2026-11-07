// vitest: shared-module-graph
import rule from "../../src/rules/no-bespoke-api-case-conversion.js";
import { ruleTester } from "./_tester.js";

const NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Review direct snake_case/camelCase mirror mappings on explicitly API-typed adapter values.",
  rationale:
    "Duplicating wire-name translation can drift from an API client contract. When the SDK owns application-facing names, centralizing conversion avoids maintaining another mirror by hand.",
  remediation:
    "Move wire-name ownership and case conversion into the generated SDK/model layer; keep application adapters on the generated typed surface.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Only adapter/adapters files and receivers explicitly annotated with a scope-resolved type imported from an API/client/SDK/contract/generated module are checked. Unrelated imports, local type shadows, reassigned receivers and inferred receiver types are excluded.",
    "Only object properties that directly translate the same identifier between snake_case and lowerCamelCase are reported.",
    "Quoted/computed protocol keys, generated/vendor code, tests, fixtures, and indirect conversions are intentionally excluded.",
  ],
  examples: [
    {
      id: "generated-client-surface",
      title: "Use the generated client's application-facing property names",
      outcome: "no-match",
      files: [
        {
          path: "src/user-adapter.ts",
          source:
            "import type { User } from './generated-client';\nconst toUser = (raw: User) => ({ displayName: raw.displayName });",
        },
      ],
      focusPath: "src/user-adapter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "bespoke-wire-case-conversion",
      title: "Do not reproduce SDK case conversion in an application adapter",
      outcome: "match",
      files: [
        {
          path: "src/user-adapter.ts",
          source:
            "import type { User } from './api-contract';\nconst toUser = (raw: User) => ({ displayName: raw.display_name });",
        },
      ],
      focusPath: "src/user-adapter.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const;

const RULE_TESTER = ruleTester();
const ERROR = { messageId: "noBespokeApiCaseConversion" as const };
const adapter = (body: string): string =>
  `import type { Contract } from "./api-contract";\n${body}`;

RULE_TESTER.run("no-bespoke-api-case-conversion", rule, {
  valid: [
    { name: "unrelated API import does not establish receiver provenance", filename: "/repo/src/user-adapter.ts", code: adapter("const raw = { display_name: 'local' }; const value = { displayName: raw.display_name };") },
    { name: "local type shadow does not inherit imported contract", filename: "/repo/src/user-adapter.ts", code: adapter("function read() { type Contract = { display_name: string }; const raw: Contract = { display_name: 'local' }; return { displayName: raw.display_name }; }") },
    {
      name: "accepts the documented generated-client surface",
      filename: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[0].focusPath,
      code: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "ignores ordinary domain files",
      filename: "/repo/src/user.ts",
      code: adapter("const user = { displayName: raw.display_name };"),
    },
    {
      name: "requires a proven API boundary import",
      filename: "/repo/src/user-adapter.ts",
      code: 'import type { User } from "./domain"; const user = { displayName: raw.display_name };',
    },
    {
      name: "ignores unrelated names instead of guessing intent",
      filename: "/repo/src/user-adapter.ts",
      code: adapter("const user = { displayName: raw.legal_name };"),
    },
    {
      name: "preserves quoted protocol keys",
      filename: "/repo/src/user-adapter.ts",
      code: adapter('const wire = { "display_name": user.displayName };'),
    },
    {
      name: "preserves computed protocol keys",
      filename: "/repo/src/user-adapter.ts",
      code: adapter("const wire = { [wireName]: user.displayName };"),
    },
    {
      name: "ignores generated adapters",
      filename: "/repo/src/generated/user-adapter.ts",
      code: adapter("const user = { displayName: raw.display_name };"),
    },
    {
      name: "ignores adapter tests and fixtures",
      filename: "/repo/src/fixtures/user-adapter.ts",
      code: adapter("const user = { displayName: raw.display_name };"),
    },
    {
      name: "does not confuse strings and comments for object properties",
      filename: "/repo/src/user-adapter.ts",
      code: adapter('const note = "displayName: raw.display_name"; // displayName: raw.display_name'),
    },
  ],
  invalid: [
    {
      name: "reports the documented read conversion",
      filename: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[1].focusPath,
      code: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[1].files[0].source,
      errors: [ERROR],
    },
    {
      name: "reports a write conversion",
      filename: "/repo/src/integration-adapters.ts",
      code: adapter("declare const draft: Contract; const wire = { owner_organization_id: draft.ownerOrganizationId };"),
      errors: [ERROR],
    },
    {
      name: "reports each independently maintained mapping",
      filename: "/repo/src/api.adapter.ts",
      code: adapter("declare const raw: Contract; const value = { isSecret: raw.is_secret, updatedAt: raw.updated_at };"),
      errors: [ERROR, ERROR],
    },
    {
      name: "recognizes nested member reads",
      filename: "/repo/src/user-adapter.ts",
      code: adapter("declare const raw: Contract; const value = { retryIntervalSeconds: raw.settings.retry_interval_seconds };"),
      errors: [ERROR],
    },
  ],
});

RULE_TESTER.run("preserves outcomes for static member access and unknown member keys", rule, {
  valid: [
    {"name": "bespoke-wire-case-conversion-dynamic-member: Unknown member access does not establish API identity", "filename": "src/user-adapter.ts", "code": "import type { User } from './api-contract';\nexport const toUser = (raw: User) => ({ displayName: raw[auditDynamicMember] });"},
  ],
  invalid: [
    {"name": "bespoke-wire-case-conversion-static-member: Static member access preserves the rule outcome", "filename": "src/user-adapter.ts", "code": "import type { User } from './api-contract';\nexport const toUser = (raw: User) => ({ displayName: raw[\"display_name\"] });", "errors": 1},
  ],
});
