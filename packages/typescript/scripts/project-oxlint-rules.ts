// Project the third-party rules of the managed Oxlint config for the docs
// catalog: evaluate createConfig() from oxlint.strict.mts, resolve its
// overrides for one example path per context, and describe every enabled rule
// that is not @sarj. JS plugin rules take their summary and docs link from the
// installed plugin. Native Oxlint rules carry no description in the Oxlint
// package, so their summaries live in oxlint-native-rule-summaries.json; a
// newly enabled native rule needs an entry there.
//
//   node scripts/project-oxlint-rules.ts

import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { registerHooks } from "node:module";
import { dirname, join, matchesGlob, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import type { OxlintConfig } from "oxlint";
import { z } from "zod";

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONFIG_ROOT = join(PACKAGE_ROOT, "../standards/src/sarj_standards/configs");
const OXLINT_BIN = join(PACKAGE_ROOT, "node_modules/.bin/oxlint");

const PeerManifestSchema = z.object({ peers: z.record(z.string(), z.string()) });
const SummariesSchema = z.record(z.string(), z.string().min(1));
const NativeRulesSchema = z.array(
  z.object({ scope: z.string(), value: z.string(), fix: z.string(), "docs_url": z.string().startsWith("https://") }),
);
const PluginDocsSchema = z.object({ description: z.string().min(1), url: z.string().startsWith("https://") });

const CONTEXTS = [
  ["source-ts", "TypeScript source", "src/example.ts"],
  ["source-tsx", "React source", "src/example.tsx"],
  ["source-js", "JavaScript source", "src/example.js"],
  ["source-jsx", "React JavaScript source", "src/example.jsx"],
  ["test-ts", "TypeScript tests", "tests/example.test.ts"],
  ["test-bun-ts", "Bun tests", "tests/example.bun.test.ts"],
  ["test-playwright-ts", "Playwright end-to-end tests", "tests/example.playwright.ts"],
  ["config-ts", "Syntax-only tool configuration", "vite.config.ts"],
  ["design-system-tsx", "Design-system React source", "src/components/ui/example.tsx"],
] as const;

// Native Oxlint plugins by config name, and the label of every provider.
// JS plugins load under the config name they are registered with in
// oxlint.strict.mts; their package comes from that registration.
const NATIVE_PLUGINS: Readonly<Record<string, string>> = {
  eslint: "ESLint core",
  typescript: "TypeScript",
  unicorn: "Unicorn",
  react: "React",
  import: "Import",
  promise: "Promise",
  oxc: "Oxc",
  vitest: "Vitest",
  jest: "Jest / Bun Test",
};
const JS_PLUGINS: Readonly<Record<string, { readonly label: string; readonly homepage: string }>> = {
  "eslint-js": { label: "ESLint core (JS plugin)", homepage: "https://eslint.org/docs/latest/rules/" },
  "unicorn-js": { label: "Unicorn (JS plugin)", homepage: "https://github.com/sindresorhus/eslint-plugin-unicorn" },
  "jsdoc-js": { label: "JSDoc (JS plugin)", homepage: "https://github.com/gajus/eslint-plugin-jsdoc" },
  "react-js": { label: "React (JS plugin)", homepage: "https://github.com/jsx-eslint/eslint-plugin-react" },
  regexp: { label: "RegExp", homepage: "https://ota-meshi.github.io/eslint-plugin-regexp/" },
  security: { label: "Security", homepage: "https://github.com/eslint-community/eslint-plugin-security" },
  zod: { label: "ESLint Zod", homepage: "https://github.com/marcalexiei/eslint-zod" },
  "@tanstack/query": { label: "TanStack Query", homepage: "https://tanstack.com/query/latest/docs/eslint/eslint-plugin-query" },
  "@eslint-react": { label: "ESLint React", homepage: "https://eslint-react.xyz/" },
  effects: { label: "You Might Not Need an Effect", homepage: "https://github.com/NickvanDyke/eslint-plugin-react-you-might-not-need-an-effect" },
  "node-test": { label: "Node Test", homepage: "https://github.com/sindresorhus/eslint-node-test" },
  "testing-library": { label: "Testing Library", homepage: "https://github.com/testing-library/eslint-plugin-testing-library" },
  playwright: { label: "Playwright", homepage: "https://github.com/mskelton/eslint-plugin-playwright" },
};
// The ESLint core rules oxlint-plugin-eslint wraps ship without docs metadata.
const ESLINT_CORE_PLUGIN = "eslint-js";

type Level = "error" | "warning";

interface RuleMeta {
  readonly docs?: unknown;
  readonly fixable?: unknown;
  readonly hasSuggestions?: unknown;
}
interface Plugin {
  readonly rules: Readonly<Record<string, { readonly meta?: RuleMeta }>>;
}
interface Description {
  readonly summary: string;
  readonly docsUrl: string;
  readonly autofix: "none" | "available";
  readonly hasSuggestions: boolean;
}

async function project(): Promise<void> {
  const config = await managedConfig();
  const { peers } = PeerManifestSchema.parse(JSON.parse(await readFile(join(CONFIG_ROOT, "typescript.peers.json"), "utf8")));
  const summaries = SummariesSchema.parse(JSON.parse(await readFile(join(PACKAGE_ROOT, "scripts/oxlint-native-rule-summaries.json"), "utf8")));
  const native = nativeRules();
  const plugins = await jsPlugins(config);
  const contextsByRule = new Map<string, { id: string; label: string; level: Level }[]>();
  for (const [id, label, path] of CONTEXTS) {
    for (const [ruleId, level] of effectiveLevels(config, path)) {
      if (ruleId.startsWith("@sarj/")) continue;
      contextsByRule.set(ruleId, [...(contextsByRule.get(ruleId) ?? []), { id, label, level }]);
    }
  }
  const unusedSummaries = Object.keys(summaries).filter((ruleId) => !contextsByRule.has(ruleId));
  if (unusedSummaries.length > 0) throw new Error(`summaries for rules the config does not enable: ${unusedSummaries.join(", ")}`);
  const rules = [...contextsByRule].map(([displayId, contexts]) => {
    const { namespace, id } = splitRule(displayId);
    const plugin = plugins.get(namespace);
    const description =
      plugin === undefined
        ? nativeDescription(displayId, native, summaries)
        : pluginDescription(displayId, plugin.rules[id]?.meta, namespace === ESLINT_CORE_PLUGIN ? summaries[displayId] : undefined);
    const provider = providerId(namespace);
    // Version-one catalog labels remain compatible; both expose one policy.
    const profiles = ["application", "standard"].map((name) => ({ name, contexts }));
    return { key: `${provider}:${id}`, provider, id, displayId, ...description, family: null, profiles };
  });
  const usedNamespaces = new Set([...contextsByRule.keys()].map((ruleId) => splitRule(ruleId).namespace));
  const providers = [...usedNamespaces].map((namespace) => {
    const plugin = plugins.get(namespace);
    const packageName = plugin?.specifier ?? "oxlint";
    const version = peers[packageName];
    if (version === undefined) throw new Error(`typescript.peers.json does not pin ${packageName}`);
    const { label, homepage } = plugin === undefined ? nativeProvider(namespace) : jsProvider(namespace);
    return { id: providerId(namespace), label, engine: "oxlint", package: packageName, version, homepage };
  });
  process.stdout.write(
    `${JSON.stringify({
      providers: providers.sort((left, right) => left.id.localeCompare(right.id)),
      rules: rules.sort((left, right) => left.key.localeCompare(right.key)),
    })}\n`,
  );
}

async function managedConfig(): Promise<OxlintConfig> {
  // oxlint.strict.mts imports "oxlint", which only this package installs.
  registerHooks({
    resolve: (specifier, context, next) => next(specifier, specifier === "oxlint" ? { ...context, parentURL: import.meta.url } : context),
  });
  const module = (await import(pathToFileURL(join(CONFIG_ROOT, "oxlint.strict.mts")).href)) as {
    createConfig(options: { testFrameworks: readonly string[] }): OxlintConfig;
  };
  return module.createConfig({ testFrameworks: ["vitest", "bun", "node", "testing-library", "playwright"] });
}

/** The level of every enabled rule for `path`, after the overrides that match it. */
function effectiveLevels(config: OxlintConfig, path: string): Map<string, Level> {
  const levels = new Map<string, Level>();
  const apply = (rules: Readonly<Record<string, unknown>> = {}): void => {
    for (const [ruleId, setting] of Object.entries(rules)) {
      const level = severity(Array.isArray(setting) ? (setting[0] as unknown) : setting);
      if (level === undefined) levels.delete(ruleId);
      else levels.set(ruleId, level);
    }
  };
  const matches = (globs: readonly string[] | null | undefined): boolean => (globs ?? []).some((glob) => matchesGlob(path, glob));
  apply(config.rules);
  for (const override of config.overrides ?? []) {
    if (matches(override.files) && !matches(override.excludeFiles)) apply(override.rules);
  }
  return levels;
}

function severity(value: unknown): Level | undefined {
  if (value === "error" || value === "deny" || value === 2) return "error";
  if (value === "warn" || value === 1) return "warning";
  if (value === "off" || value === "allow" || value === 0) return undefined;
  throw new Error(`unknown rule severity ${JSON.stringify(value)}`);
}

async function jsPlugins(config: OxlintConfig): Promise<Map<string, Plugin & { readonly specifier: string }>> {
  const loaded = new Map<string, Plugin & { readonly specifier: string }>();
  for (const entry of config.jsPlugins ?? []) {
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Oxlint's ExternalPluginEntry is a bare specifier string or a named entry.
    if (typeof entry === "string") throw new Error(`unnamed JS plugin ${entry}`);
    if (entry.name === "@sarj") continue;
    // Bare specifiers resolve from this script, inside the package that installs the plugins.
    const module = (await import(entry.specifier)) as { default?: Plugin } & Plugin;
    loaded.set(entry.name, { rules: (module.default ?? module).rules, specifier: entry.specifier });
  }
  return loaded;
}

function nativeRules(): Map<string, { readonly fix: string; readonly docsUrl: string }> {
  const result = spawnSync(OXLINT_BIN, ["--rules", "-f", "json"], { encoding: "utf8", maxBuffer: 1 << 26 });
  if (result.status !== 0) throw new Error(`oxlint --rules failed: ${result.stderr}`);
  const rules = NativeRulesSchema.parse(JSON.parse(result.stdout));
  // `--rules` spells plugin scopes with underscores (jsx_a11y); configs use hyphens.
  return new Map(
    rules.map((rule) => [
      rule.scope === "eslint" ? rule.value : `${rule.scope.replaceAll("_", "-")}/${rule.value}`,
      { fix: rule.fix, docsUrl: rule["docs_url"] },
    ]),
  );
}

function nativeDescription(
  displayId: string,
  native: ReadonlyMap<string, { readonly fix: string; readonly docsUrl: string }>,
  summaries: Readonly<Record<string, string>>,
): Description {
  const rule = native.get(displayId);
  if (rule === undefined) throw new Error(`${displayId} is not a native Oxlint rule`);
  const summary = summaries[displayId];
  if (summary === undefined) throw new Error(`add a summary for ${displayId} to scripts/oxlint-native-rule-summaries.json`);
  return {
    summary,
    docsUrl: rule.docsUrl,
    autofix: rule.fix.includes("fix") ? "available" : "none",
    hasSuggestions: rule.fix.includes("suggestion"),
  };
}

function pluginDescription(displayId: string, meta: RuleMeta | undefined, coreSummary: string | undefined): Description {
  if (meta === undefined) throw new Error(`missing installed metadata for ${displayId}`);
  const autofix = meta.fixable === undefined || meta.fixable === null ? "none" : "available";
  const hasSuggestions = meta.hasSuggestions === true;
  if (coreSummary !== undefined) {
    return { summary: coreSummary, docsUrl: `https://eslint.org/docs/latest/rules/${splitRule(displayId).id}`, autofix, hasSuggestions };
  }
  const docs = PluginDocsSchema.safeParse(meta.docs);
  if (!docs.success) throw new Error(`invalid docs metadata for ${displayId}`, { cause: docs.error });
  return { summary: plainTextSummary(docs.data.description), docsUrl: docs.data.url, autofix, hasSuggestions };
}

function splitRule(ruleId: string): { namespace: string; id: string } {
  const slash = ruleId.lastIndexOf("/");
  return slash === -1 ? { namespace: "eslint", id: ruleId } : { namespace: ruleId.slice(0, slash), id: ruleId.slice(slash + 1) };
}

/** A route-safe provider ID: `@tanstack/query` becomes `tanstack-query`. */
function providerId(namespace: string): string {
  return namespace.replace(/^@/u, "").replaceAll("/", "-");
}

function nativeProvider(namespace: string): { readonly label: string; readonly homepage: string } {
  const label = NATIVE_PLUGINS[namespace];
  if (label === undefined) throw new Error(`unknown native Oxlint plugin ${namespace}`);
  return { label, homepage: "https://oxc.rs/docs/guide/usage/linter/rules.html" };
}

function jsProvider(namespace: string): { readonly label: string; readonly homepage: string } {
  const entry = JS_PLUGINS[namespace];
  if (entry === undefined) throw new Error(`unknown JS plugin ${namespace}`);
  return entry;
}

function plainTextSummary(value: string): string {
  return value
    .replaceAll(/\[([^\]]+)\]\([^\s)]+(?:\s+"[^"]*")?\)/gu, "$1")
    .replaceAll(/\s+/gu, " ")
    .trim();
}

await project();
