// Publish selected managed rules and explicit opt-in compatibility rules. Importing each full
// plugin also initializes unrelated rules, including rules that load ESLint.
// Normal builds verify and copy the reviewed rule bundles.
// sources.lock.json is provenance, not an install input for this package.
// To refresh, reconstruct a temporary package.json from that lock's packages[""]
// entry, copy the lock there as package-lock.json, and run npm ci --ignore-scripts.
// Then run this script with --refresh and SARJ_UPSTREAM_SOURCE set to that
// temporary installation. Its upstream peers include ESLint; keep it isolated.
import { readFile, readdir, writeFile, mkdir, copyFile } from "node:fs/promises";
import { hash } from "node:crypto";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

import { build, type Plugin } from "esbuild";

import { PACKAGE_DIR } from "./lib.ts";

const SNAPSHOTS = join(PACKAGE_DIR, "src/upstream");
const PLUGINS = [
  ["unicorn-js", "eslint-plugin-unicorn", "unicorn"],
  ["jsdoc-js", "eslint-plugin-jsdoc", "jsdoc"],
  ["react-js", "eslint-plugin-react", "react"],
  ["regexp", "eslint-plugin-regexp", "regexp"],
  ["security", "eslint-plugin-security", "security"],
  ["@tanstack/query", "@tanstack/eslint-plugin-query", "query"],
  ["effects", "eslint-plugin-react-you-might-not-need-an-effect", "effects"],
  ["node-test", "eslint-node-test", "node-test"],
  ["testing-library", "eslint-plugin-testing-library", "testing-library"],
  ["playwright", "eslint-plugin-playwright", "playwright"],
  ["@eslint-react", "@eslint-react/eslint-plugin", "react-correctness"],
  ["next-js", "@next/eslint-plugin-next", "next"],
] as const;

// Ordinary builds consume reviewed, engine-free snapshots. Upstream source
// packages and their required ESLint peers belong only to the refresh fixture.
if (!process.argv.includes("--refresh")) {
  const manifest = JSON.parse(await readFile(join(SNAPSHOTS, "manifest.json"), "utf8")) as {
    files: Record<string, string>;
    sourceLockSha256: string;
  };
  const sourceLock = await readFile(join(SNAPSHOTS, "sources.lock.json"));
  if (hash("sha256", sourceLock) !== manifest.sourceLockSha256)
    throw new Error("Upstream snapshot source lock integrity mismatch");
  for (const [file, digest] of Object.entries(manifest.files)) {
    const bytes = await readFile(join(SNAPSHOTS, file));
    if (hash("sha256", bytes) !== digest)
      throw new Error(`Upstream snapshot integrity mismatch: ${file}`);
    await copyFile(join(SNAPSHOTS, file), join(PACKAGE_DIR, "dist", file));
  }
  process.exit(0);
}
await mkdir(SNAPSHOTS, { recursive: true });
const sourceRoot = process.env["SARJ_UPSTREAM_SOURCE"];
if (!sourceRoot)
  throw new Error(
    "--refresh requires SARJ_UPSTREAM_SOURCE pointing to an isolated upstream source install",
  );
const resolveSource = (name: string): string =>
  createRequire(join(sourceRoot, "package.json")).resolve(name);
const PRESET = await readFile(
  join(PACKAGE_DIR, "../standards/src/sarj_standards/configs/oxlint.strict.mts"),
  "utf8",
);
// Rule tables precede createConfig; later settings use plugin-qualified keys too.
const RULE_IDS: readonly string[] = [
  ...new Set([
    ...[
      ...PRESET.split("export function createConfig")[0]!.matchAll(
        /"((?:unicorn-js|jsdoc-js|react-js|regexp|security|@tanstack\/query|effects|node-test|testing-library|playwright|@eslint-react)\/[^" ]+)"\s*:/gu,
      ),
    ].map((match) => match[1]!),
    // Existing authored policies can opt in without the full plugin's ESLint peer.
    "unicorn-js/prefer-https",
    "unicorn-js/prefer-switch",
  ]),
];
const ENGINE = /(?:^|\/)node_modules\/eslint\//u;
const BUILTIN_RULE_EXPORT = "export {default as getBuiltinRule} from './get-builtin-rule.js';";

// The utility barrel re-exports an engine helper unused by all selected rules.
// Exclude that export from this entrypoint, rather than substituting an engine
// implementation. A selected rule importing it will fail the build.
const SELECTED_UNICORN_UTILITIES: Plugin = {
  name: "selected-unicorn-utilities",
  setup(builder) {
    builder.onLoad(
      { filter: /eslint-plugin-unicorn\/rules\/utils\/index\.js$/ },
      async ({ path }) => {
        const source = await readFile(path, "utf8");
        if (!source.includes(BUILTIN_RULE_EXPORT))
          throw new Error(`Upstream utility exports changed: ${path}`);
        return { contents: source.replace(BUILTIN_RULE_EXPORT, ""), loader: "js" };
      },
    );
  },
};

// Oxlint supports messageId natively; React's engine-version probe is unnecessary.
const PURE_HELPERS: Plugin = {
  name: "pure-upstream-helpers",
  setup(builder) {
    builder.onLoad(
      {
        filter:
          /@next\/eslint-plugin-next\/dist\/rules\/no-location-assign-relative-destination\.js$/,
      },
      async ({ path }) => {
        const source = await readFile(path, "utf8");
        const signature = "function getStaticStringPrefix(node, sourceCode) {";
        const binaryRecursion = "getStaticStringPrefix(node.left, sourceCode)";
        const aliasRecursion = "getStaticStringPrefix(lastWriteExpr, sourceCode)";
        const ending = "    return null;\n}\n";
        if (
          !source.includes(signature) ||
          !source.includes(binaryRecursion) ||
          !source.includes(aliasRecursion) ||
          !source.endsWith(ending)
        )
          throw new Error(`Next prefix resolver changed: ${path}`);
        // Next 16.4.1 recurses forever on cyclic aliases. Track only the current
        // evaluation path; sibling/repeated evaluations and relative prefixes
        // retain upstream behavior. A cyclic branch has an unknown prefix.
        return {
          contents:
            source
              .replace(
                signature,
                `${signature.slice(0, -3)}, seen = new Set()) {\n    if (seen.has(node)) return null;\n    seen.add(node);\n    try {`,
              )
              .replace(binaryRecursion, "getStaticStringPrefix(node.left, sourceCode, seen)")
              .replace(aliasRecursion, "getStaticStringPrefix(lastWriteExpr, sourceCode, seen)")
              .slice(0, -ending.length) +
            "    return null;\n    } finally { seen.delete(node); }\n}\n",
          loader: "js",
        };
      },
    );
    builder.onLoad({ filter: /eslint-plugin-react\/lib\/util\/message\.js$/ }, async ({ path }) => {
      const source = await readFile(path, "utf8");
      if (!source.includes("semver.satisfies(eslintPkg.version, '>= 4.15')"))
        throw new Error(`React message helper changed: ${path}`);
      return {
        contents: "module.exports = (messageId, message) => messageId ? {messageId} : {message};",
        loader: "js",
      };
    });
    // Keep these equivalent initializers separate: the credential scanner
    // mistakes the minified chained assignment for a high-entropy API key.
    builder.onLoad(
      { filter: /@typescript-eslint\/visitor-keys\/dist\/index\.js$/ },
      async ({ path }) => {
        const source = await readFile(path, "utf8");
        const chained = "exports.visitorKeys = exports.getKeys = void 0;";
        if (!source.includes(chained)) throw new Error(`Visitor exports changed: ${path}`);
        return {
          contents: source.replace(
            chained,
            "exports.getKeys = void 0; exports.visitorKeys = void 0;",
          ),
          loader: "js",
        };
      },
    );
    builder.onLoad({ filter: /@typescript-eslint\/utils\/dist\/index\.js$/ }, ({ path }) => ({
      // Export the actual upstream functions used by Query and Testing Library.
      // The unused TSESLint barrel loads engine classes.
      contents: `export * from ${JSON.stringify(join(dirname(path), "ts-estree.js"))};
export * as ASTUtils from ${JSON.stringify(join(dirname(path), "ast-utils/index.js"))};
export * as ESLintUtils from ${JSON.stringify(join(dirname(path), "eslint-utils/index.js"))};`,
      loader: "js",
    }));
  },
};

for (const [alias, name, subpath] of PLUGINS) {
  // Refresh inputs are direct dependencies in the locked npm source fixture.
  const packageRoot = join(sourceRoot, "node_modules", name);
  const directRules = ["unicorn-js", "jsdoc-js", "react-js", "next-js"].includes(alias);
  const root =
    alias === "next-js"
      ? join(packageRoot, "dist")
      : directRules
        ? dirname(resolveSource(name))
        : packageRoot;
  // Next is an opt-in compatibility export, never part of the default profile.
  const rules = (
    alias === "next-js" ? ["next-js/no-location-assign-relative-destination"] : RULE_IDS
  )
    .filter((id) => id.startsWith(`${alias}/`))
    .map((id) => id.slice(alias.length + 1))
    .sort();
  const imports = rules.map((rule, index) => {
    const filename =
      alias !== "jsdoc-js"
        ? rule
        : rule.replaceAll(/-([a-z])/gu, (_, letter: string) => letter.toUpperCase());
    return `import rule${String(index)} from ${JSON.stringify(join(root, alias === "react-js" ? "lib/rules" : "rules", `${filename}.js`))};`;
  });
  const rawRules = `{${rules.map((rule, index) => `${JSON.stringify(rule)}:rule${String(index)}`).join(",")}}`;
  const upstream = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8")) as {
    name: string;
    version: string;
  };
  const conversion =
    alias === "unicorn-js"
      ? `import toEslintRules from ${JSON.stringify(join(root, "rules/rule/to-eslint-rules.js"))};\nconst rules=toEslintRules(${rawRules});`
      : directRules
        ? `const rules=${rawRules};`
        : `import plugin from ${JSON.stringify(name)};const rules=Object.fromEntries(${JSON.stringify(rules)}.map(id=>{if(!plugin.rules[id])throw new Error("Missing upstream rule: "+id);return [id,plugin.rules[id]]}));`;
  const result = await build({
    stdin: {
      contents: [
        ...(directRules ? imports : []),
        conversion,
        `export default {meta:${JSON.stringify({ name: upstream.name, version: upstream.version })},rules};`,
      ].join("\n"),
      resolveDir: sourceRoot,
    },
    absWorkingDir: PACKAGE_DIR,
    outfile: join(SNAPSHOTS, `${directRules && alias !== "next-js" ? alias : subpath}.js`),
    bundle: true,
    write: false,
    platform: "node",
    format: "esm",
    target: "node22",
    metafile: true,
    minify: true,
    legalComments: "none",
    // CSS Tree loads JSON data relative to its own module. Keep that pure
    // parser as a normal dependency so its data resolves after installation.
    external: ["@eslint/css-tree", "change-case", "typescript"],
    banner: {
      js: 'import {createRequire as sarjCreateRequire} from "node:module";const require=sarjCreateRequire(import.meta.url);',
    },
    plugins: [SELECTED_UNICORN_UTILITIES, PURE_HELPERS],
  });
  const inputs = Object.keys(result.metafile.inputs);
  if (inputs.some((input) => ENGINE.test(input)))
    throw new Error(`${alias} bundles the ESLint engine`);
  for (const output of result.outputFiles) await writeFile(output.path, output.contents);
  console.log(`${alias}: ${String(rules.length)} upstream rules, no ESLint engine`);
}

await copyFile(join(sourceRoot, "package-lock.json"), join(SNAPSHOTS, "sources.lock.json"));
const files: Record<string, string> = {};
for (const file of (await readdir(SNAPSHOTS)).filter((file) => /\.js$/u.test(file)).sort())
  files[file] = hash("sha256", await readFile(join(SNAPSHOTS, file)));
await writeFile(
  join(SNAPSHOTS, "manifest.json"),
  `${JSON.stringify(
    {
      sources: PLUGINS.map(([alias, name, subpath]) => ({ alias, name, subpath })),
      sourceLockSha256: hash("sha256", await readFile(join(SNAPSHOTS, "sources.lock.json"))),
      files,
    },
    null,
    2,
  )}\n`,
);
