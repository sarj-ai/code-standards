// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_SILENT_PROMISE_CATCH_DOCUMENTATION } from "../../src/rules/no-silent-promise-catch.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-silent-promise-catch", rule, {
  valid: [
    {"name": "native shared decoding boundary: mutated-global-String-operation", "code": "String=()=> 'send';const key=String('catch');const api={send(fn){return fn(new Error('custom'));}};const result=api[key](()=>null);\nconsole.log(JSON.stringify({result,key}));"},
    {"name": "native shared decoding boundary: cross-scope-body-alias", "code": "const initial='json';const key=initial;async function f(){const initial='send';const response={json(){return Promise.reject(new SyntaxError('empty'));},send(){return Promise.reject(new Error('lost'));}};return await response[key]().catch(()=>null);}const result=await f();console.log(JSON.stringify({result,key}));"},
    {"name": "native shared decoding boundary: unknown-primitive-expression-key", "code": "const key='ca'+'tch';const result=await Promise.reject(new Error('lost'))[key](()=>null);console.log(JSON.stringify({result,key}));"},
    {"name": "native computed branch: native-fetch-empty-body", "code": "const key='json';const result=await new Response('')[key]().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: recovering-then-key", "code": "const key='then';const result=await Promise.reject(new Error('lost')).catch(()=>null)[key](value=>({recovered:value}));\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: zod-computed-catch", "code": "import { z } from 'zod';const method='catch';const schema=z.string();const result=schema[method](()=> 'default').parse(null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: zod-computed-factory", "code": "import { z } from 'zod';const factory='string';const method='catch';const result=z[factory]()[method](()=> 'default').parse(null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: zod-computed-local-schema-alias", "code": "import { z } from 'zod';const factory='string';const method='catch';const schema=z[factory]();const alias=schema;const result=alias[method](()=> 'default').parse(null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: custom-catch-consumes-error", "code": "const key='catch';const api={catch(handler){return handler(new Error('handled'));}};const result=api[key](error=>error.message);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: mutated-operation-then", "code": "let key='catch';key='then';const result=await Promise.resolve('ok')[key](value=>value);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: symbol-operation-data-key", "code": "const key=Symbol('catch');const api={[key](handler){return handler(new Error('ignored'));}};const result=api[key](()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "native computed branch: computed-web-share-cancellation", "code": "const key='share';const navigator={share(){return Promise.reject(new Error('cancelled'));}};const result=await navigator[key]().catch(()=>false);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: body-parse-dot", "code": "const response={json(){return Promise.reject(new SyntaxError('empty'));}};const result=await response.json().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: body-parse-literal", "code": "const response={json(){return Promise.reject(new SyntaxError('empty'));}};const result=await response['json']().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: body-parse-const", "code": "const key='json';const response={json(){return Promise.reject(new SyntaxError('empty'));}};const result=await response[key]().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: body-parse-alias", "code": "const key='json';const alias=key;const response={json(){return Promise.reject(new SyntaxError('empty'));}};const result=await response[alias]().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: teardown-dot", "code": "const resource={cancel(){return Promise.reject(new Error('already closed'));}};const result=await resource.cancel().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: teardown-const", "code": "const key='cancel';const resource={cancel(){return Promise.reject(new Error('already closed'));}};const result=await resource[key]().catch(()=>null);\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: silent-catch-shadow", "code": "const key='catch';async function f(){const key='then';return Promise.resolve('ok')[key](value=>value);}const result=await f();\nconsole.log(JSON.stringify({result}));"},
    {"name": "stable computed native: reported-catch-const", "code": "const key='catch';const result=await Promise.reject(new Error('lost'))[key](error=>({handled:error.message}));\nconsole.log(JSON.stringify({result}));"},
    { name: "accepts static bracket JSON parsing with an optional-body fallback", code: "client['json']()['catch'](() => null);" },
    { name: "preserves Zod fallback factories", code: "import { z } from 'zod'; z.string().catch(() => '');" },
    { name: "preserves a bound Zod schema fallback", code: "import { z as schema } from 'zod'; const value = schema.number(); value.catch(() => 0);" },
    { name: "preserves namespace Zod schema fallback", code: "import * as z from 'zod'; z.array(z.string()).catch(() => []);" },
    { name: "accepts the documented reported rejection", code: NO_SILENT_PROMISE_CATCH_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "allows a cancelled optional web-share action",
      code: "await navigator.share(data).catch(() => false);",
    },
    {
      name: "allows integration scripts to probe expected failures",
      filename: "/repo/scripts/probe.mjs",
      code: "await probe().catch(() => null);",
    },
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
    // Unknown method access is out of scope.
    {
      code: "p[method](() => null);",
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
    {"name": "native shared decoding boundary: mutated-global-String-body", "code": "String=()=> 'send';const key=String('json');const response={send(){return Promise.reject(new Error('lost'));}};const result=await response[key]().catch(()=>null);\nconsole.log(JSON.stringify({result,key}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "native shared decoding boundary: shadowed-local-String-retained", "code": "const String=()=> 'send';const key=String('json');const response={send(){return Promise.reject(new Error('lost'));}};const result=await response[key]().catch(()=>null);\nconsole.log(JSON.stringify({result,key}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "native shared decoding boundary: cross-scope-alias-lost-rejection", "code": "const initial='send';const key=initial;async function f(){const initial='json';const response={send(){return Promise.reject(new Error('lost'));},json(){return Promise.reject(new SyntaxError('empty'));}};return await response[key]().catch(()=>null);}const result=await f();console.log(JSON.stringify({result,key}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "native computed branch: custom-catch-silent-retained-name-policy", "code": "const key='catch';const api={catch(handler){return handler(new Error('ignored'));}};const result=api[key](()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "native computed branch: readonly-let-static-catch", "code": "let key='catch';const result=await Promise.reject(new Error('lost'))[key](()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "native computed branch: parameter-shadow-body-method", "code": "const key='json';async function f(key){const response={send(){return Promise.reject(new Error('lost'));}};return await response[key]().catch(()=>null);}const result=await f('send');\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: body-parse-mutated", "code": "let key='json';key='send';const response={send(){return Promise.reject(new Error('lost'));}};const result=await response[key]().catch(()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: body-parse-shadow", "code": "const key='json';async function f(){const key='send';const response={send(){return Promise.reject(new Error('lost'));}};return await response[key]().catch(()=>null);}const result=await f();\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: body-parse-symbol", "code": "const key=Symbol('json');const response={[key](){return Promise.reject(new Error('lost'));}};const result=await response[key]().catch(()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: silent-catch-dot", "code": "const result=await Promise.reject(new Error('lost')).catch(()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: silent-catch-literal", "code": "const result=await Promise.reject(new Error('lost'))['catch'](()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: silent-catch-const", "code": "const key='catch';const result=await Promise.reject(new Error('lost'))[key](()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: silent-catch-alias", "code": "const key='catch';const alias=key;const result=await Promise.reject(new Error('lost'))[alias](()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    {"name": "stable computed native: silent-second-then-const", "code": "const key='then';const result=await Promise.reject(new Error('lost'))[key](value=>value,()=>null);\nconsole.log(JSON.stringify({result}));", "errors": [{"messageId": "silentCatch"}]},
    { name: "does not exempt a shadowed Zod name", code: "import { z } from 'zod'; function run(z) { z.string().catch(() => null); }", errors: [{ messageId: "silentCatch" }] },
    { name: "does not exempt Zod async parsing rejections", code: "import { z } from 'zod'; z.string().parseAsync(input).catch(() => null);", errors: [{ messageId: "silentCatch" }] },
    { name: "does not exempt reassigned schema bindings", code: "import { z } from 'zod'; let value = z.string(); value = load(); value.catch(() => null);", errors: [{ messageId: "silentCatch" }] },
    { name: "reports the documented silent rejection", code: NO_SILENT_PROMISE_CATCH_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "silentCatch" }] },
    {
      name: "reports a silent catch followed only by finally",
      code: "load().catch(() => null).finally(cleanup);",
      errors: [{ messageId: "silentCatch" }],
    },
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
      name: "reports an unknown call without evidence of body parsing",
      code: "client[method]().catch(() => null);",
      errors: [{ messageId: "silentCatch" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "silent-rejection-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/load.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/load.ts",
        "source": "load()[\"catch\"](() => null);"
      }
    ]
  },
  {
    "id": "silent-rejection-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/load.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/load.ts",
        "source": "load()[auditDynamicMember](() => null);"
      }
    ]
  }
] } });
});
