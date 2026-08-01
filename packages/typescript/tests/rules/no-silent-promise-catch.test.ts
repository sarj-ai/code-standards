import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-silent-promise-catch.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-silent-promise-catch", rule, {
  valid: [
    // FP guard, corpus: query/packages/query-core/src/thenable.ts:54 — the
    // suppression is documented, which is the thing the rule asks for.
    { code: "thenable.catch(() => {\n  // prevent unhandled rejection errors\n});" },
    // Corpus: react-router/packages/react-router/lib/router/router.ts:6052 — the
    // explanation sits on the line above the statement.
    {
      code: [
        "// Prevent unhandled rejection errors - handled inside of `callLoadOrAction`",
        "lazyRoutePromise.catch(() => {});",
      ].join("\n"),
    },
    // Corpus: react-router/packages/react-router/lib/components.tsx:1664 — trailing.
    { code: "promise = Promise.reject().catch(() => {}); // Avoid unhandled rejection warnings" },
    // FP guard, corpus: react-router/packages/react-router/lib/rsc/html-stream/server.ts:80
    // — a teardown call rejects when the resource is already gone.
    { code: "async function f(reader, reason) { await reader.cancel(reason).catch(() => {}); }" },
    { code: "socket.close().catch(() => null);" },
    // FP guard, corpus: react-router/integration/helpers/playwright-fixture.ts:318
    // — the next link consumes the fallback, so it is a recovery step.
    { code: "evaluate.catch(() => null).then(() => { done(); });" },
    // Handler that logs is fine.
    {
      code: "p.catch((err) => logger.error({ err }, 'lookup failed'));",
    },
    // Handler that references its error parameter.
    {
      code: "p.catch((err) => fallbackFor(err));",
    },
    // Rethrow.
    {
      code: "p.catch((err) => { throw new WrappedError(err); });",
    },
    // Non-function handler (named recovery fn) — out of scope.
    {
      code: "p.catch(handleError);",
    },
    // try/catch `catch` clauses are covered by the try/catch-form rules.
    {
      code: "try { await p; } catch { /* handled elsewhere */ }",
    },
    // Computed .catch access is out of scope.
    {
      code: "p['catch'](() => null);",
    },
    // Two-argument .then-style catch is not the .catch(fn) form.
    {
      code: "p.catch(() => null, extra);",
    },
    // Returning a computed fallback (does something).
    {
      code: "p.catch(() => computeFallback());",
    },
    // Body-parse-fallback idiom: parse failure is not the handled signal.
    {
      code: "const body = await res.json().catch(() => ({}));",
    },
    {
      code: "const text = await res.text().catch(() => '');",
    },
    // Test files are exempt (unhandled-rejection suppression is routine there).
    {
      code: "p.catch(() => undefined);",
      filename: "/repo/src/components/widget.test.tsx",
    },
    {
      code: "p.catch(() => null);",
      filename: "/repo/src/__tests__/helpers.ts",
    },
    // Non-empty object fallback carries information — out of scope.
    {
      code: "p.catch(() => ({ ok: false }));",
    },
    // An eslint-disable-next-line above the call suppresses cleanly even when
    // the handler sits on a later line than the call (the report is anchored
    // on the CallExpression, not the handler).
    {
      code: [
        "// eslint-disable-next-line @rule-tester/no-silent-promise-catch -- deliberate",
        "p.catch(",
        "  () => null,",
        ");",
      ].join("\n"),
    },
  ],
  invalid: [
    // The comment guard ignores tooling directives — they are not an explanation.
    {
      code: [
        "// @ts-expect-error legacy",
        "load().catch(() => null);",
      ].join("\n"),
      errors: [{ messageId: "silentCatch" }],
    },
    // An undocumented swallow on a non-teardown call still fires.
    {
      code: "fetchUser(id).catch(() => null);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => null);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => undefined);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => void 0);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => 0);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => '');",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => false);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => ({}));",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(() => []);",
      errors: [{ messageId: "silentCatch" }],
    },
    // Empty blocks.
    {
      code: "p.catch(() => {});",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(function () {});",
      errors: [{ messageId: "silentCatch" }],
    },
    // Block that only returns a sentinel.
    {
      code: "p.catch(() => { return null; });",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      code: "p.catch(function (err) { return undefined; });",
      errors: [{ messageId: "silentCatch" }],
    },
    // Unused error parameter does not excuse a silent body.
    {
      code: "p.catch((err) => null);",
      errors: [{ messageId: "silentCatch" }],
    },
    // Cast around the sentinel is still silent.
    {
      code: "p.catch(() => null as User | null);",
      errors: [{ messageId: "silentCatch" }],
    },
    // Chained form.
    {
      code: "fetchUser(id).then(render).catch(() => null);",
      errors: [{ messageId: "silentCatch" }],
    },
    // Multi-line: the report anchors at the call, not the handler line.
    {
      code: ["p.catch(", "  () => null,", ");"].join("\n"),
      errors: [{ messageId: "silentCatch", line: 1 }],
    },
    // json/text with arguments or as a plain lookup is NOT the parse idiom.
    {
      code: "client.json(payload).catch(() => null);",
      errors: [{ messageId: "silentCatch" }],
    },
  ],
});
