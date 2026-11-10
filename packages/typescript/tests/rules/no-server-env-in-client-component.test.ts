// vitest: shared-module-graph
import rule from "../../src/rules/no-server-env-in-client-component.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });

RULE_TESTER.run("no-server-env-in-client-component", rule, {
  valid: [
    "import { SERVER_SETTINGS } from '@/server-settings';",
    "'use client'; import { CLIENT_SETTINGS } from '@/client-settings';",
    "'use client'; import type { ServerSettings } from '@/server-settings';",
    "'use client'; import { type ServerSettings } from '@/server-settings';",
    "'use client'; import { settings } from '@/settings';",
    "'use client'; import serverSettings from '@/server-settings.test-helper';",
    {
      name: "ordinary server modules may re-export server settings",
      code: "export { settings } from './server-settings.js';",
    },
    {
      name: "ordinary server modules may forward the server namespace",
      code: "export * from './server-env.mjs';",
    },
    {
      name: "a client may re-export a type-only declaration",
      code: "'use client'; export type { ServerSettings } from './server-settings.js';",
    },
    {
      name: "a client may re-export only type specifiers",
      code: "'use client'; export { type ServerSettings, type ServerEnv as Env } from './server-env';",
    },
    {
      name: "a client may forward a type-only star export",
      code: "'use client'; export type * from './server-settings.js';",
    },
    {
      name: "a client may forward a type-only namespace export",
      code: "'use client'; export type * as ServerTypes from './server-env';",
    },
    {
      name: "local value exports without a module source are not dependencies",
      code: "'use client'; const settings = {}; export { settings };",
    },
    {
      name: "local type exports without a source stay excluded",
      code: "'use client'; type Settings = { accountId: string }; export type { Settings };",
    },
    {
      name: "public client settings may be re-exported",
      code: "'use client'; export { settings } from './client-settings.js'; export * from '@/client-settings';",
    },
    {
      name: "unrelated settings paths do not acquire a server-only classification",
      code: "'use client'; export { settings } from './settings.js'; export * from './server-settings.test-helper';",
    },
    {
      name: "an index path is outside the existing exact module protocol",
      code: "'use client'; export * from './server-settings/index.js';",
    },
    {
      name: "a nested directive does not turn the module into a client entrypoint",
      code: "function helper() { 'use client'; } export * from './server-settings.js';",
    },
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
    {
      name: "runtime named re-exports keep the server dependency",
      code: "'use client';\nexport { settings } from './server-settings.js';",
      errors: [{ messageId: "noServerEnvInClientComponent", line: 2 }],
    },
    {
      name: "a runtime star re-export keeps the server dependency",
      code: "'use client'; export * from './server-env';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      name: "runtime namespace re-exports keep the server dependency",
      code: "'use client'; export * as serverSettings from '../server-settings.mjs';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      name: "a default re-export is a runtime dependency",
      code: "'use client'; export { default as settings } from '@/server-env.cts';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      name: "mixed type and value specifiers still load server settings once",
      code: "'use client'; export { type ServerSettings, settings } from './server-settings';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      name: "a value export named type is not a type-only specifier",
      code: "'use client'; export { type } from './server-env';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      name: "an empty runtime re-export is not a type-only declaration",
      code: "'use client'; export {} from './server-settings';",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
    {
      name: "local forwarding does not duplicate the original import diagnostic",
      code: "'use client'; import { settings } from './server-settings.js'; export { settings };",
      errors: [{ messageId: "noServerEnvInClientComponent" }],
    },
  ],
});
