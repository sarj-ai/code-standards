import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-schema-for-api-payload.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("prefer-schema-for-api-payload", rule, {
  valid: [
    // FP guard, corpus: react-router/integration/request-test.ts:120 — the
    // assertion IS the validation, and the suite is hyphen-named so no path
    // predicate sees it.
    {
      code: "async function t(page) { const loaderData = JSON.parse(await page.innerHTML()); expect(loaderData.method).toEqual('GET'); }",
    },
    // FP guard, corpus: zod/scripts/check-versions.ts:13 — JSON off local disk
    // is not a peer's payload.
    {
      code: "const packageJson = JSON.parse(readFileSync(p, 'utf8')); const v = packageJson.version;",
    },
    {
      code: "async function f(metaPath) { const meta = JSON.parse(await fs.readFile(metaPath, 'utf-8')); return meta.pages; }",
    },
    // Test files: a fixture parses what it just produced.
    {
      code: "async function t(res) { const body = await res.json(); use(body.id); }",
      filename: "/repo/src/__tests__/api.test.ts",
    },
    // Generated API clients own their payload typing at the generator/template boundary.
    {
      code: "async function f(r) { const body = await r.json(); return body.id; }",
      filename: "/repo/src/openapi-gen/client.ts",
    },
    // No json() involved.
    { code: "const x = { foo: 1 }; doStuff(x.foo);" },
    // Parsed through Zod.
    {
      code: "async function f(r) { const data = ZUser.parse(await r.json()); return data.name; }",
    },
    // safeParse.
    {
      code: "async function f(r) { const data = ZUser.safeParse(await r.json()); }",
    },
    // json() result used as opaque value, never field-accessed.
    {
      code: "async function f(r) { const data = await r.json(); return data; }",
    },
    // Direct `.parse()` chained off `.json()` is fine.
    {
      code: "async function f(r) { return ZUser.parse(await r.json()); }",
    },
    // Chained `.safeParse()` directly on the json() result is a validation.
    {
      code: "async function f(r) { return (await r.json()).safeParse(); }",
    },
    // Reassignment untracks: once `data` is reassigned to a parse result, later
    // field access is validated and must not be flagged.
    {
      code: "async function f(r) { let data = await r.json(); data = ZUser.parse(data); return data.name; }",
    },
    // Hand-written type-guard predicate (isX) validates before field access.
    {
      code: "async function f(r) { const body = await r.json(); if (isProtectedResourceMetadata(body)) { return body.resource; } }",
    },
    // Negated guard narrowing in the test position also counts.
    {
      code: "async function f(r) { const body = await r.json(); if (!isValidPayload(body)) throw new Error('x'); return body.id; }",
    },
    // A guard used purely as an `if` test narrows even without the `is` prefix.
    {
      code: "async function f(r) { const body = await r.json(); if (validate(body)) { return body.value; } }",
    },

    // === `JSON.parse` source ==============================================
    // The recommended shape: park it in an `unknown` and validate. Nothing is
    // read off the raw value, so nothing is reported.
    { code: "const raw = JSON.parse(text); const data = Schema.parse(raw); use(data.foo);" },
    { code: "const data = Schema.parse(JSON.parse(text)); use(data.foo);" },
    { code: "const r = Schema.safeParse(JSON.parse(text));" },
    // Parsed but never dereferenced.
    { code: "const raw = JSON.parse(text); send(raw);" },
    // A `.parse()` that is not `JSON.parse` is the validation we are asking for.
    { code: "const data = YAML.parse(text); use(data.foo);" },
    { code: "const data = Schema.parse(text); use(data.foo);" },
    // A hand-written guard narrows just as a schema does.
    { code: "const d = JSON.parse(text); if (isConfig(d)) { use(d.foo); }" },
  ],
  invalid: [
    // The trust boundary still fires: a network payload read outside an assertion.
    {
      code: "async function f(res) { const body = await res.json(); return body.id; }",
      filename: "/repo/src/clients/user-client.ts",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r) { const data = await r.json(); return data.name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r) { const payload = await r.json(); console.log(payload.id); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Destructuring directly off a json() call.
    {
      code: "async function f(r) { const { name } = await r.json(); return name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Array-pattern destructuring directly off a json() call.
    {
      code: "async function f(r) { const [first] = await r.json(); return first; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Array-pattern destructuring off a tracked variable.
    {
      code: "async function f(r) { const data = await r.json(); const [first] = data; return first; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Direct field access on the json() result (no schema parse).
    {
      code: "async function f(r) { return (await r.json()).name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Post-first-access untracking: only the FIRST unvalidated read is flagged.
    {
      code: "async function f(r) { const d = await r.json(); console.log(d.a); console.log(d.b); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // === `JSON.parse` source ==============================================
    // Field read off an unvalidated `JSON.parse` result.
    {
      code: "const data = JSON.parse(text); use(data.foo);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Direct field access on the call result.
    {
      code: "const name = JSON.parse(text).name;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Destructuring the raw result.
    {
      code: "const { foo } = JSON.parse(text);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
  ],
});
