import rule from "../../src/rules/no-raw-env.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-raw-env", rule, {
  valid: [
    { name: "raw-environment-read-dynamic-member", filename: "src/database.ts", code: "const url = process[auditDynamicMember][auditDynamicMember];" },
    { name: "does not infer process from a foreign default import", code: 'import proc from "./process"; const key = proc["env"].KEY;' },
    { name: "preserves a shadowed Node process alias", code: 'import proc from "node:process"; function read(proc: {env: {KEY: string}}) { return proc.env.KEY; }' },
    { name: "does not infer a value from a type-only Node namespace", code: 'import type * as proc from "node:process"; const key = proc.env.KEY;' },
    { name: "preserves platform exemptions under a Node alias", code: 'import proc from "node:process"; const runtime = proc["env"]["NODE_ENV"];' },
    { name: "does not confuse injected config with Node process", code: "function read(process: {env: {KEY: string}}) { return process.env.KEY; }" },
    { name: "accepts the documented validated environment", code: "import { env } from './env.js'; const url = env.DATABASE_URL;" },

    { code: "import { env } from '@/env'; const url = env.DATABASE_URL;" },

    { code: "const x = process.cwd();" },

    { code: "const x = config.env;" },

    { code: "const x = process[member];" },

    { code: "const x = config.meta.env;" },

    { code: "if (process.env.NODE_ENV === 'production') {}" },
    { code: "const dev = import.meta.env.DEV;" },
    { code: "const mode = import.meta.env.MODE;" },
    { code: "const prod = import.meta.env.PROD;" },
    { code: "const ssr = import.meta.env.SSR;" },
    {
      name: "allows assigning a raw variable without reading it",
      code: "process.env.IS_RR_BUILD_REQUEST = 'yes';",
    },
    { code: "process.env.IS_RR_BUILD_REQUEST = ogIsBuildRequest;" },
    {
      name: "allows compound assignment targets",
      code: "process.env.FORCE_COLOR ??= '1';",
    },
    {
      name: "allows deleting a raw variable",
      code: "delete process.env.FORCE_COLOR;",
    },
    {
      name: "allows forwarding the whole environment",
      code: "spawn(cmd, { env: { ...process.env, NO_COLOR: '1' } });",
    },
    {
      name: "allows raw environment access in tests",
      code: "let originalUserAgent = process.env.npm_config_user_agent;",
      filename: "packages/create-react-router/__tests__/create-react-router-test.ts",
    },
    {
      name: "allows raw environment access in scripts",
      code: "const tag = process.env.npm_config_tag || 'latest';",
      filename: "zod/scripts/check-versions.ts",
    },
    {
      name: "allows raw environment access in build config",
      code: "export default { retries: process.env.CI ? 2 : 0 };",
      filename: "playwright.config.ts",
    },
    {
      code: "export default { reporters: process.env.GITHUB_ACTIONS };",
      filename: "vitest.config.mts",
    },
    {
      name: "allows a z.object marker in a boundary-named module",
      code: `
        import { z } from "zod";
        const schema = z.object({ API_KEY: z.string() });
        export const rawApiKey = process.env.API_KEY;
      `,
      filename: "/repo/src/client-env.ts",
    },
    {
      name: "allows a parse marker in a boundary-named module",
      code: `
        const schema = getEnvSchema();
        export const env = schema.parse(process.env);
      `,
      filename: "/repo/src/server-settings.ts",
    },
    {
      name: "allows a safeParse marker in a boundary-named module",
      code: `
        const schema = getEnvSchema();
        export const env = schema.safeParse(process.env);
      `,
      filename: "/repo/src/server-env.ts",
    },
    {
      name: "allows bracketed raw reads inside a validated boundary",
      code: `
        import { z } from "zod";
        const ZClientSettings = z.object({ publicKey: z.string() });
        export const CLIENT_SETTINGS = ZClientSettings.parse({
          publicKey: process.env["NEXT_PUBLIC_KEY"],
        });
      `,
      filename: "/repo/src/client-settings.ts",
    },
    {
      name: "allows createEnv runtime mappings in a boundary-named module",
      code: `
        import { createEnv } from "@t3-oss/env-nextjs";
        import { z } from "zod";
        export const env = createEnv({
          server: { TINYBIRD_URL: z.string() },
          runtimeEnv: { TINYBIRD_URL: process.env.TINYBIRD_URL },
        });
      `,
      filename: "/repo/apps/web/src/env.ts",
    },
    {
      name: "allows the host-owned NEXT_RUNTIME marker",
      code: "if (process.env.NEXT_RUNTIME === 'nodejs') {}",
    },
    {
      name: "allows the host-owned VERCEL marker",
      code: "const ip = process.env.VERCEL === '1' ? real : local;",
    },
    {
      name: "allows the host-owned VERCEL_ENV marker",
      code: "if (process.env.VERCEL_ENV === 'production') {}",
    },
    {
      name: "allows the host-owned CI marker",
      code: "const retries = process.env.CI ? 2 : 0;",
    },
  ],
  invalid: [
    { name: "raw-environment-read-static-member", filename: "src/database.ts", code: "const url = process[\"env\"][\"DATABASE_URL\"];", errors: [{ messageId: "noRawEnv" }] },
    { name: "reports a default Node process alias", code: 'import proc from "node:process"; const key = proc.env.KEY;', errors: [{ messageId: "noRawEnv" }] },
    { name: "reports a namespace process alias with static bracket access", code: 'import * as proc from "process"; const key = proc["env"]["KEY"];', errors: [{ messageId: "noRawEnv" }] },
    { name: "reports a static bracket read of the raw environment object", code: "const x = process['env'];", errors: [{ messageId: "noRawEnv" }] },
    { name: "does not treat a comment as environment validation", filename: "src/env.ts", code: "// z.object({ KEY: z.string() }).parse(process.env)\nexport const key = process.env.KEY;", errors: [{messageId: "noRawEnv"}] },
    { name: "does not treat string payload as environment validation", filename: "src/env.ts", code: "const example = 'z.object({}).parse(process.env)'; export const key = process.env.KEY;", errors: [{messageId: "noRawEnv"}] },
    { name: "reports the documented raw environment read (its focusPath keeps it distinct from the next case's code)", filename: "src/database.ts", code: "const url = process.env.DATABASE_URL;", errors: [{ messageId: "noRawEnv" }] },
    {
      code: "const url = process.env.DATABASE_URL;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      code: "const { FOO } = process.env;",
      errors: [{ messageId: "noRawEnv" }],
    },

    {
      code: "const url = process.env[key];",
      errors: [{ messageId: "noRawEnv" }],
    },

    {
      code: "const x = import.meta.env.VITE_X;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      code: "const x = import.meta.env[key];",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports deployment settings read by application code",
      code: "const GITHUB_TOKEN = process.env.GITHUB_TOKEN;",
      filename: "src/loaders/stars.ts",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports a raw read on an assignment right-hand side",
      code: "process.env.FOO = process.env.BAR;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports raw reads in ordinary config source modules",
      code: "const host = process.env.HOST;",
      filename: "src/config.ts",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports boundary-named modules without validation markers",
      code: "export const apiKey = process.env.API_KEY;",
      filename: "/repo/src/env.ts",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports VERCEL_URL because it is deployment configuration",
      code: "const base = `https://${process.env.VERCEL_URL}`;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports PORT because it is deployment configuration",
      code: "const port = process.env.PORT;",
      errors: [{ messageId: "noRawEnv" }],
    },
  ],
});
