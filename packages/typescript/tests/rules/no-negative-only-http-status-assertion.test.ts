// vitest: shared-module-graph
import rule from "../../src/rules/no-negative-only-http-status-assertion.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();
const HEADER = "import {test, expect} from 'vitest'; ";
const FILE = "/repo/src/api.test.ts";

TESTER.run("no-negative-only-http-status-assertion", rule, {
  valid: [
    { name: "documented intended status", filename: FILE, code: "import {test,expect} from 'vitest'; test('reads', async () => { const response = await fetch('/versions'); expect(response.status).toBe(200); });" },
    { name: "negative status supplements exact same response", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); expect(response.status).not.toBe(500); expect(response.status).toBe(200); });" },
    { name: "positive status follows stable response alias", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); const alias = response; expect(alias.status).not.toBe(500); expect(response.status).toBe(200); });" },
    { name: "custom Response is not native HTTP", filename: FILE, code: HEADER + "import { Response } from './model.js'; test('reads', () => { const response = new Response(); expect(response.status).not.toBe(500); });" },
    { name: "intentional nonserver exclusion is outside policy", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); expect(response.status).not.toBe(404); });" },
    { name: "arbitrary status model is not assumed to be HTTP", filename: FILE, code: HEADER + "test('reads', () => { const response = inspect(); expect(response.status).not.toBe(500); });" },
    { name: "custom fetch binding retains its contract", filename: FILE, code: HEADER + "test('reads', async () => { const fetch = inspect; const response = await fetch('/'); expect(response.status).not.toBe(500); });" },
    { name: "nested callback is not the test body", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); const check = () => expect(response.status).not.toBe(500); });" },
    { name: "helper function is not a test", filename: FILE, code: HEADER + "async function check() { const response = await fetch('/'); expect(response.status).not.toBe(500); }" },
    { name: "production code retains separate policy", filename: "/repo/src/api.ts", code: HEADER + "test('reads', async () => { const response = await fetch('/'); expect(response.status).not.toBe(500); });" },
  ],
  invalid: [
    { name: "documented missing expected status", filename: FILE, code: "import {test,expect} from 'vitest'; test('reads', async () => { const response = await fetch('/versions'); expect(response.status).not.toBe(500); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "server error family boundary", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); expect(response.status).toBeLessThan(500); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "other response positive does not cover this response", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); const other = await fetch('/other'); expect(response.status).not.toBe(503); expect(other.status).toBe(200); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "conditional exact assertion cannot cover all paths", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); expect(response.status).not.toBe(500); if (ready) expect(response.status).toBe(200); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "runtime imported fetch alias", filename: FILE, code: HEADER + "import {fetch as send} from 'undici'; test('reads', async () => { const response = await send('/'); expect(response.status).not.toEqual(500); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "native Response constructor", filename: FILE, code: HEADER + "test('reads', () => { const response = new Response(); expect(response.status).not.toBe(500); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "stable response alias", filename: FILE, code: HEADER + "test('reads', async () => { const response = await fetch('/'); const alias = response; expect(alias.status).not.toBe(500); });", errors: [{ messageId: "expectedStatus" }] },
    { name: "native member fetch", filename: FILE, code: HEADER + "test('reads', async () => { const response = await globalThis.fetch('/'); expect(response.status).not.toBe(500); });", errors: [{ messageId: "expectedStatus" }] },
  ],
});
