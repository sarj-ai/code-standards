// vitest: shared-module-graph
import rule from "../../src/rules/no-credential-in-browser-storage.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("no-credential-in-browser-storage", rule, {
  valid: [
    "localStorage.setItem('theme', 'dark');",
    "localStorage.setItem('nextPageToken', cursor);",
    "sessionStorage.setItem('tokenExpiresAt', String(expiry));",
    "localStorage.setItem('passwordHint', hint);",
    "sessionStorage.setItem('tokenCount', String(count));",
    "localStorage.setItem(key, token);",
    "const localStorage = new Map(); localStorage.setItem('token', value);",
    "document.cookie = `locale=${locale}; path=/`;",
    "cache.setItem('accessToken', token);",
    "const page = localStorage.getItem('authToken');",
    "localStorage.removeItem('authToken');",
    "localStorage.lastVisited = Date.now();",
    { name: "server-cookie", filename: "src/theme.ts", code: "localStorage.setItem(\"sidebar-collapsed\", \"true\");\n" },
  ],
  invalid: [
    {
      code: "window.localStorage.setItem('authToken', token);",
      errors: [{ messageId: "noCredentialInBrowserStorage", data: { key: "authToken" } }],
    },
    {
      code: "const KEY = 'refresh_token'; sessionStorage.setItem(KEY, token);",
      errors: [{ messageId: "noCredentialInBrowserStorage", data: { key: "refresh_token" } }],
    },
    {
      code: "localStorage.apiKey = key;",
      errors: [{ messageId: "noCredentialInBrowserStorage", data: { key: "apiKey" } }],
    },
    {
      code: "localStorage['jwt'] = value;",
      errors: [{ messageId: "noCredentialInBrowserStorage", data: { key: "jwt" } }],
    },
    {
      code: "document.cookie = `session_token=${token}; path=/`;",
      errors: [{ messageId: "noCredentialInBrowserStorage", data: { key: "session_token" } }],
    },
    {
      code: "window.document.cookie = 'password=' + value;",
      errors: [{ messageId: "noCredentialInBrowserStorage", data: { key: "password" } }],
    },
    {
      name: "token-in-local-storage",
      filename: "src/session.ts",
      code: "export function remember(token: string): void {\n  localStorage.setItem(\"accessToken\", token);\n}\n",
      errors: [{ messageId: "noCredentialInBrowserStorage" }],
    },
  ],
});
