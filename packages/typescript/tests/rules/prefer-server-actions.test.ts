import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferServerActionsDocumentation } from "../../src/rules/prefer-server-actions.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();
const NEXT_CLIENT_MODULE = "/repo/app/ui/actions.tsx";
const USE_CLIENT = '"use client"; ';

ruleTester.run("prefer-server-actions", rule, {
  valid: [
    { name: "public no-match example", filename: preferServerActionsDocumentation.examples[0].focusPath, code: preferServerActionsDocumentation.examples[0].files[0].source },
    {
      name: "ignores Angular modules because they cannot use Server Actions",
      code: [
        'import { inject } from "@angular/core";',
        'import { HttpClient } from "@angular/common/http";',
        'const http = inject(HttpClient);',
        'export const addTask = (task) => http.post("/api/tasks", task);',
      ].join("\n"),
      filename: "/repo/src/app/services/tasks.service.ts",
    },
    {
      name: "ignores Vue modules because they cannot use Server Actions",
      code: 'import { ref } from "vue"; api.post("/api/tasks");',
    },
    {
      name: "ignores Svelte modules because they cannot use Server Actions",
      code: 'import { onMount } from "svelte"; api.post("/api/tasks");',
    },
    {
      name: "ignores Solid modules because they cannot use Server Actions",
      code: 'import { createSignal } from "solid-js"; api.post("/api/tasks");',
    },
    {
      name: "ignores Nest modules because they cannot use Server Actions",
      code: 'import { Injectable } from "@nestjs/common"; api.post("/api/tasks");',
    },
    {
      name: "ignores Ember modules because they cannot use Server Actions",
      code: 'import Service from "@ember/service"; api.post("/api/tasks");',
    },
    {
      name: "ignores RxJS modules because they cannot use Server Actions",
      code: 'import { of } from "rxjs"; api.post("/api/tasks");',
    },
    {
      name: "ignores non-React modules regardless of import position",
      code: 'api.post("/api/tasks"); import { ref } from "vue";',
    },
    {
      name: "ignores React Vite modules without positive Next.js evidence",
      code: 'import React from "react"; api.post("/api/tasks");',
      filename: "/repo/src/components/actions.tsx",
    },
    {
      name: "ignores Vite pages paths without a use-client directive",
      code: 'import React from "react"; api.post("/api/tasks");',
      filename: "/repo/src/pages/actions.tsx",
    },
    {
      name: "still allows GET requests in a Next.js module",
      code: `${USE_CLIENT}fetch('/api/users');`,
      filename: NEXT_CLIENT_MODULE,
    },
    {
      name: "still allows external mutations in a Next.js module",
      code: `${USE_CLIENT}fetch('https://api.example.com/users', { method: 'POST' });`,
      filename: NEXT_CLIENT_MODULE,
    },
    {
      name: "ignores codemod fixtures because they are not running code",
      code: "fetch('/api/todos', { method: 'POST' });",
      filename: "/repo/src/v5/__testfixtures__/bug-reports.input.tsx",
    },
    {
      name: "ignores test files",
      code: "fetch('/api/todos', { method: 'POST' });",
      filename: "/repo/src/todos.test.ts",
    },
    {
      name: "ignores scripts",
      code: "fetch('/api/todos', { method: 'POST' });",
      filename: "/repo/scripts/seed.ts",
    },
    {
      name: "ignores App Router route handlers",
      code: "fetch('/api/todos', { method: 'POST' });",
      filename: "/repo/app/api/todos/route.ts",
    },
    {
      name: "ignores Pages Router API handlers",
      code: "fetch('/api/todos', { method: 'POST' });",
      filename: "/repo/pages/api/todos.ts",
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
    {
      name: "ignores Express route definitions with inline arrow handlers",
      code: "router.post('/api/users', (req, res) => res.json({}));",
    },
    {
      name: "ignores Express route definitions with inline function handlers",
      code: "router.delete('/api/users/:id', function (req, res) {});",
    },
    {
      name: "ignores Express route definitions with variable handlers",
      code: [
        "const handler = (req, res) => res.json({});",
        "router.post('/api/users', handler);",
      ].join("\n"),
    },
    {
      name: "ignores Express route definitions with declared handlers",
      code: [
        "function handler(req, res) { res.json({}); }",
        "router.post('/api/users', handler);",
      ].join("\n"),
    },
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
    { name: "public match example", filename: preferServerActionsDocumentation.examples[1].focusPath, code: preferServerActionsDocumentation.examples[1].files[0].source, errors: [{ messageId: "preferServerAction" }] },
    // A React page still fires.
    {
      code: `${USE_CLIENT}const r = await fetch('/api/data', { method: 'POST', body });`,
      filename: "/repo/src/pages/index.tsx",
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: `${USE_CLIENT}fetch('/api/users', { method: 'POST' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: `${USE_CLIENT}fetch('/api/users/1', { method: 'DELETE' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      // Method casing is normalized.
      code: `${USE_CLIENT}fetch('/api/users/1', { method: 'put' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: `${USE_CLIENT}fetch(\`/api/literal\`, { method: 'PATCH' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      // Dynamic template literal with `/api/` prefix.
      code: `${USE_CLIENT}fetch(\`/api/\${id}\`, { method: 'POST' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    // Branch 2: axios/custom-wrapper member call (no handler arg).
    {
      code: `${USE_CLIENT}api.post('/api/orders', { total: 1 });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      name: "flags member mutations whose payload is an identifier",
      code: `${USE_CLIENT}api.post('/api/orders', order);`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: `${USE_CLIENT}axios.put('/api/orders/1');`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    // Branch 3: direct axios config object.
    {
      code: `${USE_CLIENT}axios({ method: 'post', url: '/api/orders' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      // request({ method, url }) direct-config form.
      code: `${USE_CLIENT}request({ method: 'DELETE', url: '/api/orders/1' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    // resolveNode: url and method resolved through variables.
    {
      code: `${USE_CLIENT}const url = '/api/orders'; fetch(url, { method: 'POST' });`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      code: `${USE_CLIENT}const cfg = { method: 'post', url: '/api/orders' }; axios(cfg);`,
      filename: NEXT_CLIENT_MODULE,
      errors: [{ messageId: "preferServerAction" }],
    },
    {
      name: "reports with an explicit Next import outside app and pages trees",
      code: 'import { useRouter } from "next/navigation"; fetch("/api/items", { method: "POST" });',
      filename: "/repo/src/components/actions.tsx",
      errors: [{ messageId: "preferServerAction" }],
    },
  ],
});
