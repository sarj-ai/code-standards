import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferServerActionsDocumentation } from "../../src/rules/prefer-server-actions.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

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
      name: "flags member mutations whose payload is an identifier",
      code: "api.post('/api/orders', order);",
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
