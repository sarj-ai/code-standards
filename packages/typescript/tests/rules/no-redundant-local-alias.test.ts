// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION } from "../../src/rules/no-redundant-local-alias.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });

TESTER.run("no-redundant-local-alias", rule, {
  valid: [
    { name: "closed primitive explicit property converges", code: "export {}; function f(value: string) { return { accountId: value }; }" },
    NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION.examples[1].files[0].source,
    { name: "annotated domain boundary", code: "function f(value: string) { const accountId: AccountId = value; return { accountId }; }" },
    { name: "multiple meaningful reads", code: "function f(value) { const accountId = value; log(accountId); return { accountId }; }" },
    { name: "snapshot of mutable source", code: "function f(value) { const accountId = value; value = ''; return { accountId }; }" },
    { name: "captured alias", code: "function f(value) { const accountId = value; return () => ({ accountId }); }" },
    { name: "import alias", code: "import { value } from './state.js'; function f() { const accountId = value; return { accountId }; }" },
    { name: "module boundary", code: "const value = ''; const accountId = value; export { accountId };" },
    { name: "destructuring is independent binding", code: "function f(value) { const { accountId } = value; return { accountId }; }" },
    { name: "positional argument", code: "function f(value) { const accountId = value; return send(accountId); }" },
    { name: "different property contract", code: "function f(value) { const accountId = value; return { owner: accountId }; }" },
    { name: "generated artifact", filename: "src/generated/request.ts", code: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION.examples[0].files[0].source },
    { name: "local suppression", code: "function f(value) {\n// eslint-disable-next-line @rule-tester/no-redundant-local-alias -- preserve domain name for migration\nconst accountId = value; return { accountId }; }" },
  ],
  invalid: [
    ...["string", "number", "boolean", "bigint", "symbol"].map(type => ({
      name: `closed ${type} parameter data field`,
      code: `export {}; function f(value: ${type}) { const accountId = value; return { accountId }; }`,
      output: `export {}; function f(value: ${type}) { return { accountId: value }; }`,
      errors: [{ messageId: "redundantAlias" as const }],
    })),
    ...["\n", "\r\n"].map(ending => ({
      name: `closed alias preserves ${JSON.stringify(ending)} boundaries`,
      code: ["export {};", "function f(value: string) {", "  const accountId = value;", "  return { accountId };", "}"].join(ending),
      output: ["export {};", "function f(value: string) {", "", "  return { accountId: value };", "}"].join(ending),
      errors: [{ messageId: "redundantAlias" as const }],
    })),
    { name: "separate CR and LF boundaries cannot become one CRLF", code: "export {}; function f(value: string) {\r  const accountId = value;\n  return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "proto shorthand is an own data field", code: "export {}; function f(value: string) { const __proto__ = value; return { __proto__ }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "global eval withdraws binding custody", code: "export {}; function f(value: string) { const accountId = value; return { accountId }; } eval('f');", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "comment custody remains manual", code: "export {}; function f(value: string) { const accountId = value; /* keep alias */ return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "generic input remains manual", code: "export {}; function f<T extends string>(value: T) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "explicit return contract remains manual", code: "export {}; function f(value: string): {accountId: string} { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "untyped parameter remains manual", code: "export {}; function f(value) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "optional primitive parameter remains manual", code: "export {}; function f(value?: string) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "default parameter remains manual", code: "export {}; function f(value: string = 'initial') { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "public function remains manual", code: "export function f(value: string) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "additional field evaluation remains manual", code: "export {}; function f(value: string) { const accountId = value; return { accountId, observed: read() }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "nested scope can shadow original read site", code: "export {}; function f(value: string) { const accountId = value; { const value = 'other'; return { accountId }; } }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "async function remains manual", code: "export {}; async function f(value: string) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "generator function remains manual", code: "export {}; function* f(value: string) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { name: "overload binding remains manual", code: "export {}; function f(value: string): {accountId: string}; function f(value: string) { const accountId = value; return { accountId }; }", output: null, errors: [{ messageId: "redundantAlias" }] },
    { code: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "redundantAlias" }] },
    { name: "initialized local source", code: "function f() { const value = read(); const accountId = value; return { accountId }; }", errors: [{ messageId: "redundantAlias" }] },
    { name: "same scope within callback", code: "items.map(value => { const accountId = value; return { accountId }; });", errors: [{ messageId: "redundantAlias" }] },
  ],
});
