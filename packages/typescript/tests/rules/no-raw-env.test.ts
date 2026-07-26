import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-raw-env.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("no-raw-env", rule, {
  valid: [
    // Reading from a validated env module is the prescribed pattern.
    { code: "import { env } from '@/env'; const url = env.DATABASE_URL;" },
    // Unrelated member access is fine.
    { code: "const x = process.cwd();" },
    // A property named `env` on something other than `process` is fine.
    { code: "const x = config.env;" },
    // `process["env"]` (computed on `process`) yields the env object as a whole,
    // not a specific unvalidated var — out of scope.
    { code: "const x = process['env'];" },
    // `import.meta.env` on a non-import meta base is unrelated.
    { code: "const x = config.meta.env;" },
    // Build-time constants are statically replaced by the bundler — there is no
    // runtime env value to validate, so they are exempt.
    { code: "if (process.env.NODE_ENV === 'production') {}" },
    { code: "const dev = import.meta.env.DEV;" },
    { code: "const mode = import.meta.env.MODE;" },
    { code: "const prod = import.meta.env.PROD;" },
    { code: "const ssr = import.meta.env.SSR;" },
    // --- Not a read of a configuration value --------------------------------
    // Setting a variable for a child process. Real corpus:
    // react-router/packages/react-router-dev/vite/plugins/prerender.ts:250.
    { code: "process.env.IS_RR_BUILD_REQUEST = 'yes';" },
    { code: "process.env.IS_RR_BUILD_REQUEST = ogIsBuildRequest;" },
    { code: "delete process.env.FORCE_COLOR;" },
    // Forwarding the inherited environment to a spawned process. Real corpus:
    // react-router/integration/helpers/create-fixture.ts:45.
    { code: "spawn(cmd, { env: { ...process.env, NO_COLOR: '1' } });" },
    // --- Files with no validated env module to import -----------------------
    // A test that drives a CLI has to read and set the raw environment. Real
    // corpus: react-router/packages/create-react-router/__tests__/
    // create-react-router-test.ts (26 hits).
    {
      code: "let originalUserAgent = process.env.npm_config_user_agent;",
      filename: "packages/create-react-router/__tests__/create-react-router-test.ts",
    },
    // A one-off script. Real corpus: zod/scripts/check-versions.ts.
    {
      code: "const tag = process.env.npm_config_tag || 'latest';",
      filename: "zod/scripts/check-versions.ts",
    },
    // Build/test config runs before the app exists. Real corpus:
    // swr/test/e2e/playwright.config.ts.
    {
      code: "export default { retries: process.env.CI ? 2 : 0 };",
      filename: "playwright.config.ts",
    },
    {
      code: "export default { reporters: process.env.GITHUB_ACTIONS };",
      filename: "vitest.config.mts",
    },
    // Validated env boundary modules are the one place raw reads belong.
    {
      code: `
        import { z } from "zod";
        const ZClientSettings = z.object({ publicKey: z.string() });
        export const CLIENT_SETTINGS = ZClientSettings.parse({
          publicKey: process.env["NEXT_PUBLIC_KEY"],
        });
      `,
      filename: "/repo/src/client-settings.ts",
    },
  ],
  invalid: [
    {
      code: "const url = process.env.DATABASE_URL;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      code: "const { FOO } = process.env;",
      errors: [{ messageId: "noRawEnv" }],
    },
    // Computed access into process.env is just as unvalidated as the dotted form.
    {
      code: "const url = process.env[key];",
      errors: [{ messageId: "noRawEnv" }],
    },
    // A real runtime Vite var (not a build-time constant) still fires.
    {
      code: "const x = import.meta.env.VITE_X;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      code: "const x = import.meta.env[key];",
      errors: [{ messageId: "noRawEnv" }],
    },
    // The exemptions must not swallow the shape the rule exists for: application
    // code reading a deployment setting. Real corpus:
    // zod/packages/docs/loaders/stars.ts:1.
    {
      code: "const GITHUB_TOKEN = process.env.GITHUB_TOKEN;",
      filename: "src/loaders/stars.ts",
      errors: [{ messageId: "noRawEnv" }],
    },
    // Only the assignment TARGET is exempt — the read on the right still fires.
    {
      code: "process.env.FOO = process.env.BAR;",
      errors: [{ messageId: "noRawEnv" }],
    },
    // A `*.config.*` basename exempts config; a source file that merely has
    // `config` in its name does not.
    {
      code: "const host = process.env.HOST;",
      filename: "src/config.ts",
      errors: [{ messageId: "noRawEnv" }],
    },
  ],
});
