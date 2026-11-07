// vitest: shared-module-graph
import rule from "../../src/rules/no-return-disposed-resource.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

TESTER.run("no-return-disposed-resource", rule, {
  valid: [
    { name: "documented independent snapshot", code: "function client() { using handle = acquire(); return handle.snapshot(); }" },
    { name: "ordinary owned return", code: "function create() { const handle = acquire(); return handle; }" },
    { name: "awaited fixture callback keeps scope open", code: "async function fixture({}, use) { await using handle = acquire(); await use(handle); }" },
    { name: "nested callback retains outer lifetime", code: "function fixture() { using handle = acquire(); function read() { return handle; } return consume(read); }" },
    { name: "returned independent snapshot alias", code: "function fixture() { using handle = acquire(); const value = handle.snapshot(); return value; }" },
    { name: "using resource shadow is distinct", code: "function fixture() { using handle = acquire(); function create(handle) { return handle; } return create; }" },
    { name: "generated resource preserves generator ownership", filename: "/repo/src/generated/client.ts", code: "function client() { using handle = acquire(); return handle; }" },
  ],
  invalid: [
    { name: "documented disposed return", code: "function client() { using handle = acquire(); return handle; }", errors: [{ messageId: "disposedReturn" }] },
    { name: "async resource return", code: "async function client() { await using handle = acquire(); return handle; }", errors: [{ messageId: "disposedReturn" }] },
    { name: "constant alias cannot transfer disposal ownership", code: "function client() { using handle = acquire(); const value = handle; return value; }", errors: [{ messageId: "disposedReturn" }] },
    { name: "wrapped return retains lifetime", code: "function client() { using handle = acquire(); return (handle as Client); }", errors: [{ messageId: "disposedReturn" }] },
  ],
});
