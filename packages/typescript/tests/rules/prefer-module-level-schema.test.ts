// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION } from "../../src/rules/prefer-module-level-schema.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

const IMPORT = 'import { z } from "zod";\n';

RULE_TESTER.run("prefer-module-level-schema", rule, {
  valid: [
    { name: "does not assume every Zod namespace function constructs a schema", code: `${IMPORT}function build() { return z.object({id: z.string(), name: z.string({error: z.getErrorMap()})}); }` },
    { name: "preserves eager time-dependent defaults", code: `${IMPORT}function build() { return z.object({id: z.string(), created: z.number().default(Date.now())}); }` },
    { name: "preserves namespace construction-time calls", code: `${IMPORT}import * as policy from './policy'; function build() { return z.object({id: z.string(), count: z.number().max(policy.currentLimit())}); }` },
    { name: "preserves construction-time allocation", code: `${IMPORT}function build() { return z.object({id: z.string(), created: z.date().default(new Date())}); }` },
    { name: "public no-match example", filename: PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION.examples[0].focusPath, code: PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION.examples[0].files[0].source },

    {
      code: `${IMPORT}const ZBody = z.object({ id: z.string(), name: z.string() });\nexport function handle(raw: unknown) { return ZBody.parse(raw); }`,
    },


    {
      code: `${IMPORT}export const route = router.input(z.object({ id: z.string(), name: z.string() }));`,
    },



    {
      code: `${IMPORT}export function envelope(inner: z.ZodTypeAny) { return z.object({ data: inner, ok: z.boolean() }); }`,
    },


    {
      code: `${IMPORT}export function build() { const inner = z.string(); return z.object({ a: inner, b: z.number() }); }`,
    },



    {
      code: `${IMPORT}export function make<T extends string>() { return z.object({ v: z.custom<T>(), w: z.string() }); }`,
    },


    {
      code: `${IMPORT}export function make2() { type Inner = { b: 2 }; return z.object({ v: z.custom<Inner>(), w: z.string() }); }`,
    },




    {
      code: `${IMPORT}export const Dialog = ({ required }: { required: boolean }) => { const S = z.object({ a: z.string(), b: z.string() }).superRefine((data, ctx) => { if (!required) { ctx.addIssue({ code: "custom" }); } }); return S; };`,
    },


    {
      code: `${IMPORT}export function build(fallback: string) { return z.object({ a: z.string(), b: z.string() }).catch({ a: fallback, b: fallback }); }`,
    },



    {
      name: "allows schemas that read this",
      code: `${IMPORT}export class C { private readonly base = z.string(); get s() { return z.object({ a: this.base, b: z.string() }); } }`,
    },

    {
      name: "allows schemas that read super",
      code: `${IMPORT}class Base { protected static base = z.string(); }\nexport class C extends Base { static build() { return z.object({ a: super.base, b: z.string() }); } }`,
    },

    {
      name: "allows schemas that read arguments",
      code: `${IMPORT}export function build() { return z.object({ a: z.literal(arguments.length), b: z.string() }); }`,
    },
    {
      name: "allows schemas that read a mutable module binding",
      code: `${IMPORT}let required = true;\nexport function setRequired(value: boolean) { required = value; }\nexport function build() { return z.object({ a: z.string(), b: z.string() }).refine(() => required); }`,
    },
    {
      name: "allows schemas whose imported factory may be dynamic or effectful",
      code: `${IMPORT}import { allowedNow } from "./policy.js";
             export function build() { return z.object({ role: z.enum(allowedNow()), name: z.string() }); }`,
    },


    {
      name: "allows schemas wrapped in useMemo",
      code: `${IMPORT}import { useMemo } from "react";\nexport function useForm() { return useMemo(() => z.object({ a: z.string(), b: z.string() }), []); }`,
    },

    {
      name: "allows schemas wrapped in memo",
      code: `${IMPORT}import { memo } from "./memo.js";\nexport function build() { return memo(() => z.object({ a: z.string(), b: z.string() })); }`,
    },
    {
      name: "allows schemas wrapped in once",
      code: `${IMPORT}import { once } from "./memo.js";\nexport function build() { return once(() => z.object({ a: z.string(), b: z.string() })); }`,
    },
    {
      name: "allows configured project-specific memo wrappers",
      code: `${IMPORT}import { useStableFactory } from "./memo.js";\nexport function useForm() { return useStableFactory(() => z.object({ a: z.string(), b: z.string() })); }`,
      options: [{ memoCallees: ["useStableFactory"] }],
    },



    {
      code: `${IMPORT}export function build() { return z.lazy(() => z.object({ a: z.string(), b: z.string() })); }`,
    },






    { code: `${IMPORT}export function handle(raw: unknown) { return z.object({}).parse(raw); }` },
    {
      code: `${IMPORT}export function handle(raw: unknown) { return z.object({ reason: z.string() }).parse(raw); }`,
    },





    {
      name: "allows schemas with tagged localized text",
      code: `${IMPORT}import { t } from "@lingui/core/macro";\nconst make = () => z.object({ otp: z.string().length(6, t\`OTP must be exactly 6 digits\`), pin: z.string() });\nexport default make;`,
    },
    {
      name: "allows schemas with $t localized text",
      code: `${IMPORT}import { $t } from "i18n";\nexport const make = () => z.object({ a: z.string($t("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with defineMessage localized text",
      code: `${IMPORT}import { defineMessage } from "i18n";\nexport const make = () => z.object({ a: z.string(defineMessage("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with gettext localized text",
      code: `${IMPORT}import { gettext } from "i18n";\nexport const make = () => z.object({ a: z.string(gettext("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with msg localized text",
      code: `${IMPORT}import { msg } from "i18n";\nexport const make = () => z.object({ a: z.string(msg("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with ngettext localized text",
      code: `${IMPORT}import { ngettext } from "i18n";\nexport const make = () => z.object({ a: z.string(ngettext("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with t localized text",
      code: `${IMPORT}import { t } from "i18n";\nexport const make = () => z.object({ a: z.string(t("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with translate localized text",
      code: `${IMPORT}import { translate } from "i18n";\nexport const make = () => z.object({ a: z.string(translate("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with $i18n localized text",
      code: `${IMPORT}import { $i18n } from "i18n";\nexport const make = () => z.object({ a: z.string($i18n.formatMessage("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with i18n localized text",
      code: `${IMPORT}import { i18n } from "i18n";\nexport const make = () => z.object({ a: z.string(i18n.formatMessage("a.label")), b: z.string() });`,
    },
    {
      name: "allows schemas with intl localized text",
      code: `${IMPORT}import { intl } from "i18n";\nexport const make = () => z.object({ a: z.string(intl.formatMessage("a.label")), b: z.string() });`,
    },





    {
      code: `${IMPORT}import { Base } from "./base.js";\nexport function make(root: string) { return Base.extend({ compressHTML: z.union([z.boolean(), z.literal("jsx")]), root: z.string().transform((v) => v + root) }); }`,
    },


    {
      code: `${IMPORT}import { Base } from "./base.js";\nexport function make(root: string) { return Base.extend({ server: z.preprocess((v) => v, z.object({ host: z.string(), port: z.number() })), root: z.string().transform((v) => v + root) }); }`,
    },


    {
      code: `${IMPORT}export function build() { return z.array(z.string()); }`,
    },
    {
      code: `${IMPORT}export function build() { return z.enum(["a", "b"]); }`,
    },


    {
      code: 'import { z } from "./my-helpers.js";\nexport function build() { return z.object({ a: 1, b: 2 }); }',
    },


    {
      code: `${IMPORT}it("parses", () => { const S = z.object({ a: z.string(), b: z.string() }); expect(S).toBeDefined(); });`,
      filename: "/repo/src/thing.test.ts",
    },


    {
      code: `${IMPORT}export function build() { return z.object({ a: z.string(), b: z.string() }); }`,
      filename: "/repo/src/generated/sdk.gen.ts",
    },
  ],

  invalid: [
    { name: "retains deferred time-dependent defaults", code: `${IMPORT}function build() { return z.object({id: z.string(), created: z.number().default(() => Date.now())}); }`, errors: [{ messageId: "hoistSchema" }] },
    { name: "public match example", filename: PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION.examples[1].focusPath, code: PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "hoistSchema" }] },

    {
      name: "reports a function-local object schema without autofixing",
      code: `${IMPORT}export function handle(raw: unknown) { const ZBody = z.object({ id: z.string(), name: z.string() }); return ZBody.parse(raw); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "handle" } }],
      output: null,
    },




    {
      code: `${IMPORT}export function handle(raw: unknown) { return z.object({ id: z.string(), name: z.string() }).parse(raw); }`,
      errors: [{ messageId: "hoistSchema" }],
    },


    {
      code: `${IMPORT}export class Client { get shape() { return z.object({ a: z.string(), b: z.string() }); } }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "shape" } }],
    },


    {
      code: `${IMPORT}export const Form = () => { const schema = z.object({ a: z.string(), b: z.string() }); return schema; };`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "Form" } }],
    },



    {
      code: `${IMPORT}export function outer() { return () => z.object({ a: z.string(), b: z.string() }); }`,
      errors: [{ messageId: "hoistSchema" }],
    },


    {
      code: 'import * as z4 from "zod/v4";\nexport function build() { return z4.strictObject({ a: z4.string(), b: z4.string() }); }',
      errors: [{ messageId: "hoistSchema", data: { factory: "z.strictObject", owner: "build" } }],
    },


    {
      code: `${IMPORT}export function build() { return z.record(z.string(), z.number()); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.record", owner: "build" } }],
    },
    {
      code: `${IMPORT}export function build() { return z.discriminatedUnion("k", [A, B]); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.discriminatedUnion", owner: "build" } }],
    },



    {
      code: `${IMPORT}export function build() { return z.union([z.object({ a: z.string() }), z.object({ b: z.string() })]); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.union", owner: "build" } }],
    },




    {
      code: `${IMPORT}export function build() { return z.array(z.object({ a: z.string(), b: z.string() })); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "build" } }],
    },

    {
      code: `${IMPORT}export function build() { return z.array(z.object({ a: z.string(), b: z.string() })); }`,
      options: [{ factories: ["array", "object"] }],
      errors: [{ messageId: "hoistSchema", data: { factory: "z.array", owner: "build" } }],
    },






    {
      code: `${IMPORT}declare function tool(o: unknown): unknown;\nexport function make(ctx: { log: (s: string) => void }) { return tool({ inputSchema: z.object({ a: z.string(), b: z.string() }), execute: () => ctx.log("x") }); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "make" } }],
    },






    {
      code: `${IMPORT}export function build() { return z.object({ a: z.string(), b: z.string() }).refine((options) => options.a !== options.b); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "build" } }],
    },
    {
      code: `${IMPORT}export const booleanString = () => z.union([z.boolean(), z.string()]).transform((value) => value.toString());`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.union", owner: "booleanString" } }],
    },



    {
      code: `${IMPORT}export function build() { return z.preprocess((v) => v, z.array(z.object({ a: z.string(), b: z.string() }))).catch([]); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "build" } }],
    },


    {
      code: `${IMPORT}export function handle(raw: unknown) { return z.object({ reason: z.string() }).parse(raw); }`,
      options: [{ minProperties: 1 }],
      errors: [{ messageId: "hoistSchema" }],
    },


    {
      code: `${IMPORT}it("parses", () => { const S = z.object({ a: z.string(), b: z.string() }); return S; });`,
      filename: "/repo/src/thing.test.ts",
      options: [{ ignoreTestFiles: false }],
      errors: [{ messageId: "hoistSchema" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "local-schema-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/handler.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/handler.ts",
        "source": "import { z } from 'zod'; export function handle(raw: unknown) { const ZBody = z[\"object\"]({ id: z[\"string\"](), name: z[\"string\"]() }); return ZBody[\"parse\"](raw); }"
      }
    ]
  },
  {
    "id": "local-schema-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/handler.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/handler.ts",
        "source": "import { z } from 'zod'; export function handle(raw: unknown) { const ZBody = z[auditDynamicMember]({ id: z[auditDynamicMember](), name: z[auditDynamicMember]() }); return ZBody[auditDynamicMember](raw); }"
      }
    ]
  }
] } });
});
