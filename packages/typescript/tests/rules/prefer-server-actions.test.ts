import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-server-actions.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("prefer-server-actions", rule, {
  valid: [
    // FP guard, corpus: query/examples/angular/auto-refetching/src/app/services/tasks.service.ts:38
    // — Server Actions do not exist outside React/Next.
    {
      code: [
        'import { inject } from "@angular/core";',
        'import { HttpClient } from "@angular/common/http";',
        'const http = inject(HttpClient);',
        'export const addTask = (task) => http.post("/api/tasks", task);',
      ].join("\n"),
      filename: "/repo/src/app/services/tasks.service.ts",
    },
    // FP guard: jscodeshift input/output fixtures are text, not running code.
    {
      code: "fetch('/api/todos', { method: 'POST' });",
      filename: "/repo/src/v5/__testfixtures__/bug-reports.input.tsx",
    },
    // GET is fine — only mutations are flagged.
    { code: "fetch('/api/users');" },
    { code: "fetch('/api/users', { method: 'GET' });" },
    // External URLs are fine.
    { code: "fetch('https://api.example.com/users', { method: 'POST' });" },
    // Mutation against a non-/api URL is fine.
    { code: "fetch('/other/users', { method: 'POST' });" },
    // axios member GET is not a mutation.
    { code: "api.get('/api/users');" },
    // Express-style route DEFINITION (inline handler arg) is not a client
    // mutation. Detection is limited to inline function args (see rule docs).
    { code: "router.post('/api/users', (req, res) => res.json({}));" },
    { code: "router.delete('/api/users/:id', function (req, res) {});" },
    // Direct axios config with GET is fine.
    { code: "axios({ method: 'get', url: '/api/users' });" },
    // Direct axios config against an external URL is fine.
    {
      code: "axios({ method: 'post', url: 'https://x.com/api/users' });",
    },
    // resolveNode: variable resolves to a GET method — not a mutation.
    {
      code: "const method = 'GET'; fetch('/api/users', { method });",
    },
  ],
  invalid: [
    // A React page still fires.
    {
      code: "const r = await fetch('/api/data', { method: 'POST', body });",
      filename: "/repo/src/pages/index.tsx",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: "fetch('/api/users', { method: 'POST' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: "fetch('/api/users/1', { method: 'DELETE' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      // Method casing is normalized.
      code: "fetch('/api/users/1', { method: 'put' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: "fetch(`/api/literal`, { method: 'PATCH' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      // Dynamic template literal with `/api/` prefix.
      code: "fetch(`/api/${id}`, { method: 'POST' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    // Branch 2: axios/custom-wrapper member call (no handler arg).
    {
      code: "api.post('/api/orders', { total: 1 });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: "axios.put('/api/orders/1');",
      errors: [{ messageId: "preferServerAction" }],
    },
    // Branch 3: direct axios config object.
    {
      code: "axios({ method: 'post', url: '/api/orders' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      // request({ method, url }) direct-config form.
      code: "request({ method: 'DELETE', url: '/api/orders/1' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    // resolveNode: url and method resolved through variables.
    {
      code: "const url = '/api/orders'; fetch(url, { method: 'POST' });",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: "const cfg = { method: 'post', url: '/api/orders' }; axios(cfg);",
      errors: [{ messageId: "preferServerAction" }],
    },
  ],
});
