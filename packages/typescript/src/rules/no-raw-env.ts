/**
 * @fileoverview Disallow direct `process.env` access. Force all env reads
 * through a Zod-validated env module so configuration is typed and validated
 * at startup.
 *
 * The rule is about READING A CONFIGURATION VALUE in application code, and a
 * sweep of 2,186 real TypeScript files (zod / TanStack Query / react-router /
 * swr / zustand) produced 143 hits of which ~90% were not that. Four exemptions,
 * each measured against that corpus:
 *
 *   - **Write target.** `process.env.X = "yes"` sets a variable for a child
 *     process; there is no value being read, so the validated-env module has
 *     nothing to say about it. 20 hits, e.g.
 *     react-router/packages/react-router-dev/vite/plugins/prerender.ts:250 and
 *     react-router/packages/react-router-dev/vite/plugin.ts:2451.
 *   - **Whole-environment pass-through.** `{ ...process.env, NO_COLOR: "1" }`
 *     forwards the inherited environment to a spawned process — again no
 *     configuration value is read. 9 hits, e.g.
 *     react-router/integration/helpers/create-fixture.ts:45.
 *   - **Test files** (shared `isTestFile`). A test that drives a CLI has to set
 *     and read the raw environment; there is no app env module in scope. 50
 *     hits, e.g.
 *     react-router/packages/create-react-router/__tests__/create-react-router-test.ts:1052.
 *   - **Scripts and build/test config** (shared `isScriptFile`, plus a
 *     `*.config.*` basename). A `vitest.config.mts` / `playwright.config.ts`
 *     configures the *build*, runs before the app exists, and cannot import the
 *     app's validated env. 47 hits, e.g. swr/test/e2e/playwright.config.ts:16
 *     and zod/scripts/check-versions.ts:5.
 *
 * What survives is the shape the rule was written for: application code reading
 * a deployment setting, e.g. zod/packages/docs/loaders/stars.ts:1
 * (`const GITHUB_TOKEN = process.env.GITHUB_TOKEN!`).
 *
 * SECOND SWEEP (25,508 deduped TS/TSX files across zod / trpc / dub /
 * openstatus / formbricks / documenso / unkey / midday / papermark / cal.com /
 * hono plus six first-party repos, 2026-07): 1,851 hits, 50 read in a seeded
 * random sample — 43 true positives, 2 false positives, 5 arguable. The rule is
 * essentially correct; the two false-positive classes both came from the rule
 * failing to recognise a value it can say nothing about:
 *
 *   - **The validated env boundary itself, under a form the sniff missed** —
 *     55 / 1,851. `isValidatedEnvBoundary` demanded literally `z.object(` AND
 *     `.parse(`. Across boundary-named files in that corpus, 48 findings use
 *     `createEnv({...})` (`@t3-oss/env-nextjs`), 5 use `z.object` with
 *     `.safeParse`, and 2 use `.parse` with no `z.object`.
 *     `openstatus/apps/web/src/env.ts` alone was 24 findings: a textbook t3-env
 *     boundary whose `runtimeEnv:` map is REQUIRED by the library to spell
 *     `process.env.X` once per variable. Widening the sniff to any of the three
 *     markers costs no measurable recall — 23 boundary-NAMED files in the same
 *     corpus validate nothing at all and keep firing, correctly.
 *   - **Platform/runtime markers** — see `PLATFORM_MARKERS`.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "noRawEnv";
type Options = readonly [];

/** Build / test / tooling config: `vite.config.ts`, `vitest.config.mts`, `playwright.config.ts`. */
const CONFIG_FILE_RE = /(^|[\\/])[\w.-]+\.config\.[cm]?[jt]sx?$/;

/**
 * Modules that define the validated env boundary have to read raw env exactly
 * once before handing values to Zod. Keep this path-scoped so ordinary
 * `config.ts`/settings helpers still use the boundary instead of becoming one.
 */
const ENV_BOUNDARY_FILE_RE =
  /(^|[\\/])(?:env|client-env|server-env|client-settings|server-settings)\.[cm]?[jt]sx?$/;

/**
 * Evidence that a boundary-NAMED module actually validates: a Zod object
 * schema, a `createEnv({...})` call (`@t3-oss/env-nextjs` and friends, which
 * validate against the `server`/`client` schemas passed to them), or a
 * `.parse()` / `.safeParse()` anywhere in the file. Any ONE of the three is
 * enough — requiring `z.object` AND `.parse` together missed 55 of 1,851
 * findings, 48 of them the `createEnv` form.
 */
const ENV_VALIDATION_MARKER_RE =
  /\bcreateEnv\s*\(|\bz\.object\s*\(|\.(?:safeParse|parse)\s*\(/;

function isValidatedEnvBoundary(filename: string, sourceText: string): boolean {
  return (
    ENV_BOUNDARY_FILE_RE.test(filename.replaceAll("\\", "/")) &&
    ENV_VALIDATION_MARKER_RE.test(sourceText)
  );
}

/** True for the `process.env` member node (dotted or as the base of `process.env[key]`). */
function isProcessEnv(node: TSESTree.MemberExpression): boolean {
  return (
    !node.computed &&
    node.object.type === "Identifier" &&
    node.object.name === "process" &&
    node.property.type === "Identifier" &&
    node.property.name === "env"
  );
}

/** True for the `import.meta.env` member node (dotted or as the base of `import.meta.env[key]`). */
function isImportMetaEnv(node: TSESTree.MemberExpression): boolean {
  return (
    !node.computed &&
    node.property.type === "Identifier" &&
    node.property.name === "env" &&
    node.object.type === "MetaProperty" &&
    node.object.meta.name === "import" &&
    node.object.property.name === "meta"
  );
}

// Build-time constants that bundlers (webpack/Vite) statically replace — there is
// no runtime env value to route through the validated layer, so they are exempt.
const BUILD_TIME_CONSTANTS: ReadonlySet<string> = new Set([
  "NODE_ENV",
  "MODE",
  "DEV",
  "PROD",
  "SSR",
]);

/**
 * Markers the PLATFORM injects, not values the deployment configures: which
 * runtime the module was loaded into, whether this is a Vercel build, whether
 * this is CI. Same family as the already-exempt `NODE_ENV` — always present,
 * owned by the host, and nothing an app env schema can meaningfully validate or
 * default. 184 of the 1,851 second-sweep findings were this class, e.g.
 * `formbricks/apps/web/lib/posthog/server.ts:31`
 * (`process.env.NEXT_RUNTIME === "nodejs"`) and
 * `dub/apps/web/lib/middleware/utils/get-final-url.ts:84`
 * (`process.env.VERCEL === "1"`).
 *
 * `VERCEL_URL` (52 findings) and `PORT` (19) are deliberately NOT here: both are
 * read to BUILD a base URL, which is a deployment value a repo may well want its
 * env schema to own. A test pins that exclusion.
 */
const PLATFORM_MARKERS: ReadonlySet<string> = new Set([
  "NEXT_RUNTIME",
  "VERCEL",
  "VERCEL_ENV",
  "CI",
]);

/**
 * True when `node` is the base of an exempt named access like
 * `process.env.NODE_ENV` or `process.env.VERCEL` — a bundler-replaced constant
 * or a platform-injected marker.
 */
function isExemptVariableAccess(node: TSESTree.MemberExpression): boolean {
  const parent = node.parent;
  return (
    parent.type === "MemberExpression" &&
    parent.object === node &&
    !parent.computed &&
    parent.property.type === "Identifier" &&
    (BUILD_TIME_CONSTANTS.has(parent.property.name) ||
      PLATFORM_MARKERS.has(parent.property.name))
  );
}

/**
 * True when the env access is the TARGET of an assignment (`process.env.X = v`,
 * `process.env.X ??= v`, `delete process.env.X`) rather than a read. Writing a
 * variable for a child process reads no configuration value.
 */
function isWriteTarget(node: TSESTree.MemberExpression): boolean {
  const access = node.parent.type === "MemberExpression" && node.parent.object === node ? node.parent : node;
  const parent = access.parent;
  if (parent.type === "AssignmentExpression") {
    return parent.left === access;
  }
  if (parent.type === "UnaryExpression") {
    return parent.operator === "delete";
  }
  return false;
}

/**
 * True when the WHOLE environment is spread into an object literal —
 * `{ ...process.env, NO_COLOR: "1" }`. That forwards the inherited environment
 * to a spawned process; it is not a read of any particular setting.
 */
function isWholeEnvSpread(node: TSESTree.MemberExpression): boolean {
  const parent = node.parent;
  return parent.type === "SpreadElement" && parent.argument === node;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-raw-env",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow direct `process.env` access; use a Zod-validated env module instead.",
    },
    schema: [],
    messages: {
      noRawEnv:
        "Do not read from `process.env` directly. Import the Zod-validated env module instead so values are typed and validated at startup.",
    },
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename;
    if (
      isTestFile(filename) ||
      isScriptFile(filename) ||
      CONFIG_FILE_RE.test(filename.replaceAll("\\", "/")) ||
      isValidatedEnvBoundary(filename, context.sourceCode.text)
    ) {
      return {};
    }
    return {
      MemberExpression(node: TSESTree.MemberExpression): void {
        if (
          (isProcessEnv(node) || isImportMetaEnv(node)) &&
          !isExemptVariableAccess(node) &&
          !isWriteTarget(node) &&
          !isWholeEnvSpread(node)
        ) {
          context.report({
            node,
            messageId: "noRawEnv",
          });
        }
      },
    };
  },
});
