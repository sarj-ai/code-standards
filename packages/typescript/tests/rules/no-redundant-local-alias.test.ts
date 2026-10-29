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
    { code: NO_REDUNDANT_LOCAL_ALIAS_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "redundantAlias" }] },
    { name: "initialized local source", code: "function f() { const value = read(); const accountId = value; return { accountId }; }", errors: [{ messageId: "redundantAlias" }] },
    { name: "same scope within callback", code: "items.map(value => { const accountId = value; return { accountId }; });", errors: [{ messageId: "redundantAlias" }] },
  ],
});
