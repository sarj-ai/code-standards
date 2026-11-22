// vitest: shared-module-graph
import rule from "../../src/rules/no-credential-in-browser-storage.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("no-credential-in-browser-storage", rule, {
  valid: [
    "localStorage.setItem('accessToken', '');",
    "localStorage.accessToken = '';",
    "document.cookie = 'accessToken=; Max-Age=0; Path=/';",
    "document.cookie = `accessToken=; Path=${path}`;",
    "document.cookie = 'accessToken=; Path=' + path;",
    "document.cookie = 'accessToken=old; Max-Age=0; Path=/';",
    "document.cookie = 'accessToken=old; max-age=-1; Path=/';",
    "document.cookie = 'accessToken=old; Max-Age=100; Max-Age=0';",
    { name: "invalid later age retains deletion", code: "document.cookie = 'accessToken=old; Max-Age=0; Max-Age=invalid';" },
    { name: "invalid signed age retains deletion", code: "document.cookie = 'accessToken=old; Max-Age=-1; Max-Age=+0';" },
    { name: "ASCII whitespace permits deletion", code: "document.cookie = 'accessToken=old; Max-Age= \\t0\\t ';" },
    { name: "invalid Unicode age retains prior deletion", code: "document.cookie = 'accessToken=old; Max-Age=0; Max-Age=\\u00a00';" },
    { name: "invalid Unicode attribute retains prior deletion", code: "document.cookie = 'accessToken=old; Max-Age=0; \\u00a0Max-Age=100';" },
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
    { name: "Unicode whitespace is a nonempty cookie value", code: "document.cookie = 'accessToken=\\u00a0';", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
    { name: "Unicode whitespace does not normalize an age", code: "document.cookie = 'accessToken=live; Max-Age=\\u00a00';", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
    { name: "Unicode whitespace does not normalize an attribute name", code: "document.cookie = 'accessToken=live; \\u00a0Max-Age=0';", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
    { code: "document.cookie = 'accessToken=live; Max-Age=0; Max-Age=100';", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
    { code: "document.cookie = 'accessToken=' + token;", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
    { code: "document.cookie = 'accessToken=live; Max-Age=0; ' + attributes;", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
    { code: "localStorage.accessToken += '';", errors: [{ messageId: "noCredentialInBrowserStorage" }] },
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
