import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION } from "../../src/rules/no-return-disposed-resource.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

TESTER.run("no-return-disposed-resource", rule, {
  valid: [
    { name: "documented independent snapshot", code: NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION.examples[1].files[0].source },
    { name: "ordinary owned return", code: "function create() { const handle = acquire(); return handle; }" },
    { name: "awaited fixture callback keeps scope open", code: "async function fixture({}, use) { await using handle = acquire(); await use(handle); }" },
    { name: "nested callback retains outer lifetime", code: "function fixture() { using handle = acquire(); function read() { return handle; } return consume(read); }" },
    { name: "returned independent snapshot alias", code: "function fixture() { using handle = acquire(); const value = handle.snapshot(); return value; }" },
    { name: "using resource shadow is distinct", code: "function fixture() { using handle = acquire(); function create(handle) { return handle; } return create; }" },
    { name: "generated resource preserves generator ownership", filename: "/repo/src/generated/client.ts", code: "function client() { using handle = acquire(); return handle; }" },
  ],
  invalid: [
    { name: "documented disposed return", code: NO_RETURN_DISPOSED_RESOURCE_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "disposedReturn" }] },
    { name: "async resource return", code: "async function client() { await using handle = acquire(); return handle; }", errors: [{ messageId: "disposedReturn" }] },
    { name: "constant alias cannot transfer disposal ownership", code: "function client() { using handle = acquire(); const value = handle; return value; }", errors: [{ messageId: "disposedReturn" }] },
    { name: "wrapped return retains lifetime", code: "function client() { using handle = acquire(); return (handle as Client); }", errors: [{ messageId: "disposedReturn" }] },
  ],
});
