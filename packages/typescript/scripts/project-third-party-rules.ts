import { builtinRules } from "eslint/use-at-your-own-risk";
import { ESLint, type Linter } from "eslint";
import { record } from "../../standards/src/sarj_standards/configs/tool-json.mts";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(PACKAGE_ROOT, "../..");
const CONFIG_ROOT = join(
  REPOSITORY_ROOT,
  "packages/standards/src/sarj_standards/configs",
);
const CACHE_PREFIX = join(
  PACKAGE_ROOT,
  "node_modules/.cache/sarj-third-party-catalog-",
);

const CONTEXTS = [
  ["source-ts", "TypeScript source", "src/example.ts"],
  ["source-tsx", "React source", "src/example.tsx"],
  ["source-js", "JavaScript source", "src/example.js"],
  ["source-jsx", "React JavaScript source", "src/example.jsx"],
  ["test-ts", "TypeScript tests", "tests/example.test.ts"],
  ["test-bun-ts", "Bun tests", "tests/example.bun.test.ts"],
  [
    "test-playwright-ts",
    "Playwright end-to-end tests",
    "tests/example.playwright.ts",
  ],
  ["config-ts", "Syntax-only tool configuration", "vite.config.ts"],
  [
    "design-system-tsx",
    "Design-system React source",
    "src/components/ui/example.tsx",
  ],
] as const;

interface RuleMetadata {
  readonly meta?:
    | {
        readonly docs?:
          | { readonly description?: unknown; readonly url?: unknown }
          | undefined;
        readonly fixable?: unknown;
        readonly hasSuggestions?: unknown;
      }
    | undefined;
}
interface ProjectedRule {
  key: string;
  provider: string;
  id: string;
  displayId: string;
  summary: string;
  docsUrl: string;
  family: null;
  autofix: "none" | "available";
  hasSuggestions: boolean;
  profiles: Map<
    string,
    { id: string; label: string; level: "error" | "warning" }[]
  >;
}

const PROVIDERS: Record<string, readonly [string, string, string]> = {
  eslint: ["ESLint", "eslint", "https://eslint.org/"],
  "typescript-eslint": [
    "typescript-eslint",
    "typescript-eslint",
    "https://typescript-eslint.io/",
  ],
  react: [
    "React",
    "eslint-plugin-react",
    "https://github.com/jsx-eslint/eslint-plugin-react",
  ],
  "react-hooks": [
    "React Hooks",
    "eslint-plugin-react-hooks",
    "https://react.dev/reference/eslint-plugin-react-hooks",
  ],
  unicorn: [
    "Unicorn",
    "eslint-plugin-unicorn",
    "https://github.com/sindresorhus/eslint-plugin-unicorn",
  ],
  regexp: [
    "RegExp",
    "eslint-plugin-regexp",
    "https://ota-meshi.github.io/eslint-plugin-regexp/",
  ],
  "eslint-comments": [
    "ESLint Comments",
    "@eslint-community/eslint-plugin-eslint-comments",
    "https://eslint-community.github.io/eslint-plugin-eslint-comments/",
  ],
  n: [
    "Node.js",
    "eslint-plugin-n",
    "https://github.com/eslint-community/eslint-plugin-n",
  ],
  perfectionist: [
    "Perfectionist",
    "eslint-plugin-perfectionist",
    "https://perfectionist.dev/",
  ],
  promise: [
    "Promise",
    "eslint-plugin-promise",
    "https://github.com/eslint-community/eslint-plugin-promise",
  ],
  "simple-import-sort": [
    "Simple Import Sort",
    "eslint-plugin-simple-import-sort",
    "https://github.com/lydell/eslint-plugin-simple-import-sort",
  ],
  "better-tailwindcss": [
    "Better Tailwind CSS",
    "eslint-plugin-better-tailwindcss",
    "https://github.com/schoero/eslint-plugin-better-tailwindcss",
  ],
  jsdoc: [
    "JSDoc",
    "eslint-plugin-jsdoc",
    "https://github.com/gajus/eslint-plugin-jsdoc",
  ],
  shadcn: ["shadcn", "@shadcn/lint", "https://github.com/shadcn-ui/lint"],
  vitest: [
    "Vitest",
    "@vitest/eslint-plugin",
    "https://github.com/vitest-dev/eslint-plugin-vitest",
  ],
  "node-test": [
    "Node Test",
    "eslint-node-test",
    "https://github.com/sindresorhus/eslint-node-test",
  ],
  jest: [
    "Jest / Bun Test",
    "eslint-plugin-jest",
    "https://github.com/jest-community/eslint-plugin-jest",
  ],
  "testing-library": [
    "Testing Library",
    "eslint-plugin-testing-library",
    "https://github.com/testing-library/eslint-plugin-testing-library",
  ],
  playwright: [
    "Playwright",
    "eslint-plugin-playwright",
    "https://github.com/mskelton/eslint-plugin-playwright",
  ],
  zod: [
    "ESLint Zod",
    "eslint-plugin-zod",
    "https://github.com/marcalexiei/eslint-zod",
  ],
};

const namespaceToProvider = (namespace: string): string => {
  const aliases: Record<string, string> = {
    "@typescript-eslint": "typescript-eslint",
    "@eslint-community/eslint-comments": "eslint-comments",
  };
  return aliases[namespace] ?? namespace;
};

async function project() {
  const profiles = await loadProfiles();
  const peerManifest = record(
    JSON.parse(
      await readFile(join(CONFIG_ROOT, "eslint.peers.json"), "utf8"),
    ) as unknown,
    "ESLint peers",
  );
  const peers = record(peerManifest["peers"], "ESLint peer versions");
  const registries = installedRegistries(profiles);
  const records = new Map<string, ProjectedRule>();
  for (const [profile, configs] of Object.entries(profiles)) {
    const eslint = new ESLint({
      cwd: REPOSITORY_ROOT,
      overrideConfigFile: true,
      overrideConfig: configs,
    });
    for (const [contextId, contextLabel, path] of CONTEXTS) {
      const configured: unknown = await eslint.calculateConfigForFile(path);
      const effective = record(configured, `effective config for ${path}`);
      const rules = record(
        effective["rules"] ?? {},
        `effective rules for ${path}`,
      );
      for (const [displayId, setting] of Object.entries(rules)) {
        const effectiveLevel = level(setting);
        const { provider, id } = splitRule(displayId);
        if (effectiveLevel === undefined || provider === "@sarj") continue;
        const key = `${provider}:${id}`;
        const projected =
          records.get(key) ??
          projectedRule(displayId, provider, id, registries);
        records.set(key, projected);
        const contexts = projected.profiles.get(profile) ?? [];
        contexts.push({
          id: contextId,
          label: contextLabel,
          level: effectiveLevel,
        });
        projected.profiles.set(profile, contexts);
      }
    }
  }
  const providers = Object.entries(PROVIDERS).map(
    ([id, [label, packageName, homepage]]) => {
      const version = peers[packageName];
      if (typeof version !== "string")
        throw new Error(`missing installed peer version for ${packageName}`);
      return {
        id,
        label,
        engine: "eslint",
        package: packageName,
        version,
        homepage,
      };
    },
  );
  const rules = [...records.values()]
    .sort((left, right) => left.key.localeCompare(right.key))
    .map((entry) => ({
      ...entry,
      profiles: [...entry.profiles.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, contexts]) => ({ name, contexts })),
    }));
  process.stdout.write(`${JSON.stringify({ providers, rules })}\n`);
}

async function loadProfiles(): Promise<Record<string, Linter.Config[]>> {
  await mkdir(dirname(CACHE_PREFIX), { recursive: true });
  const cacheRoot = await mkdtemp(CACHE_PREFIX);
  const profiles: Record<string, Linter.Config[]> = {};
  try {
    for (const name of ["strict"]) {
      const destination = join(cacheRoot, `eslint.${name}.mjs`);
      const source = await readFile(
        join(CONFIG_ROOT, `eslint.${name}.mjs`),
        "utf8",
      );
      const localSarj = pathToFileURL(join(PACKAGE_ROOT, "dist/index.js")).href;
      const rewritten = source.replace(
        'from "@sarj/eslint-plugin"',
        `from "${localSarj}"`,
      );
      if (rewritten === source)
        throw new Error(
          `could not resolve local @sarj import in eslint.${name}.mjs`,
        );
      await writeFile(destination, rewritten, "utf8");
      const module = (await import(
        `${pathToFileURL(destination).href}?catalog=1`
      )) as {
        createConfig(options: {
          projectService: boolean;
          tsconfigRootDir: string;
          testFrameworks: string[];
        }): Linter.Config[];
      };
      profiles["standard"] = module.createConfig({
        projectService: true,
        tsconfigRootDir: REPOSITORY_ROOT,
        testFrameworks: [
          "vitest",
          "bun",
          "node",
          "testing-library",
          "playwright",
        ],
      });
      // Version-one catalog labels remain compatible; both expose one policy.
      profiles["application"] = profiles["standard"];
    }
    return profiles;
  } finally {
    await rm(cacheRoot, { recursive: true, force: true });
  }
}

function installedRegistries(
  profiles: Readonly<Record<string, Linter.Config[]>>,
): Record<string, Record<string, RuleMetadata>> {
  const registries: Record<string, Record<string, RuleMetadata>> = {
    eslint: Object.fromEntries(builtinRules),
  };
  for (const configs of Object.values(profiles)) {
    for (const config of configs) {
      for (const [namespace, plugin] of Object.entries(config.plugins ?? {})) {
        const provider = namespaceToProvider(namespace);
        if (provider === "@sarj") continue;
        registries[provider] = installedPluginRules(plugin);
      }
    }
  }
  return registries;
}

function installedPluginRules(
  plugin: ESLint.Plugin,
): Record<string, RuleMetadata> {
  return Object.fromEntries(
    Object.entries(plugin.rules ?? {}).flatMap(([id, definition]) =>
      typeof definition === "object" && definition !== null
        ? [[id, { meta: definition.meta }]]
        : [],
    ),
  );
}

function projectedRule(
  displayId: string,
  provider: string,
  id: string,
  registries: Readonly<Record<string, Readonly<Record<string, RuleMetadata>>>>,
): ProjectedRule {
  if (!(provider in PROVIDERS))
    throw new Error(`unknown configured ESLint provider: ${provider}`);
  const rule = registries[provider]?.[id];
  if (rule === undefined)
    throw new Error(`missing installed metadata for ${displayId}`);
  const rawSummary = rule.meta?.docs?.description;
  const docsUrl = rule.meta?.docs?.url;
  if (typeof rawSummary !== "string" || rawSummary.length === 0)
    throw new Error(`missing summary for ${displayId}`);
  if (typeof docsUrl !== "string" || !docsUrl.startsWith("https://"))
    throw new Error(`missing HTTPS docs URL for ${displayId}`);
  return {
    key: `${provider}:${id}`,
    provider,
    id,
    displayId,
    summary: plainTextSummary(rawSummary),
    docsUrl,
    family: null,
    autofix: rule.meta?.fixable === undefined ? "none" : "available",
    hasSuggestions: rule.meta?.hasSuggestions === true,
    profiles: new Map(),
  };
}

function level(setting: unknown): "error" | "warning" | undefined {
  const severity: unknown = Array.isArray(setting) ? setting[0] : setting;
  if (severity === 2 || severity === "error") return "error";
  if (severity === 1 || severity === "warn" || severity === "warning")
    return "warning";
  return undefined;
}

function splitRule(displayId: string): { provider: string; id: string } {
  if (!displayId.includes("/")) return { provider: "eslint", id: displayId };
  for (const namespace of [
    "@typescript-eslint",
    "@eslint-community/eslint-comments",
    "@sarj",
  ]) {
    if (displayId.startsWith(`${namespace}/`))
      return {
        provider: namespaceToProvider(namespace),
        id: displayId.slice(namespace.length + 1),
      };
  }
  const [namespace, ...parts] = displayId.split("/");
  return {
    provider: namespaceToProvider(namespace ?? ""),
    id: parts.join("/"),
  };
}

function plainTextSummary(value: string) {
  return value
    .replaceAll(/\[([^\]]+)\]\([^\s)]+(?:\s+"[^"]*")?\)/gu, "$1")
    .replaceAll(/\s+/gu, " ")
    .trim();
}

await project();
