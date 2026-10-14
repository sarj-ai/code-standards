// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/no-credential-in-browser-storage.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

RULE_TESTER.run("no-credential-in-browser-storage", rule, {
  valid: [
    "localStorage.setItem('theme', 'dark');",
    "sessionStorage.setItem('tokenCount', String(count));",
    "localStorage.setItem(key, token);",
    "const localStorage = new Map(); localStorage.setItem('token', value);",
    "document.cookie = `locale=${locale}; path=/`;",
    "cache.setItem('accessToken', token);",
    "const page = localStorage.getItem('authToken');",
    "localStorage.removeItem('authToken');",
    "localStorage.lastVisited = Date.now();",
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
  ],
});
