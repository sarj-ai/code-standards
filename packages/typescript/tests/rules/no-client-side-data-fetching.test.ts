// vitest: shared-module-graph
import rule from "../../src/rules/no-client-side-data-fetching.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-client-side-data-fetching", rule, {
  valid: [

    { code: "async function load() { return await fetch('/x'); }" },

    {
      code: "import { loadUsers } from './users-client';\nexport default async function Users() { const users = await loadUsers(); return <pre>{JSON.stringify(users)}</pre>; }",
      filename: "app/users/page.tsx",
      languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
    },

    {
      code: "import { useState } from 'react'; const [x, setX] = useState(0);",
    },

    {
      code: "useEffect(() => { fetch('/api/x', { method: 'POST' }); }, []);",
    },
    {
      code: "useEffect(() => { axios({ url: '/api/x', method: 'POST' }); }, []);",
    },
    {
      code: "useEffect(() => { ky('/api/x', { method: 'PUT' }); }, []);",
    },

    {
      code: "useEffect(() => { const instance = axios.create({ baseURL: '/' }); }, []);",
    },
    {
      code: "useEffect(() => { axios.defaults.timeout = 5000; }, []);",
    },
    {
      code: "useEffect(() => { axios.interceptors.request.use((c) => c); }, []);",
    },
    {
      code: "useEffect(() => { ky.create({ prefixUrl: '/api' }); superagent.agent(); }, []);",
    },

    {
      code: "useEffect(() => { fetch('/api/track/page-view'); }, []);",
    },
    {
      code: "useEffect(() => { fetch('/api/log'); }, []);",
    },
    {
      code: "useEffect(() => { fetch('/api/analytics.js'); }, []);",
    },
    {
      code: "useEffect(() => { fetch('/telemetry'); fetch('/ping'); fetch('/beacon'); fetch('/metrics'); fetch('/event'); }, []);",
    },
  ],
  invalid: [
    {
      code: "'use client'; import { useEffect } from 'react';\nexport function Users() { useEffect(() => { fetch('/api/users'); }, []); return null; }",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { fetch('/api/users', { method: 'GET' }); }, []);",
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
    {
      code: "useEffect(() => { ky('/x'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { ky.get('/x'); superagent.head('/x'); }, []);",
      errors: [
        { messageId: "noClientFetch" },
        { messageId: "noClientFetch" },
      ],
    },

    {
      code: "useLayoutEffect(() => { fetch('/api/users'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },

    {
      code: "React.useEffect(() => { fetch('/api/users'); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "React.useLayoutEffect(() => { axios.post('/api/x', {}); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },

    {
      code: "useEffect(() => { axios.patch('/api/users/1', { name: 'x' }); }, []);",
      errors: [{ messageId: "noClientFetch" }],
    },
    {
      code: "useEffect(() => { axios.put('/x'); axios.delete('/x'); axios.request('/x'); axios.head('/x'); axios.options('/x'); }, []);",
      errors: Array.from({ length: 5 }, () => ({
        messageId: "noClientFetch" as const,
      })),
    },

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
