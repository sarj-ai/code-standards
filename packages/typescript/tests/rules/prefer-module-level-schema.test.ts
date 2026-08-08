import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferModuleLevelSchemaDocumentation } from "../../src/rules/prefer-module-level-schema.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

const IMPORT = 'import { z } from "zod";\n';

ruleTester.run("prefer-module-level-schema", rule, {
  valid: [
    { name: "public no-match example", filename: preferModuleLevelSchemaDocumentation.examples[0].focusPath, code: preferModuleLevelSchemaDocumentation.examples[0].files[0].source },
    // The target state — declared once, at module scope.
    {
      code: `${IMPORT}const ZBody = z.object({ id: z.string(), name: z.string() });\nexport function handle(raw: unknown) { return ZBody.parse(raw); }`,
    },

    // Not inside a function at all: an argument to a module-level call.
    {
      code: `${IMPORT}export const route = router.input(z.object({ id: z.string(), name: z.string() }));`,
    },

    // NOT FLAGGED — closes over a parameter. This is a schema FACTORY, and
    // hoisting it would be a compile error.
    {
      code: `${IMPORT}export function envelope(inner: z.ZodTypeAny) { return z.object({ data: inner, ok: z.boolean() }); }`,
    },

    // NOT FLAGGED — closes over a local binding declared in the same function.
    {
      code: `${IMPORT}export function build() { const inner = z.string(); return z.object({ a: inner, b: z.number() }); }`,
    },

    // NOT FLAGGED — closes over a TYPE PARAMETER. A type reference pins the
    // schema to the function just as firmly as a value reference does.
    {
      code: `${IMPORT}export function make<T extends string>() { return z.object({ v: z.custom<T>(), w: z.string() }); }`,
    },

    // NOT FLAGGED — closes over a type declared inside the function body.
    {
      code: `${IMPORT}export function make2() { type Inner = { b: 2 }; return z.object({ v: z.custom<Inner>(), w: z.string() }); }`,
    },

    // NOT FLAGGED — the `.superRefine` callback reads a component prop, so the
    // schema is pinned to the component even though the `z.object` subtree
    // alone closes over nothing. Measured FP, from documenso.
    {
      code: `${IMPORT}export const Dialog = ({ required }: { required: boolean }) => { const S = z.object({ a: z.string(), b: z.string() }).superRefine((data, ctx) => { if (!required) { ctx.addIssue({ code: "custom" }); } }); return S; };`,
    },

    // NOT FLAGGED — a builder method takes a local value.
    {
      code: `${IMPORT}export function build(fallback: string) { return z.object({ a: z.string(), b: z.string() }).catch({ a: fallback, b: fallback }); }`,
    },

    // NOT FLAGGED — reads `this`. The free-variable check alone would call this
    // hoistable; it is not, because `this.base` has no meaning at module scope.
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

    // NOT FLAGGED — already memoized, so the construction cost is paid once.
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

    // NOT FLAGGED — `z.lazy` exists so the schema is NOT built eagerly. The
    // callback is a function, but reporting inside it would be exactly wrong.
    {
      code: `${IMPORT}export function build() { return z.lazy(() => z.object({ a: z.string(), b: z.string() })); }`,
    },


    // NOT FLAGGED — below `minProperties`. An empty placeholder shape, and a
    // one-key schema written inline at its only use, read better where they are.
    // The one-key case needs NO option: the default is 2, which is what the
    // fileoverview always claimed and what `minProperties: 1` never delivered.
    { code: `${IMPORT}export function handle(raw: unknown) { return z.object({}).parse(raw); }` },
    {
      code: `${IMPORT}export function handle(raw: unknown) { return z.object({ reason: z.string() }).parse(raw); }`,
    },

    // NOT FLAGGED — the message is rendered by an i18n macro, so the schema is
    // built AFTER locale activation on purpose. Hoisting freezes every message
    // in the boot locale: a behaviour change, not a refactor. From
    // `twenty/…/useTwoFactorAuthenticationForm.ts:7`.
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

    // NOT FLAGGED — a FRAGMENT of a schema that cannot itself move. The sibling
    // keys of the `.extend({…})` close over a parameter, so the object literal
    // around this `z.union` is rebuilt per call whatever happens to the union.
    // From `astro/…/core/config/schemas/relative.ts:31`.
    {
      code: `${IMPORT}import { Base } from "./base.js";\nexport function make(root: string) { return Base.extend({ compressHTML: z.union([z.boolean(), z.literal("jsx")]), root: z.string().transform((v) => v + root) }); }`,
    },
    // Same, one level deeper: the fragment sits inside a `z.preprocess` inside
    // the unhoistable `.extend`. From the same file, line 102.
    {
      code: `${IMPORT}import { Base } from "./base.js";\nexport function make(root: string) { return Base.extend({ server: z.preprocess((v) => v, z.object({ host: z.string(), port: z.number() })), root: z.string().transform((v) => v + root) }); }`,
    },

    // NOT FLAGGED — `z.array` / `z.enum` are outside the default factory list.
    {
      code: `${IMPORT}export function build() { return z.array(z.string()); }`,
    },
    {
      code: `${IMPORT}export function build() { return z.enum(["a", "b"]); }`,
    },

    // NOT FLAGGED — the import is not Zod, so `z` is somebody else's namespace.
    {
      code: 'import { z } from "./my-helpers.js";\nexport function build() { return z.object({ a: 1, b: 2 }); }',
    },

    // NOT FLAGGED — test file, where a fixture schema belongs beside its assertion.
    {
      code: `${IMPORT}it("parses", () => { const S = z.object({ a: z.string(), b: z.string() }); expect(S).toBeDefined(); });`,
      filename: "/repo/src/thing.test.ts",
    },

    // NOT FLAGGED — generated file.
    {
      code: `${IMPORT}export function build() { return z.object({ a: z.string(), b: z.string() }); }`,
      filename: "/repo/src/generated/sdk.gen.ts",
    },
  ],

  invalid: [
    { name: "public match example", filename: preferModuleLevelSchemaDocumentation.examples[1].focusPath, code: preferModuleLevelSchemaDocumentation.examples[1].files[0].source, errors: [{ messageId: "hoistSchema" }] },
    // The core case: rebuilt on every call, uses nothing the function owns.
    {
      name: "reports a function-local object schema without autofixing",
      code: `${IMPORT}export function handle(raw: unknown) { const ZBody = z.object({ id: z.string(), name: z.string() }); return ZBody.parse(raw); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "handle" } }],
      output: null,
    },

    // Inline at the parse site. `.parse(raw)` CONSUMES a parameter, but the
    // schema in front of it is still hoistable, so the chain walk stops there.
    // Inline at the parse site — still one allocation per call.
    {
      code: `${IMPORT}export function handle(raw: unknown) { return z.object({ id: z.string(), name: z.string() }).parse(raw); }`,
      errors: [{ messageId: "hoistSchema" }],
    },

    // A getter: rebuilt on every property READ, which is the worst of the set.
    {
      code: `${IMPORT}export class Client { get shape() { return z.object({ a: z.string(), b: z.string() }); } }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "shape" } }],
    },

    // A React component: a fresh schema — and a fresh reference — every render.
    {
      code: `${IMPORT}export const Form = () => { const schema = z.object({ a: z.string(), b: z.string() }); return schema; };`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "Form" } }],
    },

    // Nested functions: the hoist target is module scope, so the OUTERMOST
    // function is what the schema must be free of — and it is.
    {
      code: `${IMPORT}export function outer() { return () => z.object({ a: z.string(), b: z.string() }); }`,
      errors: [{ messageId: "hoistSchema" }],
    },

    // Namespace import — `zod/v4` is still Zod.
    {
      code: 'import * as z4 from "zod/v4";\nexport function build() { return z4.strictObject({ a: z4.string(), b: z4.string() }); }',
      errors: [{ messageId: "hoistSchema", data: { factory: "z.strictObject", owner: "build" } }],
    },

    // Other object-like composites are in the default set too.
    {
      code: `${IMPORT}export function build() { return z.record(z.string(), z.number()); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.record", owner: "build" } }],
    },
    {
      code: `${IMPORT}export function build() { return z.discriminatedUnion("k", [A, B]); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.discriminatedUnion", owner: "build" } }],
    },

    // Nested inside an outer REPORTABLE factory: ONE finding for the whole
    // expression, anchored at the outermost node — not one per `z.object`.
    {
      code: `${IMPORT}export function build() { return z.union([z.object({ a: z.string() }), z.object({ b: z.string() })]); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.union", owner: "build" } }],
    },

    // `z.array` is not reportable by default, so the finding falls through to
    // the `z.object` inside it rather than disappearing. Hoisting that object
    // and writing `z.array(ZItem)` is the fix either way.
    {
      code: `${IMPORT}export function build() { return z.array(z.object({ a: z.string(), b: z.string() })); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "build" } }],
    },
    // Opting `array` in anchors the report at the outermost node instead.
    {
      code: `${IMPORT}export function build() { return z.array(z.object({ a: z.string(), b: z.string() })); }`,
      options: [{ factories: ["array", "object"] }],
      errors: [{ messageId: "hoistSchema", data: { factory: "z.array", owner: "build" } }],
    },

    // A schema in a NON-Zod options object still fires. Walking out of a shape
    // literal is only valid when the call around it is a Zod construct;
    // `tool({ inputSchema, execute })` is not, and treating the whole options
    // object as the schema would inherit `execute`'s free variables. Five real
    // findings in `novu/libs/agent-evals/src/core/tools.ts` turn on this.
    {
      code: `${IMPORT}declare function tool(o: unknown): unknown;\nexport function make(ctx: { log: (s: string) => void }) { return tool({ inputSchema: z.object({ a: z.string(), b: z.string() }), execute: () => ctx.log("x") }); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "make" } }],
    },

    // A refinement callback's OWN parameters are part of the schema and travel
    // with it. Treating them as bindings the function owns made every refined
    // schema unreportable — `astro/packages/integrations/sitemap/src/
    // validate-options.ts:9` and two Medusa `booleanString()` factories were
    // silently lost to it.
    {
      code: `${IMPORT}export function build() { return z.object({ a: z.string(), b: z.string() }).refine((options) => options.a !== options.b); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "build" } }],
    },
    {
      code: `${IMPORT}export const booleanString = () => z.union([z.boolean(), z.string()]).transform((value) => value.toString());`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.union", owner: "booleanString" } }],
    },

    // An enclosing Zod construct that IS hoistable does not suppress: the whole
    // `z.preprocess(…)` moves, and the report anchors the part that can be named.
    {
      code: `${IMPORT}export function build() { return z.preprocess((v) => v, z.array(z.object({ a: z.string(), b: z.string() }))).catch([]); }`,
      errors: [{ messageId: "hoistSchema", data: { factory: "z.object", owner: "build" } }],
    },

    // `minProperties: 1` opts the one-key inline schema back in.
    {
      code: `${IMPORT}export function handle(raw: unknown) { return z.object({ reason: z.string() }).parse(raw); }`,
      options: [{ minProperties: 1 }],
      errors: [{ messageId: "hoistSchema" }],
    },

    // Test files fire when the exemption is switched off.
    {
      code: `${IMPORT}it("parses", () => { const S = z.object({ a: z.string(), b: z.string() }); return S; });`,
      filename: "/repo/src/thing.test.ts",
      options: [{ ignoreTestFiles: false }],
      errors: [{ messageId: "hoistSchema" }],
    },
  ],
});
