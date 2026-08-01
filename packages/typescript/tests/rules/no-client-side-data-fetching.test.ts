import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-client-side-data-fetching.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("no-client-side-data-fetching", rule, {
  valid: [
    // fetch outside useEffect is fine.
    { code: "async function load() { return await fetch('/x'); }" },
    // useEffect with no fetch is fine.
    {
      code: "import { useEffect } from 'react'; useEffect(() => { console.log('x'); }, []);",
    },
    // useState only.
    {
      code: "import { useState } from 'react'; const [x, setX] = useState(0);",
    },
    // Non-GET fetch (e.g. POST analytics) is allowed.
    {
      code: "useEffect(() => { fetch('/api/x', { method: 'POST' }); }, []);",
    },
    // axios.create / axios.defaults are NOT HTTP method calls — must not flag.
    {
      code: "useEffect(() => { const instance = axios.create({ baseURL: '/' }); }, []);",
    },
    {
      code: "useEffect(() => { axios.defaults.timeout = 5000; }, []);",
    },
    {
      code: "useEffect(() => { axios.interceptors.request.use((c) => c); }, []);",
    },
    // Analytics endpoints are exempt (whole segment matches).
    {
      code: "useEffect(() => { fetch('/api/track/page-view'); }, []);",
    },
    {
      code: "useEffect(() => { fetch('/api/log'); }, []);",
    },
    {
      code: "useEffect(() => { fetch('/api/analytics.js'); }, []);",
    },
  ],
  invalid: [
    {
      code: "useEffect(() => { fetch('/api/users'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { axios.get('/api/users'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(async () => { const r = await fetch('/api/x'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(function () { axios('/x'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    // useLayoutEffect must also be caught.
    {
      code: "useLayoutEffect(() => { fetch('/api/users'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    // React.useEffect / React.useLayoutEffect namespaced form.
    {
      code: "React.useEffect(() => { fetch('/api/users'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "React.useLayoutEffect(() => { axios.post('/api/x', {}); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    // axios non-get methods are still data calls.
    {
      code: "useEffect(() => { axios.patch('/api/users/1', { name: 'x' }); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    // Substring-vs-segment regressions: these must NOT be exempted as analytics.
    {
      code: "useEffect(() => { fetch('/api/login'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { fetch('/api/events'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { fetch('/catalog'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { fetch('/blog'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { fetch('/api/shipping'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
  ],
});
