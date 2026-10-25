import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { hash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, extname, resolve } from "node:path";
import process from "node:process";
import { text as readStreamText } from "node:stream/consumers";

import { format as prettierFormat, type Plugin } from "prettier";
import type { ExampleFile, Rule, RuleExample } from "../src/lib/catalog.ts";
import type { CliCommand } from "../src/lib/cli.ts";
import { validateCatalog } from "../src/lib/catalog-validation.ts";
import { parseReference } from "../src/lib/parse-reference.ts";
import { record, text } from "./_json.ts";
import * as prettierPluginSh from "prettier-plugin-sh";
import prettierPluginToml from "prettier-plugin-toml";
import { format as sqlFormat } from "sql-formatter";

const FENCE_PATHS: Readonly<Record<string, string>> = {
  bash: "example.sh",
  hcl: "example.hcl",
  javascript: "example.js",
  js: "example.js",
  json: "example.json",
  markdown: "example.md",
  md: "example.md",
  python: "example.py",
  py: "example.py",
  sh: "example.sh",
  shell: "example.sh",
  sql: "example.sql",
  terraform: "example.tf",
  toml: "example.toml",
  ts: "example.ts",
  tsx: "example.tsx",
  typescript: "example.ts",
  yaml: "example.yml",
  yml: "example.yml",
};

const appRoot = resolve(import.meta.dirname, "..");
const repositoryRoot = resolve(appRoot, "../..");
const catalogPath = resolve(
  repositoryRoot,
  "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
);
const cliPath = resolve(
  repositoryRoot,
  "packages/standards/src/sarj_standards/configs/cli-reference.v1.json",
);
const docsProjectionPath = resolve(
  appRoot,
  "src/generated/formatted-code.v1.json",
);
const mode = process.argv[2];

if (mode !== "--check" && mode !== "--write" && mode !== "--format-json") {
  throw new Error(
    "usage: node scripts/format-code-examples.ts --check|--write|--format-json",
  );
}

const cache = new Map<string, string>();
const ruffVersion = "0.17.2";

assert.equal(
  execFileSync(
    resolve(repositoryRoot, "packages/standards/.venv/bin/ruff"),
    ["--version"],
    { encoding: "utf8" },
  ).trim(),
  `ruff ${ruffVersion}`,
  `formatted code requires repository-pinned Ruff ${ruffVersion}`,
);
assert.match(
  execFileSync("terraform", ["version"], { encoding: "utf8" }),
  /^Terraform v1\.17\.0\b/u,
  "formatted code requires Terraform 1.17.0",
);

function sha256(source: string) {
  return hash("sha256", source, "hex");
}

async function installedVersion(packageName: string) {
  const metadata = record(
    JSON.parse(
      await readFile(
        resolve(appRoot, "node_modules", packageName, "package.json"),
        "utf8",
      ),
    ) as unknown,
    "formatter package",
  );
  assert.equal(
    metadata["name"],
    packageName,
    "formatter package identity mismatch",
  );
  const version = text(metadata["version"], "formatter version");
  assert.match(version, /^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/u);
  return version;
}

function normalize(source: string) {
  return `${source.replaceAll("\r\n", "\n").replaceAll("\r", "\n").trimEnd()}\n`;
}

// eslint-disable-next-line @sarj/stepdown -- adapter helpers precede the dispatcher they make readable.
function runFormatter(
  command: string,
  args: string[],
  source: string,
  label: string,
) {
  try {
    return execFileSync(command, args, {
      cwd: repositoryRoot,
      encoding: "utf8",
      input: normalize(source),
      maxBuffer: 1024 * 1024,
      timeout: 30_000,
    });
  } catch (error) {
    const stderr =
      error && typeof error === "object" && "stderr" in error
        ? String(error.stderr).trim()
        : "";
    throw new Error(`${label} formatter failed${stderr ? `: ${stderr}` : ""}`, {
      cause: error,
    });
  }
}

function virtualPath(path: string) {
  const lower = path.toLowerCase();
  if (lower.endsWith(".tftest.hcl")) return "example.tftest.hcl";
  const extension = extname(lower);
  return `example${extension || ".txt"}`;
}

async function formatMarkdownFences(
  source: string,
  context: string,
): Promise<string> {
  const fencePattern = /```([A-Za-z0-9_-]*)\n([\s\S]*?)```/gu;
  const output = [];
  let offset = 0;
  for (const match of source.matchAll(fencePattern)) {
    output.push(source.slice(offset, match.index));
    const language = match[1];
    if (!language)
      throw new Error(
        `${context}: nonempty Markdown code fences require a language`,
      );
    const path = languageForFence(language);
    if (!path)
      throw new Error(
        `${context}: unsupported Markdown fence language ${language}`,
      );
    const formatted = await formatCode(
      match.at(2) ?? "",
      path,
      `${context} fenced ${language}`,
    );
    output.push(`\`\`\`${language}\n${formatted}\`\`\``);
    offset = match.index + match[0].length;
  }
  output.push(source.slice(offset));
  return output.join("");
}

function languageForFence(language: string) {
  return FENCE_PATHS[language.toLowerCase()];
}

async function formatWithPrettier(
  source: string,
  path: string,
  context: string,
): Promise<string> {
  const lower = path.toLowerCase();
  let parser;
  let plugins: Plugin[] = [];
  if (/\.(?:ts|cts|mts)$/u.test(lower)) parser = "typescript";
  else if (lower.endsWith(".tsx")) parser = "typescript";
  else if (/\.(?:js|cjs|mjs)$/u.test(lower)) parser = "babel";
  else if (lower.endsWith(".jsx")) parser = "babel";
  else if (lower.endsWith(".json")) parser = "json";
  else if (lower.endsWith(".jsonc")) parser = "json-stringify";
  else if (/\.(?:yaml|yml)$/u.test(lower)) parser = "yaml";
  else if (/\.(?:md|mdx)$/u.test(lower)) {
    parser = lower.endsWith(".mdx") ? "mdx" : "markdown";
    source = await formatMarkdownFences(source, context);
  } else if (lower.endsWith(".toml")) {
    parser = "toml";
    plugins = [prettierPluginToml];
  } else if (/\.(?:sh|bash|zsh)$/u.test(lower)) {
    parser = "sh";
    plugins = [prettierPluginSh];
  }
  if (!parser)
    throw new Error(
      `${context}: no formatter is registered for ${basename(path)}`,
    );
  return prettierFormat(normalize(source), {
    filepath: virtualPath(path),
    parser,
    plugins,
    printWidth: 88,
    tabWidth: 2,
  });
}

async function formatCode(
  source: string,
  path: string,
  context: string,
): Promise<string> {
  if (typeof source !== "string" || source.length === 0)
    throw new TypeError(`${context}: source must be nonempty`);
  if (source.length > 64 * 1024)
    throw new Error(`${context}: source exceeds the 64 KiB display limit`);
  if (path.includes("\0"))
    throw new Error(`${context}: path contains a NUL byte`);
  const lower = path.toLowerCase();
  const cacheKey = `${lower}\0${source}`;
  const cached = cache.get(cacheKey);
  if (cached !== undefined) return cached;

  // Make has no pinned formatter; recipe tabs and trailing variable spaces are semantic.
  // Match the DevOps execution-block basenames without expanding unsupported extensions.
  if (["makefile", "gnumakefile"].includes(basename(lower))) {
    if (!source.endsWith("\n"))
      throw new Error(`${context}: Make source must end with a newline`);
    cache.set(cacheKey, source);
    return source;
  }

  let formatted;
  if (lower.endsWith("/.git/keep") || lower === ".git/keep") {
    formatted = normalize(source);
  } else if (lower.endsWith(".py") || lower.endsWith(".pyi")) {
    formatted = runFormatter(
      resolve(repositoryRoot, "packages/standards/.venv/bin/ruff"),
      ["format", "--isolated", "--stdin-filename", virtualPath(path), "-"],
      source,
      context,
    );
  } else if (
    lower.endsWith(".tf") ||
    lower.endsWith(".tfvars") ||
    lower.endsWith(".hcl") ||
    lower.endsWith(".tftest.hcl")
  ) {
    formatted = runFormatter("terraform", ["fmt", "-"], source, context);
  } else if (lower.endsWith(".sql")) {
    formatted = sqlFormat(normalize(source), {
      language: "postgresql",
      keywordCase: "upper",
      tabWidth: 2,
    });
  } else {
    formatted = await formatWithPrettier(source, path, context);
  }

  const normalized = normalize(formatted);
  cache.set(cacheKey, normalized);
  return normalized;
}

async function formatFile(file: ExampleFile, context: string) {
  const source = await formatCode(
    file.source,
    file.path,
    `${context} (${file.path})`,
  );
  const secondPass = await formatCode(
    source,
    file.path,
    `${context} idempotence (${file.path})`,
  );
  assert.equal(
    secondPass,
    source,
    `${context} (${file.path}): formatter is not idempotent`,
  );
  return {
    ...file,
    source,
  };
}

async function formatJson() {
  const request: unknown = JSON.parse(await readStreamText(process.stdin));
  assert(Array.isArray(request), "format JSON input must be a file array");
  const files = await Promise.all(
    request.map((value: unknown, index: number) => {
      const file = record(value, `format JSON file ${String(index)}`);
      assert.deepEqual(Object.keys(file).sort(), ["path", "source"]);
      const path = text(file["path"], "format JSON path");
      const source = file["source"];
      assert(typeof source === "string", "format JSON source must be a string");
      // Empty native output is represented only for this display comparison.
      // The caller retains the original raw bytes for convergence and analysis.
      return formatFile({ path, source: source || "\n" }, "format JSON");
    }),
  );
  process.stdout.write(render(files));
}

async function formatExample(rule: Rule, example: RuleExample) {
  const context = `${rule.key}/${example.id}/${example.outcome}`;
  return {
    ...example,
    files: await Promise.all(
      example.files.map((file) => formatFile(file, `${context}/files`)),
    ),
    fixedFiles: await Promise.all(
      example.fixedFiles.map((file) =>
        formatFile(file, `${context}/fixedFiles`),
      ),
    ),
  };
}

function flattenCommands(commands: CliCommand[]): CliCommand[] {
  return commands.flatMap((command) => [
    command,
    ...flattenCommands(command.commands),
  ]);
}

if (mode === "--format-json") await formatJson();
else {
  const catalogSource = await readFile(catalogPath, "utf8");
  const cliSource = await readFile(cliPath, "utf8");
  const catalog: unknown = JSON.parse(catalogSource);
  validateCatalog(catalog);
  const cli = parseReference(JSON.parse(cliSource) as unknown);

  const rules: Record<
    string,
    { examples: RuleExample[]; optionsSchemaSource: string | null }
  > = {};
  let formattedFileCount = 0;
  const sourceFileCount = catalog.rules.reduce(
    (ruleCount, rule) =>
      ruleCount +
      rule.examples.reduce(
        (exampleCount, example) =>
          exampleCount + example.files.length + example.fixedFiles.length,
        0,
      ),
    0,
  );
  for (const rule of catalog.rules) {
    const examples = await Promise.all(
      rule.examples.map((example) => formatExample(rule, example)),
    );
    formattedFileCount += examples.reduce(
      (count, example) =>
        count + example.files.length + example.fixedFiles.length,
      0,
    );
    for (const scenarioId of new Set(
      examples.map((example) => example.scenarioId),
    )) {
      const before = examples.find(
        (example) =>
          example.scenarioId === scenarioId && example.outcome === "reject",
      );
      const after = examples.find(
        (example) =>
          example.scenarioId === scenarioId && example.outcome === "accept",
      );
      assert(before && after, `${rule.key}/${scenarioId}: incomplete comparison`);
      assert.notDeepEqual(
        before.files.map(({ path, source }) => ({ path, source })),
        after.files.map(({ path, source }) => ({ path, source })),
        `${rule.key}/${scenarioId}: formatting collapses before and after to the same code`,
      );
    }
    rules[rule.key] = {
      examples,
      optionsSchemaSource:
        rule.optionsSchema === null
          ? null
          : await formatCode(
              JSON.stringify(rule.optionsSchema),
              "options.json",
              `${rule.key}/optionsSchema`,
            ),
    };
  }
  assert.equal(
    formattedFileCount,
    sourceFileCount,
    "the formatted projection must cover every catalog file",
  );

  for (const [ruleKey, displayed] of Object.entries(rules)) {
    for (const example of displayed.examples) {
      for (const file of [...example.files, ...example.fixedFiles]) {
        assert(
          file.source.endsWith("\n"),
          `${ruleKey}/${example.id}/${file.path}: missing final newline`,
        );
        if (file.path.endsWith(".sql") && file.source.includes("cursor")) {
          assert.doesNotMatch(
            file.source,
            /:\s+cursor\b/u,
            `${ruleKey}/${example.id}: SQL placeholder was split`,
          );
        }
      }
    }
  }

  const quickSetupSource = [
    cli.launcher.install,
    `${cli.program} setup`,
    `${cli.program} doctor`,
    `${cli.program} check`,
  ].join("\n");
  const usage: Record<string, string> = {};
  for (const command of flattenCommands(cli.commands)) {
    usage[command.path.join("/")] = normalize(command.usage);
  }

  const docsProjection = {
    schemaVersion: 1,
    catalogSha256: sha256(catalogSource),
    cliSha256: sha256(cliSource),
    formatterVersions: {
      prettier: await installedVersion("prettier"),
      prettierPluginSh: await installedVersion("prettier-plugin-sh"),
      prettierPluginToml: await installedVersion("prettier-plugin-toml"),
      ruff: ruffVersion,
      sqlFormatter: await installedVersion("sql-formatter"),
      terraform: "1.17.0",
    },
    rules,
    static: {
      quickSetup: await formatCode(
        quickSetupSource,
        "quick-setup.sh",
        "home/quickSetup",
      ),
      runOnce: await formatCode(
        `${cli.launcher.runLatest} setup`,
        "run-once.sh",
        "cli/runOnce",
      ),
      bootstrap: await formatCode(
        '[ci]\nbootstrap = ["yarn generate", "uv run --project python generate-api"]',
        "bootstrap.toml",
        "cli/bootstrap",
      ),
      usage,
    },
  };

  await sync(docsProjectionPath, render(docsProjection));
}

function render(value: unknown) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

async function sync(path: string, expected: string) {
  let current = "";
  try {
    current = await readFile(path, "utf8");
  } catch (error) {
    if (!(
      error &&
      typeof error === "object" &&
      "code" in error &&
      error.code === "ENOENT"
    ))
      throw error;
  }
  if (current === expected) return;
  if (mode === "--check")
    throw new Error(`${path} is stale; run npm run code-examples:sync`);
  await mkdir(resolve(path, ".."), { recursive: true });
  await writeFile(path, expected);
}
