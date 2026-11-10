import rule from "../../src/rules/no-raw-env.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-raw-env", rule, {
  valid: [
    {
      name: "a known identity helper can forward into the actual Zod parser",
      filename: "/repo/src/env.ts",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ KEY: z.string() }); const createEnv = input => input; export const settings = SettingsSchema.parse(createEnv(process.env));',
    },
    {
      name: "an identity method can forward into an actual outer validator",
      filename: "/repo/src/env.ts",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ KEY: z.string() }); const adapter = { parse(input) { return input; } }; export const settings = SettingsSchema.parse(adapter.parse(process.env));',
    },
    {
      name: "identity forwarding may use a stable private value alias",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => input; const input = createEnv(process.env); export const settings = SettingsSchema.parse(input);",
    },
    {
      name: "angle-bracket assertions do not block a real outer settings parser",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => input; export const settings = SettingsSchema.parse(<Settings>createEnv(process.env));",
    },
    {
      name: "a real local Zod wrapper is not treated as identity",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => SettingsSchema.parse(input); export const settings = createEnv(process.env);",
    },
    {
      name: "a parse method invoking the real schema is not treated as identity",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse(input) { return SettingsSchema.parse(input); } }; export const settings = adapter.parse(process.env);",
    },
    {
      name: "an imported project settings loader remains an unresolved supported protocol",
      filename: "/repo/src/env.ts",
      code: 'import { createEnv } from "./typed-settings-loader.js"; export const settings = createEnv(process.env);',
    },
    {
      name: "a receiver method write makes its current implementation unknown",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input }; adapter.parse = input => SettingsSchema.parse(input); export const settings = adapter.parse(process.env);",
    },
    {
      name: "an escaped receiver can be configured by another owner",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input }; configure(adapter); export const settings = adapter.parse(process.env);",
    },
    {
      name: "an extra receiver method may change validation ownership",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input, configure() { this.parse = input => SettingsSchema.parse(input); } }; adapter.configure(); export const settings = adapter.parse(process.env);",
    },
    {
      name: "object spreads leave adapter ownership unknown",
      filename: "/repo/src/env.ts",
      code: "const adapter = { ...source, parse: input => input }; export const settings = adapter.parse(process.env);",
    },
    {
      name: "a getter may provide a real settings validator",
      filename: "/repo/src/env.ts",
      code: "const adapter = { get parse() { return SettingsSchema.parse; } }; export const settings = adapter.parse(process.env);",
    },
    {
      name: "a duplicate key can replace an earlier identity method",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input, parse: input => SettingsSchema.parse(input) }; export const settings = adapter.parse(process.env);",
    },
    {
      name: "an opaque computed key can replace the visible method",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input, [key]: validator }; export const settings = adapter.parse(process.env);",
    },
    {
      name: "a reassigned function binding does not retain identity ownership",
      filename: "/repo/src/env.ts",
      code: "function createEnv(input) { return input; } createEnv = input => SettingsSchema.parse(input); export const settings = createEnv(process.env);",
    },
    {
      name: "a public exported loader retains its existing project protocol",
      filename: "/repo/src/env.ts",
      code: "export const createEnv = input => input; export const settings = createEnv(process.env);",
    },
    {
      name: "a named receiver export is an ordinary escape",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input }; export { adapter }; export const settings = adapter.parse(process.env);",
    },
    {
      name: "a parameter shadowing the local adapter can be a real settings loader",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => input; export function load(createEnv) { return createEnv(process.env); }",
    },
    {
      name: "direct eval may install a different validator",
      filename: "/repo/src/env.ts",
      code: 'const adapter = { parse: input => input }; eval("adapter.parse = SettingsSchema.parse"); export const settings = adapter.parse(process.env);',
    },
    {
      name: "a namespace member can be changed through its namespace owner",
      filename: "/repo/src/env.ts",
      code: "export namespace Config { function createEnv(input) { return input; } export const settings = createEnv(process.env); }",
    },
    {
      name: "optional adapter calls retain the existing unresolved protocol",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input }; export const settings = SettingsSchema.parse(adapter.parse?.(process.env));",
    },
    {
      name: "awaited adapter-result flow is deliberately outside the exact identity proof",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => input; export const settings = SettingsSchema.parse(await createEnv(process.env));",
    },
    {
      name: "parameter defaults are not inferred to be exact identity adapters",
      filename: "/repo/src/env.ts",
      code: "const createEnv = (input = defaults) => input; export const settings = createEnv(process.env);",
    },
    {
      name: "simple selected env fields can all feed the actual boundary parser",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY } = process.env; export const settings = SettingsSchema.parse({ API_KEY });",
    },
    {
      name: "a named native env alias supports selected-field validation",
      filename: "/repo/src/env.ts",
      code: 'import { env as raw } from "node:process"; const { API_KEY } = raw; export const settings = SettingsSchema.parse({ API_KEY });',
    },
    {
      name: "selected static keys may be renamed while every value is parsed",
      filename: "/repo/src/env.ts",
      code: 'const { "API_KEY": apiKey, ["API_ORIGIN"]: apiOrigin } = process.env; export const settings = SettingsSchema.parse({ apiKey, apiOrigin });',
    },
    {
      name: "type-only references do not count as raw selected-field escapes",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY } = process.env; export type ApiKey = typeof API_KEY; export const settings = SettingsSchema.parse({ API_KEY });",
    },
    {
      name: "whole-environment aliases may have harmless type queries before parsing",
      filename: "/repo/src/env.ts",
      code: "const raw = process.env; export type Environment = typeof raw; export const settings = SettingsSchema.parse(raw);",
    },
    {
      name: "host marker fields can coexist with separately parsed ordinary settings",
      filename: "/repo/src/env.ts",
      code: 'import { env as raw } from "node:process"; const { NODE_ENV: mode, API_KEY } = raw; export const settings = SettingsSchema.parse({ API_KEY }); export const production = mode === "production";',
    },
    {
      name: "a destructured native environment can supply parsed selected fields",
      filename: "/repo/src/env.ts",
      code: "const { env: raw } = process; const { API_KEY } = raw; export const settings = SettingsSchema.parse({ API_KEY });",
    },
    {
      name: "selected values retain existing optional-default precedence",
      filename: "/repo/src/env.ts",
      code: 'const { OPTIONAL_ORIGIN } = process.env; export const settings = SettingsSchema.parse({ OPTIONAL_ORIGIN: OPTIONAL_ORIGIN ?? "http://localhost:8080" });',
    },
    {
      name: "native alias host marker extraction remains exempt in application code",
      filename: "/repo/src/runtime.ts",
      code: 'import { env as raw } from "node:process"; const { NODE_ENV: mode, CI } = raw; export const platform = { mode, CI };',
    },
    {
      name: "field patterns exceeding the explicit selection budget remain unknown",
      filename: "/repo/src/env.ts",
      code: "const { K0, K1, K2, K3, K4, K5, K6, K7, K8, K9, K10, K11, K12, K13, K14, K15, K16, K17, K18, K19, K20, K21, K22, K23, K24, K25, K26, K27, K28, K29, K30, K31, K32, K33, K34, K35, K36, K37, K38, K39, K40, K41, K42, K43, K44, K45, K46, K47, K48, K49, K50, K51, K52, K53, K54, K55, K56, K57, K58, K59, K60, K61, K62, K63, K64, K65, K66, K67, K68, K69, K70, K71, K72, K73, K74, K75, K76, K77, K78, K79, K80, K81, K82, K83, K84, K85, K86, K87, K88, K89, K90, K91, K92, K93, K94, K95, K96, K97, K98, K99, K100, K101, K102, K103, K104, K105, K106, K107, K108, K109, K110, K111, K112, K113, K114, K115, K116, K117, K118, K119, K120, K121, K122, K123, K124, K125, K126, K127, K128 } = process.env;",
    },
    {
      name: "named native env imports flow into the boundary parser",
      filename: "/repo/src/env.ts",
      code: 'import { env as raw } from "node:process"; export const settings = SettingsSchema.parse(raw);',
    },
    {
      name: "native env destructuring feeds the parser through a stable alias",
      filename: "/repo/src/settings.ts",
      code: "const { env: raw } = process; export const settings = SettingsSchema.parse(raw);",
    },
    {
      name: "native process module aliases can expose env through destructuring",
      filename: "/repo/src/env.ts",
      code: 'import runtime from "node:process"; const { env: raw } = runtime; export const settings = SettingsSchema.parse(raw);',
    },
    {
      name: "named env imports preserve host marker exemptions",
      filename: "/repo/src/runtime.ts",
      code: 'import { env as raw } from "node:process"; export const production = raw.NODE_ENV === "production";',
    },
    {
      name: "native env aliases preserve member writes and deletion",
      filename: "/repo/src/runtime.ts",
      code: 'import { env as raw } from "node:process"; raw.MODE = "test"; raw.KEY ??= "fixture"; delete raw.KEY;',
    },
    {
      name: "native env aliases retain whole-environment forwarding outside boundaries",
      filename: "/repo/src/child.ts",
      code: 'const { env: raw } = process; spawn(command, { env: { ...raw, NO_COLOR: "1" } });',
    },
    {
      name: "named env imports from foreign modules are not native process inputs",
      filename: "/repo/src/client.ts",
      code: 'import { env as raw } from "./process.js"; export const origin = raw.API_ORIGIN;',
    },
    {
      name: "type-only native env imports are not runtime acquisitions",
      filename: "/repo/src/client.ts",
      code: 'import type { env as raw } from "node:process"; export type Environment = typeof raw;',
    },
    {
      name: "native env imports used only in a type query do not acquire runtime settings",
      filename: "/repo/src/client.ts",
      code: 'import { env as raw } from "node:process"; export type Environment = typeof raw;',
    },
    {
      name: "a parameter shadowing a native env import is an injected object",
      filename: "/repo/src/client.ts",
      code: 'import { env as raw } from "node:process"; export function read(raw) { return raw.KEY; }',
    },
    {
      name: "a parameter named process does not prove native destructuring",
      filename: "/repo/src/client.ts",
      code: "export function read(process) { const { env: raw } = process; return raw.KEY; }",
    },
    {
      name: "mutable destructured aliases do not prove a stable native env source",
      filename: "/repo/src/client.ts",
      code: "let { env: raw } = process; raw = fixture; export const key = raw.KEY;",
    },
    {
      name: "a renamed T3 validator retains actual import ownership",
      filename: "/repo/src/env.ts",
      code: 'import { createEnv as makeEnv } from "@t3-oss/env-nextjs"; import { z } from "zod"; export const settings = makeEnv({ server: { API_KEY: z.string().min(1) }, runtimeEnv: { API_KEY: process.env.API_KEY } });',
    },
    {
      name: "the core T3 package supports renamed validator imports",
      filename: "/repo/src/env.ts",
      code: 'import { createEnv as makeEnv } from "@t3-oss/env-core"; import { z } from "zod"; export const settings = makeEnv({ server: { API_ORIGIN: z.url() }, runtimeEnv: { API_ORIGIN: process.env.API_ORIGIN } });',
    },
    {
      name: "a directly awaited async parse completes before settings exposure",
      filename: "/repo/src/env.ts",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ KEY: z.string() }); export const settings = await SettingsSchema.parseAsync(process.env);',
    },
    {
      name: "a directly awaited safe async parse still requires separate failure handling",
      filename: "/repo/src/env.ts",
      code: 'const result = await SettingsSchema.safeParseAsync(process.env); if (!result.success) throw new Error("invalid settings"); export const settings = result.data;',
    },
    {
      name: "conditional value arms can contain validated raw input",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse(enabled ? process.env.API_ORIGIN : undefined);",
    },
    {
      name: "nullish and logical-or defaults preserve their input value branches",
      filename: "/repo/src/env.ts",
      code: 'export const settings = SettingsSchema.parse({ ORIGIN: process.env.ORIGIN ?? "http://localhost:8080", NAME: process.env.NAME || "local" });',
    },
    {
      name: "a logical-and right operand remains the parsed value",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse(enabled && process.env.API_ORIGIN);",
    },
    {
      name: "native JSON decoding must feed the actual settings validator",
      filename: "/repo/src/env.ts",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ API_ORIGIN: z.url() }); export const settings = SettingsSchema.parse(JSON.parse(process.env.SETTINGS_JSON));',
    },
    {
      name: "an unresolved project parser named JSON remains a supported protocol",
      filename: "/repo/src/env.ts",
      code: 'import JSON from "./typed-settings-loader.js"; export const settings = JSON.parse(process.env);',
    },
    {
      name: "the shared settings module is a supported validation boundary",
      filename: "/repo/src/settings.ts",
      code: "export const settings = SettingsSchema.parse(process.env);",
    },
    {
      name: "ESM settings modules parse the shared object at their boundary",
      filename: "/repo/src/env.mjs",
      code: "export const settings = SettingsSchema.parse(process.env);",
    },
    {
      name: "a copied input object is allowed when it reaches validation",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse({ ...process.env });",
    },
    {
      name: "one parsed settings object can serve multiple consumers",
      filename: "/repo/src/env.ts",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ API_KEY: z.string().min(1) }); export const settings = SettingsSchema.parse(process.env); export const first = () => settings.API_KEY; export const second = () => settings.API_KEY;',
    },
    {
      name: "stable raw aliases may flow only to the shared parser",
      filename: "/repo/src/env.ts",
      code: "const raw = process.env; const input = raw; export const settings = SettingsSchema.parse(input);",
    },
    {
      name: "supports validation after explicit scalar coercion",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse({ PORT: Number(process.env.PORT) });",
    },
    {
      name: "supports import meta env in a validated input mapping",
      filename: "/repo/src/client-env.ts",
      code: "export const settings = SettingsSchema.parse({ API_URL: import.meta.env.VITE_API_URL });",
    },
    {
      name: "raw-environment-read-dynamic-member",
      filename: "src/database.ts",
      code: "const url = process[auditDynamicMember][auditDynamicMember];",
    },
    {
      name: "does not infer process from a foreign default import",
      code: 'import proc from "./process"; const key = proc["env"].KEY;',
    },
    {
      name: "preserves a shadowed Node process alias",
      code: 'import proc from "node:process"; function read(proc: {env: {KEY: string}}) { return proc.env.KEY; }',
    },
    {
      name: "does not infer a value from a type-only Node namespace",
      code: 'import type * as proc from "node:process"; const key = proc.env.KEY;',
    },
    {
      name: "preserves platform exemptions under a Node alias",
      code: 'import proc from "node:process"; const runtime = proc["env"]["NODE_ENV"];',
    },
    {
      name: "does not confuse injected config with Node process",
      code: "function read(process: {env: {KEY: string}}) { return process.env.KEY; }",
    },
    {
      name: "accepts the documented validated environment",
      code: "import { env } from './env.js'; const url = env.DATABASE_URL;",
    },

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
    {
      name: "a stable local function declaration returning its argument is not validation",
      filename: "/repo/src/env.ts",
      code: "function createEnv(input) { return input; } export const settings = createEnv(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a stable local identity arrow is not a settings loader",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => input; export const settings = createEnv(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "typed identity bodies do not add runtime validation",
      filename: "/repo/src/env.ts",
      code: "const createEnv = (input: unknown): Settings => input as Settings; export const settings = createEnv(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "an own plain parse identity method does not validate the environment",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse(input) { return input; } }; export const settings = adapter.parse(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "an own safeParse identity method does not produce a validation outcome",
      filename: "/repo/src/env.ts",
      code: "const adapter = { safeParse: input => input }; export const settings = adapter.safeParse(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "two own identity methods still require an actual parser after each call",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input, safeParse: input => input }; export const first = adapter.parse(process.env); export const second = adapter.safeParse(process.env);",
      errors: [{ messageId: "noRawEnv" }, { messageId: "noRawEnv" }],
    },
    {
      name: "transparent receiver and return wrappers do not add validation",
      filename: "/repo/src/env.ts",
      code: "const adapter = ({ parse: (input: unknown) => input! } as Adapter); export const settings = (adapter as Adapter).parse(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "type-only receiver references do not obscure a closed identity proof",
      filename: "/repo/src/env.ts",
      code: "const adapter = { parse: input => input }; export type Adapter = typeof adapter; export const settings = adapter.parse(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "an asserted identity result is still raw until actually parsed",
      filename: "/repo/src/env.ts",
      code: "const createEnv = input => input; export const settings = <Settings>createEnv(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "unused selected ordinary inputs are not validated",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY } = process.env;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a selected field cannot escape without its parser",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY } = process.env; export const leaked = API_KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "one parsed selected field does not exempt another raw escape",
      filename: "/repo/src/env.ts",
      code: 'import { env as raw } from "node:process"; const { API_KEY, API_ORIGIN } = raw; export const settings = SettingsSchema.parse({ API_KEY }); export const leaked = API_ORIGIN;',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a later write destroys selected-field binding proof",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY } = process.env; API_KEY = replacement; export const settings = SettingsSchema.parse({ API_KEY });",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "only type references do not validate an otherwise unused selected field",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY } = process.env; export type ApiKey = typeof API_KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "opaque computed calls are not plain selected keys",
      filename: "/repo/src/env.ts",
      code: "const { [fieldName()]: apiKey } = process.env; export const settings = SettingsSchema.parse({ apiKey });",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "computed binding names are not guessed from their spelling",
      filename: "/repo/src/env.ts",
      code: 'const field = "API_KEY"; const { [field]: apiKey } = process.env; export const settings = SettingsSchema.parse({ apiKey });',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "call defaults can execute before selected-field validation",
      filename: "/repo/src/env.ts",
      code: 'const { API_KEY = fetch("https://example.test/key") } = process.env; export const settings = SettingsSchema.parse({ API_KEY });',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "rest patterns remain outside selected-field proof",
      filename: "/repo/src/env.ts",
      code: "const { API_KEY, ...rest } = process.env; export const settings = SettingsSchema.parse({ API_KEY, ...rest });",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "exported selected bindings escape alongside their parsed object",
      filename: "/repo/src/env.ts",
      code: "export const { API_KEY } = process.env; export const settings = SettingsSchema.parse({ API_KEY });",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a host-marker-shaped property of a raw field is not a native marker",
      filename: "/repo/src/env.ts",
      code: "const { NODE_ENV } = process.env.SECRET_INPUT; export const mode = NODE_ENV;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "nested patterns remain outside plain identifier field selection",
      filename: "/repo/src/env.ts",
      code: "const { SECTION: { API_KEY } } = process.env; export const settings = SettingsSchema.parse({ API_KEY });",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "named native env imports cannot escape into application consumers",
      filename: "/repo/src/client.ts",
      code: 'import { env as raw } from "node:process"; export const origin = raw.API_ORIGIN;',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "native process env destructuring cannot bypass application validation",
      filename: "/repo/src/client.ts",
      code: "const { env: raw } = process; export const origin = raw.API_ORIGIN;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a parsed named env alias does not exempt an additional raw export",
      filename: "/repo/src/env.ts",
      code: 'import { env as raw } from "node:process"; export const settings = SettingsSchema.parse(raw); export const leaked = raw.API_KEY;',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a conditional test does not become the parsed branch value",
      filename: "/repo/src/env.ts",
      code: 'export const settings = SettingsSchema.parse(process.env.LOAD_REMOTE ? fetch("https://example.test/config") : undefined);',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "logical-and input conditions cannot hide remote effects before parsing",
      filename: "/repo/src/env.ts",
      code: 'export const settings = SettingsSchema.parse(process.env.LOAD_REMOTE && fetch("https://example.test/config"));',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "native JSON parsing alone does not validate the settings contract",
      filename: "/repo/src/env.ts",
      code: "export const settings = JSON.parse(process.env.SETTINGS_JSON);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a JSON reviver cannot consume unvalidated input before the settings parser",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse(JSON.parse(process.env.SETTINGS_JSON, (key, value) => fetch(value)));",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "an async parser Promise is not a completed startup settings result",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parseAsync(process.env);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "async result aliasing is outside the direct-await proof",
      filename: "/repo/src/env.ts",
      code: "const pending = SettingsSchema.parseAsync(process.env); export const settings = await pending;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a foreign renamed createEnv import does not establish T3 validation",
      filename: "/repo/src/env.ts",
      code: 'import { createEnv as makeEnv } from "./unrelated.js"; export const settings = makeEnv(process.env);',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a type-only T3 alias does not establish a runtime validator",
      filename: "/repo/src/env.ts",
      code: 'import type { createEnv as makeEnv } from "@t3-oss/env-core"; export const settings = makeEnv(process.env);',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a parameter shadowing a real T3 alias does not retain import ownership",
      filename: "/repo/src/env.ts",
      code: 'import { createEnv as makeEnv } from "@t3-oss/env-core"; export function load(makeEnv) { return makeEnv(process.env); }',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a settings filename alone does not validate raw values",
      filename: "/repo/src/settings.ts",
      code: "export const settings = { KEY: process.env.KEY };",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "an ESM boundary is not exempt merely because ordinary mjs scripts are",
      filename: "/repo/src/env.mjs",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ KEY: z.string() }); export const settings = { KEY: process.env.KEY };',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "exported raw declarations escape even when other uses reach the parser",
      filename: "/repo/src/env.ts",
      code: "export const raw = process.env; export const settings = SettingsSchema.parse(raw);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "named raw re-exports escape alongside validated settings",
      filename: "/repo/src/env.ts",
      code: "const raw = process.env; export const settings = SettingsSchema.parse(raw); export { raw };",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "remote effects must not consume a raw value before validation",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse(fetch(process.env.API_URL));",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a shadowed scalar constructor may have arbitrary effects",
      filename: "/repo/src/env.ts",
      code: "const Number = value => fetch(value); export const settings = SettingsSchema.parse({ PORT: Number(process.env.PORT) });",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "spreading the environment does not create validated settings",
      filename: "/repo/src/env.ts",
      code: "export const settings = { ...process.env };",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a Zod schema declaration does not validate an unrelated raw export",
      filename: "/repo/src/client-env.ts",
      code: 'import { z } from "zod"; const SettingsSchema = z.object({ API_KEY: z.string() }); export const rawApiKey = process.env.API_KEY;',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "parsing another value does not validate the raw export",
      filename: "/repo/src/env.ts",
      code: "const other = SettingsSchema.parse(input); export const rawApiKey = process.env.API_KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a validated settings export does not exempt an extra raw export",
      filename: "/repo/src/env.ts",
      code: "export const settings = SettingsSchema.parse(process.env); export const rawApiKey = process.env.API_KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "raw aliases may not escape alongside the parsed object",
      filename: "/repo/src/env.ts",
      code: "const raw = process.env; export const settings = SettingsSchema.parse(raw); export const leaked = raw.API_KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "a parser used as an unrelated method receiver is not a validation argument",
      filename: "/repo/src/env.ts",
      code: "export const settings = process.env.parse(input);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "mutable raw aliases are not a stable validation boundary",
      filename: "/repo/src/env.ts",
      code: "let raw = process.env; raw = other; export const settings = SettingsSchema.parse(raw);",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "unused raw aliases are not validated",
      filename: "/repo/src/env.ts",
      code: "const raw = process.env;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "raw-environment-read-static-member",
      filename: "src/database.ts",
      code: 'const url = process["env"]["DATABASE_URL"];',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports a default Node process alias",
      code: 'import proc from "node:process"; const key = proc.env.KEY;',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports a namespace process alias with static bracket access",
      code: 'import * as proc from "process"; const key = proc["env"]["KEY"];',
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports a static bracket read of the raw environment object",
      code: "const x = process['env'];",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "does not treat a comment as environment validation",
      filename: "src/env.ts",
      code: "// z.object({ KEY: z.string() }).parse(process.env)\nexport const key = process.env.KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "does not treat string payload as environment validation",
      filename: "src/env.ts",
      code: "const example = 'z.object({}).parse(process.env)'; export const key = process.env.KEY;",
      errors: [{ messageId: "noRawEnv" }],
    },
    {
      name: "reports the documented raw environment read (its focusPath keeps it distinct from the next case's code)",
      filename: "src/database.ts",
      code: "const url = process.env.DATABASE_URL;",
      errors: [{ messageId: "noRawEnv" }],
    },
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
