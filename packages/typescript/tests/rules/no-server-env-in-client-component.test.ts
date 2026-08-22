import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-server-env-in-client-component.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
});

RULE_TESTER.run("no-server-env-in-client-component", rule, {
  valid: [
    "import { SERVER_SETTINGS } from '@/server-settings';",
    "'use client'; import { CLIENT_SETTINGS } from '@/client-settings';",
    "'use client'; import type { ServerSettings } from '@/server-settings';",
    "'use client'; import { type ServerSettings } from '@/server-settings';",
    "'use client'; import { settings } from '@/settings';",
    "'use client'; import serverSettings from '@/server-settings.test-helper';",
  ],
  invalid: [
    {
      code: "'use client'; import { SERVER_SETTINGS } from '@/server-settings';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      code: "'use client'; import serverEnv from '../config/server-env.ts';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      code: "'use strict'; 'use client'; import { env } from './server-env';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
  ],
});
