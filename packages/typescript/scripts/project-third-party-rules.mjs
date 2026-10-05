import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createStrictOxlintConfig } from "../dist/config.js";
import { TESTING_LIBRARY_REACT_RECOMMENDED_RULES } from "../dist/presets.js";

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(PACKAGE_ROOT, "../..");
const CLI = join(
  dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const [
  manifest,
  aggregateProvenance,
  playwrightProvenance,
  testingLibraryProvenance,
] = await Promise.all(
  [
    "package.json",
    "vendor/PROVENANCE.json",
    "vendor/playwright/PROVENANCE.json",
    "vendor/testing-library/PROVENANCE.json",
  ].map(async (path) =>
    JSON.parse(await readFile(join(PACKAGE_ROOT, path), "utf8")),
  ),
);
const provenance = {
  ...aggregateProvenance,
  playwright: playwrightProvenance,
  "testing-library": testingLibraryProvenance,
};

async function project() {
  const native = new Map(
    run(["--rules", "--format=json"]).map((rule) => [
      `${rule.scope.replaceAll("_", "-")}/${rule.value}`,
      rule,
    ]),
  );
  const cacheParent = join(PACKAGE_ROOT, "node_modules/.cache");
  await mkdir(cacheParent, { recursive: true });
  const temporary = await mkdtemp(join(cacheParent, "sarj-native-catalog-"));
  try {
    const { policy, expanded, classOrdering } = await loadPolicy(temporary);
    const registries = await loadRegistries(policy);
    const providers = new Map();
    const records = new Map();
    for (const context of configurationGroups(
      policy,
      expanded,
      classOrdering,
    )) {
      for (const [configuredId, setting] of Object.entries(
        context.rules ?? {},
      )) {
        includeRule(
          configuredId,
          setting,
          context,
          native,
          registries,
          providers,
          records,
        );
      }
    }
    const rules = [...records.values()]
      .sort((left, right) => left.key.localeCompare(right.key))
      .map(({ contexts, ...record }) => ({
        ...record,
        profiles: ["application", "standard"].map((name) => ({
          name,
          contexts,
        })),
      }));
    const orderedProviders = [...providers.values()].sort((left, right) =>
      left.id.localeCompare(right.id),
    );
    process.stdout.write(
      `${JSON.stringify({ providers: orderedProviders, rules })}\n`,
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

function run(arguments_) {
  return JSON.parse(
    execFileSync(process.execPath, [CLI, ...arguments_], {
      cwd: PACKAGE_ROOT,
      encoding: "utf8",
      timeout: 30_000,
      maxBuffer: 16 * 1024 * 1024,
    }),
  );
}

async function loadPolicy(temporary) {
  const baseline = await createStrictOxlintConfig({
    root: REPOSITORY_ROOT,
    query: true,
    nextjs: true,
    sonarjs: true,
    testFrameworks: ["vitest", "bun", "node", "testing-library", "playwright"],
  });
  const classOrdering = {
    files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
    rules: { "perfectionist/sort-classes": "error" },
  };
  const policy = {
    ...baseline,
    overrides: [
      ...(baseline.overrides ?? []),
      {
        files: ["**/*.{test,spec}.tsx"],
        rules: TESTING_LIBRARY_REACT_RECOMMENDED_RULES,
      },
      classOrdering,
    ],
  };
  const config = join(temporary, ".oxlintrc.json");
  await writeFile(config, JSON.stringify(policy));
  // The engine validates every configured plugin and expands native categories.
  // Its serializer currently omits some JavaScript rules, so the public native
  // configuration remains the source of their exact declarations and options.
  const expanded = run(["--config", config, "--print-config"]);
  return { policy, expanded, classOrdering };
}

async function loadRegistries(policy) {
  const registries = new Map();
  for (const plugin of policy.jsPlugins ?? []) {
    const specifier = typeof plugin === "string" ? plugin : plugin.specifier;
    const module = await import(specifier);
    const implementation = module.default ?? module;
    const namespace =
      typeof plugin === "string" ? implementation.meta.name : plugin.name;
    registries.set(namespace, implementation.rules);
  }
  return registries;
}

function configurationGroups(policy, expanded, classOrdering) {
  // These are native configuration groups, not an emulation of file matching.
  // Oxlint's public CLI does not expose an effective per-file configuration API.
  return [
    {
      id: "base",
      label: "Base native configuration",
      rules: canonicalRules({ ...expanded.rules, ...policy.rules }),
    },
    ...(policy.overrides ?? []).map((override, index) => ({
      id: `override-${index + 1}`,
      label:
        override === classOrdering
          ? "Explicit class ordering opt-in (JavaScript and TypeScript)"
          : `Native override: ${override.files.join(", ")}`,
      rules: canonicalRules(override.rules ?? {}),
    })),
  ];
}

function canonicalRules(rules) {
  return Object.fromEntries(
    Object.entries(rules).map(([id, setting]) => [canonicalRule(id), setting]),
  );
}

function includeRule(
  configuredId,
  setting,
  context,
  native,
  registries,
  providers,
  records,
) {
  const severity = level(setting);
  // Authored Sarj and React Doctor rules have separate metadata projections.
  if (
    severity === undefined ||
    configuredId.startsWith("@sarj/") ||
    configuredId.startsWith("react-doctor/")
  )
    return;
  const displayId = canonicalRule(configuredId);
  const separator = displayId.indexOf("/");
  const namespace = displayId.slice(0, separator);
  const id = displayId.slice(separator + 1);
  const nativeRule = native.get(displayId);
  const pluginRule = registries.get(namespace)?.[id];
  if (nativeRule === undefined && pluginRule === undefined)
    throw new Error(
      `configured rule has no native implementation: ${displayId}`,
    );
  const provider = namespace === "eslint" ? "oxlint" : namespace;
  if (!providers.has(provider))
    providers.set(
      provider,
      providerRecord(provider, namespace, nativeRule, pluginRule),
    );
  const key = `${provider}:${id}`;
  let record = records.get(key);
  if (record === undefined) {
    record = ruleRecord(key, provider, id, displayId, nativeRule, pluginRule);
    records.set(key, record);
  }
  record.contexts.push({
    id: context.id,
    label: context.label,
    level: severity,
  });
}

function level(setting) {
  const severity = Array.isArray(setting) ? setting[0] : setting;
  if ([2, "error", "deny"].includes(severity)) return "error";
  if ([1, "warn", "warning"].includes(severity)) return "warning";
  return undefined;
}

function canonicalRule(id) {
  if (!id.includes("/")) return `eslint/${id}`;
  return id.replace(/^(jsx_a11y|react_perf)\//u, (scope) =>
    scope.replaceAll("_", "-"),
  );
}

function providerRecord(provider, namespace, nativeRule, pluginRule) {
  const sourceFamily = namespace.replace(/^sarj-/u, "");
  const source =
    nativeRule === undefined ? provenance[sourceFamily] : undefined;
  const packageName =
    source?.package ?? providerPackage(namespace, nativeRule !== undefined);
  return {
    id: provider,
    label:
      nativeRule !== undefined
        ? `Oxlint ${namespace} rules`
        : `${sourceFamily} source policies`,
    engine: "oxlint",
    package: packageName,
    version:
      (source?.package === undefined ? undefined : source.version) ??
      manifest.dependencies[packageName] ??
      manifest.devDependencies[packageName] ??
      manifest.version,
    homepage:
      nativeRule !== undefined
        ? "https://oxc.rs/docs/guide/usage/linter/"
        : (sourceHomepage(source?.source) ?? pluginRule.meta.docs?.url),
    projectionScope: "config-explicit",
  };
}

function sourceHomepage(source) {
  return typeof source === "string" ? source : source?.url;
}

function providerPackage(namespace, isNative) {
  if (isNative) return "oxlint";
  if (namespace === "sarj-react-hooks") return "@sarj/oxlint-react-hooks";
  return "@sarj/oxlint-plugin";
}

function ruleRecord(key, provider, id, displayId, nativeRule, pluginRule) {
  const docsUrl = nativeRule?.["docs_url"] ?? pluginRule.meta.docs?.url;
  if (typeof docsUrl !== "string" || !docsUrl.startsWith("https://"))
    throw new Error(`missing upstream HTTPS documentation for ${displayId}`);
  const fix = fixMetadata(nativeRule, pluginRule);
  return {
    key,
    provider,
    id,
    displayId,
    summary: plainText(pluginRule?.meta.docs?.description ?? title(id)),
    docsUrl,
    family: nativeRule?.category ?? null,
    ...fix,
    contexts: [],
  };
}

function fixMetadata(nativeRule, pluginRule) {
  if (nativeRule !== undefined)
    return {
      autofix: nativeRule.fix.includes("fix") ? "available" : "none",
      hasSuggestions: nativeRule.fix.includes("suggestion"),
    };
  return {
    autofix: pluginRule.meta.fixable === undefined ? "none" : "available",
    hasSuggestions: pluginRule.meta.hasSuggestions === true,
  };
}

function plainText(value) {
  return value
    .replaceAll(/\[([^\]]+)\]\([^\s)]+(?:\s+"[^"]*")?\)/gu, "$1")
    .replaceAll(/\s+/gu, " ")
    .trim();
}

function title(id) {
  const words = id.replaceAll("-", " ");
  if (words.startsWith("no ")) return `Disallow ${words.slice(3)}.`;
  return `${words[0].toUpperCase()}${words.slice(1)}.`;
}

await project();
