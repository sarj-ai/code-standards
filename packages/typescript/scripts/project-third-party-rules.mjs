import { builtinRules } from "eslint/use-at-your-own-risk";
import { ESLint } from "eslint";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(PACKAGE_ROOT, "../..");
const CONFIG_ROOT = join(REPOSITORY_ROOT, "packages/standards/src/sarj_standards/configs");
const CACHE_PREFIX = join(PACKAGE_ROOT, "node_modules/.cache/sarj-third-party-catalog-");

const CONTEXTS = [
  ["source-ts", "TypeScript source", "src/example.ts"],
  ["source-tsx", "React source", "src/example.tsx"],
  ["source-js", "JavaScript source", "src/example.js"],
  ["source-jsx", "React JavaScript source", "src/example.jsx"],
  ["test-ts", "TypeScript tests", "tests/example.test.ts"],
  ["config-ts", "Syntax-only tool configuration", "vite.config.ts"],
  ["design-system-tsx", "Design-system React source", "src/components/ui/example.tsx"],
];

const PROVIDERS = {
  eslint: ["ESLint", "eslint", "https://eslint.org/"],
  "typescript-eslint": ["typescript-eslint", "typescript-eslint", "https://typescript-eslint.io/"],
  react: ["React", "eslint-plugin-react", "https://github.com/jsx-eslint/eslint-plugin-react"],
  "react-hooks": ["React Hooks", "eslint-plugin-react-hooks", "https://react.dev/reference/eslint-plugin-react-hooks"],
  unicorn: ["Unicorn", "eslint-plugin-unicorn", "https://github.com/sindresorhus/eslint-plugin-unicorn"],
  "eslint-comments": ["ESLint Comments", "@eslint-community/eslint-plugin-eslint-comments", "https://eslint-community.github.io/eslint-plugin-eslint-comments/"],
  n: ["Node.js", "eslint-plugin-n", "https://github.com/eslint-community/eslint-plugin-n"],
  perfectionist: ["Perfectionist", "eslint-plugin-perfectionist", "https://perfectionist.dev/"],
  promise: ["Promise", "eslint-plugin-promise", "https://github.com/eslint-community/eslint-plugin-promise"],
  "simple-import-sort": ["Simple Import Sort", "eslint-plugin-simple-import-sort", "https://github.com/lydell/eslint-plugin-simple-import-sort"],
  "better-tailwindcss": ["Better Tailwind CSS", "eslint-plugin-better-tailwindcss", "https://github.com/schoero/eslint-plugin-better-tailwindcss"],
  zod: ["ESLint Zod", "eslint-plugin-zod", "https://github.com/marcalexiei/eslint-zod"],
};

const namespaceToProvider = (namespace) => ({
  "@typescript-eslint": "typescript-eslint",
  "@eslint-community/eslint-comments": "eslint-comments",
}[namespace] ?? namespace);

const level = (setting) => {
  const severity = Array.isArray(setting) ? setting[0] : setting;
  if (severity === 2 || severity === "error") return "error";
  if (severity === 1 || severity === "warn" || severity === "warning") return "warning";
  return undefined;
};

const splitRule = (displayId) => {
  if (!displayId.includes("/")) return ["eslint", displayId, undefined];
  if (displayId.startsWith("@typescript-eslint/")) {
    return ["typescript-eslint", displayId.slice("@typescript-eslint/".length), "@typescript-eslint"];
  }
  if (displayId.startsWith("@eslint-community/eslint-comments/")) {
    return ["eslint-comments", displayId.slice("@eslint-community/eslint-comments/".length), "@eslint-community/eslint-comments"];
  }
  if (displayId.startsWith("@sarj/")) return ["@sarj", displayId.slice("@sarj/".length), "@sarj"];
  const [namespace, ...parts] = displayId.split("/");
  return [namespaceToProvider(namespace), parts.join("/"), namespace];
};

async function loadProfiles() {
  await mkdir(dirname(CACHE_PREFIX), { recursive: true });
  const cacheRoot = await mkdtemp(CACHE_PREFIX);
  const profiles = {};
  try {
    for (const name of ["application", "strict"]) {
      const destination = join(cacheRoot, `eslint.${name}.mjs`);
      const source = await readFile(join(CONFIG_ROOT, `eslint.${name}.mjs`), "utf8");
      const localSarj = pathToFileURL(join(PACKAGE_ROOT, "dist/index.js")).href;
      const rewritten = source.replace('from "@sarj/eslint-plugin"', `from "${localSarj}"`);
      if (rewritten === source) throw new Error(`could not resolve local @sarj import in eslint.${name}.mjs`);
      await writeFile(destination, rewritten, "utf8");
      const module = await import(`${pathToFileURL(destination).href}?catalog=1`);
      profiles[name === "strict" ? "standard" : name] = module.createConfig({
        projectService: true,
        tsconfigRootDir: REPOSITORY_ROOT,
      });
    }
    return profiles;
  } finally {
    await rm(cacheRoot, { recursive: true, force: true });
  }
}

async function project() {
  const profiles = await loadProfiles();
  const peers = JSON.parse(await readFile(join(CONFIG_ROOT, "eslint.peers.json"), "utf8")).peers;
  const registries = { eslint: builtinRules };
  for (const configs of Object.values(profiles)) {
    for (const config of configs) {
      for (const [namespace, plugin] of Object.entries(config.plugins ?? {})) {
        const provider = namespaceToProvider(namespace);
        if (provider !== "@sarj") registries[provider] = plugin.rules ?? {};
      }
    }
  }

  const records = new Map();
  for (const [profile, configs] of Object.entries(profiles)) {
    const eslint = new ESLint({ cwd: REPOSITORY_ROOT, overrideConfigFile: true, overrideConfig: configs });
    for (const [contextId, contextLabel, path] of CONTEXTS) {
      const effective = await eslint.calculateConfigForFile(path);
      for (const [displayId, setting] of Object.entries(effective?.rules ?? {})) {
        const effectiveLevel = level(setting);
        if (effectiveLevel === undefined) continue;
        const [provider, id] = splitRule(displayId);
        if (provider === "@sarj") continue;
        if (!(provider in PROVIDERS)) throw new Error(`unknown configured ESLint provider: ${provider}`);
        const rule = provider === "eslint" ? registries.eslint.get(id) : registries[provider]?.[id];
        if (rule === undefined) throw new Error(`missing installed metadata for ${displayId}`);
        const rawSummary = rule.meta?.docs?.description;
        const docsUrl = rule.meta?.docs?.url;
        if (typeof rawSummary !== "string" || rawSummary.length === 0) throw new Error(`missing summary for ${displayId}`);
        const summary = plainTextSummary(rawSummary);
        if (typeof docsUrl !== "string" || !docsUrl.startsWith("https://")) throw new Error(`missing HTTPS docs URL for ${displayId}`);
        const key = `${provider}:${id}`;
        let record = records.get(key);
        if (record === undefined) {
          record = {
            key,
            provider,
            id,
            displayId,
            summary,
            docsUrl,
            family: null,
            autofix: rule.meta?.fixable === undefined ? "none" : "available",
            hasSuggestions: rule.meta?.hasSuggestions === true,
            profiles: new Map(),
          };
          records.set(key, record);
        }
        const contexts = record.profiles.get(profile) ?? [];
        contexts.push({ id: contextId, label: contextLabel, level: effectiveLevel });
        record.profiles.set(profile, contexts);
      }
    }
  }

  const providers = Object.entries(PROVIDERS).map(([id, [label, packageName, homepage]]) => ({
    id,
    label,
    engine: "eslint",
    package: packageName,
    version: peers[packageName],
    homepage,
  }));
  const rules = [...records.values()].sort((left, right) => left.key.localeCompare(right.key)).map((record) => ({
    ...record,
    profiles: [...record.profiles.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([name, contexts]) => ({ name, contexts })),
  }));
  process.stdout.write(`${JSON.stringify({ providers, rules })}\n`);
}

function plainTextSummary(value) {
  return value
    .replaceAll(/\[([^\]]+)\]\([^\s)]+(?:\s+"[^"]*")?\)/gu, "$1")
    .replaceAll(/\s+/gu, " ")
    .trim();
}

await project();
