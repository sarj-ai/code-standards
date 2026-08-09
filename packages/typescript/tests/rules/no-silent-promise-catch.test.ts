import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noSilentPromiseCatchDocumentation } from "../../src/rules/no-silent-promise-catch.js";

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
    { name: "accepts the documented reported rejection", code: noSilentPromiseCatchDocumentation.examples[0].files[0].source },
    {
      name: "allows a suppression explained inside the handler",
      code: "thenable.catch(() => {\n  // prevent unhandled rejection errors\n});",
    },
    {
      name: "allows a suppression explained above the statement",
      code: [
        "// Prevent unhandled rejection errors - handled inside of `callLoadOrAction`",
        "lazyRoutePromise.catch(() => {});",
      ].join("\n"),
    },
    {
      name: "allows a suppression explained beside the statement",
      code: "promise = Promise.reject().catch(() => {}); // Avoid unhandled rejection warnings",
    },
    {
      name: "allows silent teardown catches",
      code: [
        "reader.cancel(reason).catch(() => {});",
        "socket.close().catch(() => null);",
        "controller.abort().catch(() => undefined);",
        "resource.destroy().catch(() => false);",
        "handle.dispose().catch(() => 0);",
        "lock.release().catch(() => '');",
        "mutex.unlock().catch(() => ({}));",
        "client.disconnect().catch(() => []);",
      ].join("\n"),
    },
    {
      name: "allows a catch fallback consumed by the next chain link",
      code: "evaluate.catch(() => null).then(() => { done(); });",
    },
    {
      name: "allows a two-argument then fallback consumed by the next chain link",
      code: "evaluate.then(render, () => null).then(() => { done(); });",
    },
    {
      name: "allows a one-argument then",
      code: "evaluate.then(render);",
    },
    {
      name: "allows an explained two-argument then rejection handler",
      code: "// Missing data is expected here\nevaluate.then(render, () => null);",
    },
    // Handler that logs is fine.
    {
      code: "p.catch((err) => logger.error({ err }, 'lookup failed'));",
    },
    // Handler that references its error parameter.
    {
      name: "allows recovery that returns the rejection value",
      code: "p.catch((err) => err);",
    },
    {
      name: "allows a regex fallback because it carries information",
      code: "p.catch(() => /unavailable/);",
    },
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
      name: "allows JSON body parse fallbacks",
      code: "const body = await res.json().catch(() => ({}));",
    },
    {
      name: "allows text body parse fallbacks",
      code: "const text = await res.text().catch(() => '');",
    },
    {
      name: "allows other standard body parse fallbacks",
      code: [
        "await res.blob().catch(() => null);",
        "await res.arrayBuffer().catch(() => null);",
        "await res.formData().catch(() => null);",
        "await res.bytes().catch(() => null);",
      ].join("\n"),
    },
    // Test files are exempt (unhandled-rejection suppression is routine there).
    {
      code: "p.catch(() => undefined);",
      filename: "/repo/src/components/widget.test.tsx",
    },
    {
      name: "allows silent catches in spec files",
      code: "p.catch(() => false);",
      filename: "/repo/src/components/widget.spec.tsx",
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
    { name: "reports the documented silent rejection", code: noSilentPromiseCatchDocumentation.examples[1].files[0].source, errors: [{ messageId: "silentCatch" }] },
    {
      name: "reports a silent rejection handler in the second then argument",
      code: "fetchUser(id).then(render, () => null);",
      errors: [{ messageId: "silentCatch" }],
    },
    {
      name: "reports an empty second-argument then handler",
      code: "fetchUser(id).then(render, () => {});",
      errors: [{ messageId: "silentCatch" }],
    },
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
      name: "reports a bare return that discards the rejection",
      code: "p.catch(() => { return; });",
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
    {
      name: "reports computed JSON calls because they are not recognized body parsing",
      code: "client['json']().catch(() => null);",
      errors: [{ messageId: "silentCatch" }],
    },
  ],
});
