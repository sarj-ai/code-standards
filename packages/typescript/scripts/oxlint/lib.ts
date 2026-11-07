// Shared helpers for the scripts in this folder: corpora, config generation,
// running Oxlint with a clean environment, and parsing its JSON output.

import { spawnSync } from "node:child_process";
import { access, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const PACKAGE_DIR = resolve(fileURLToPath(new URL("../..", import.meta.url)));
export const PORT_PLUGIN = join(PACKAGE_DIR, "dist/index.js");
const OXLINT_BIN = join(PACKAGE_DIR, "node_modules/.bin/oxlint");

// Checkouts of the Sarj repositories linted as corpora.
const SARJ_REPOS = process.env["SARJ_REPOS"] ?? join(homedir(), "Developer/sarj");

interface Corpus {
  readonly name: string;
  readonly cwd: string;
}

/** An Oxlint rule setting: a severity, or a severity with options. */
type RuleSetting = string | readonly unknown[];
export type RuleSettings = Readonly<Record<string, RuleSetting>>;

/** One diagnostic of Oxlint's JSON output that carries a rule code. */
export interface Finding {
  readonly filename: string;
  readonly rule: string;
  readonly offset: number;
  readonly message: string;
}

/** A diagnostic without a rule code: a plugin crash or a file Oxlint cannot parse. */
export interface Problem {
  readonly filename: string;
  readonly message: string;
}

export interface ParsedOutput {
  readonly findings: Finding[];
  readonly crashes: Problem[];
  readonly parseErrors: Problem[];
  readonly files: number;
}

interface OxlintRun {
  readonly ms: number;
  readonly stdout: string;
  readonly stderr: string;
}

interface Timings {
  readonly rules: Readonly<Record<string, number>>;
  readonly totalMs: number | null;
}

/** Options parsed from `--key value` or `--key=value` pairs. */
type Args<Key extends string> = Partial<Record<Key, string>>;

interface OxlintOptions {
  readonly configPath: string;
  readonly cwd: string;
  readonly format?: string;
  readonly extraArgs?: readonly string[];
  readonly env?: Readonly<Record<string, string>>;
}

interface OxlintDiagnostic {
  readonly filename: string;
  readonly code?: string;
  readonly message: string;
  readonly labels?: readonly { readonly span?: { readonly offset?: number } }[];
}

interface OxlintOutput {
  readonly diagnostics: readonly OxlintDiagnostic[];
  readonly "number_of_files": number;
}

// Platform keeps oxlint-suppressions.json at its root, and Oxlint reads that
// file from the working directory, so Platform is linted one folder at a time.
const CORPORA: readonly Corpus[] = [
  ...["products", "libraries", "tests", "scripts", "iac"].map((folder) => ({
    name: `platform/${folder}`,
    cwd: join(SARJ_REPOS, "platform", folder),
  })),
  ...["banking", "automations", "ai", "wiki", "wiki-internal", "design", "portal", "code-standards"].map((repo) => ({
    name: repo,
    cwd: join(SARJ_REPOS, repo),
  })),
];

const IGNORE_PATTERNS = [
  "**/node_modules/**",
  "**/dist/**",
  "**/build/**",
  "**/out/**",
  "**/coverage/**",
  "**/.next/**",
  "**/.open-next/**",
  "**/.wrangler/**",
  "**/generated/**",
  "**/__generated__/**",
  "**/vendor/**",
  "**/*.min.{js,mjs,cjs}",
  "**/.yarn/**",
] as const;

const CATEGORIES_OFF = Object.fromEntries(
  ["correctness", "suspicious", "pedantic", "perf", "style", "restriction", "nursery"].map((category) => [category, "off"]),
);

// Oxlint reports a JS plugin exception and a file it cannot parse both as
// diagnostics without a rule code. Only the first is a plugin crash.
const PLUGIN_CRASH = "Error running JS plugin.";

/**
 * Write an Oxlint config that loads one plugin build as `@sarj` (so inline
 * `@sarj/...` disable comments in the corpora apply) and enables only `rules`.
 * `rules` maps rule names (without prefix) to an Oxlint rule setting.
 */
export async function writeConfig(pluginPath: string, rules: RuleSettings): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "sarj-oxlint-"));
  const config = {
    plugins: [],
    categories: CATEGORIES_OFF,
    jsPlugins: [{ name: "@sarj", specifier: pluginPath }],
    rules: Object.fromEntries(Object.entries(rules).map(([name, setting]) => [`@sarj/${name}`, setting])),
    options: { typeAware: false },
  };
  const path = join(dir, "oxlint.json");
  await writeFile(path, JSON.stringify(config, null, 2));
  return path;
}

/** Run Oxlint once. Returns wall time and raw output. */
export function runOxlint({ configPath, cwd, format = "json", extraArgs = [], env = {} }: OxlintOptions): OxlintRun {
  // Config ignorePatterns resolve against the temp config's folder, so they
  // never match corpus files; pass them relative to the corpus instead.
  const ignores = IGNORE_PATTERNS.map((pattern) => `--ignore-pattern=${pattern}`);
  const args = ["-c", configPath, "--disable-nested-config", ...ignores, "-f", format, ...extraArgs, "."];
  const start = process.hrtime.bigint();
  const result = spawnSync(OXLINT_BIN, args, { cwd, env: cleanEnv(env), encoding: "utf8", maxBuffer: 1 << 30 });
  const ms = Number(process.hrtime.bigint() - start) / 1e6;
  if (result.error !== undefined) throw result.error;
  // Exit 1 means findings; anything else is a failure of the run itself.
  if (result.status !== 0 && result.status !== 1) {
    throw new Error(`oxlint exited ${String(result.status)} in ${cwd}\n${result.stderr}\n${result.stdout.slice(0, 2000)}`);
  }
  return { ms, stdout: result.stdout, stderr: result.stderr };
}

// Oxlint changes its output when it detects an AI agent (CLAUDECODE and
// friends hide --debug=timings), so run it with a minimal environment.
function cleanEnv(extra: Readonly<Record<string, string>>): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { HOME: process.env["HOME"], PATH: process.env["PATH"], ...extra };
  const temporary = process.env["TMPDIR"];
  if (temporary !== undefined && temporary !== "") env["TMPDIR"] = temporary;
  return env;
}

/** Split Oxlint JSON output into findings, plugin crashes and parse errors. */
export function parseJson(stdout: string): ParsedOutput {
  const data = JSON.parse(stdout) as OxlintOutput;
  const findings: Finding[] = [];
  const crashes: Problem[] = [];
  const parseErrors: Problem[] = [];
  for (const diagnostic of data.diagnostics) {
    if (diagnostic.code !== undefined && diagnostic.code !== "") {
      findings.push({
        filename: diagnostic.filename,
        rule: diagnostic.code,
        offset: diagnostic.labels?.[0]?.span?.offset ?? -1,
        message: diagnostic.message,
      });
    } else {
      const problem = { filename: diagnostic.filename, message: diagnostic.message.split("\n").slice(0, 3).join(" | ") };
      (diagnostic.message.startsWith(PLUGIN_CRASH) ? crashes : parseErrors).push(problem);
    }
  }
  return { findings, crashes, parseErrors, files: data["number_of_files"] };
}

export function findingKey(finding: Finding): string {
  return `${finding.filename}\u0000${finding.rule}\u0000${String(finding.offset)}\u0000${finding.message}`;
}

/** Parse the `--debug=timings` table into { rule: ms } plus the JS total. */
export function parseTimings(text: string): Timings {
  const rules: Record<string, number> = {};
  for (const line of text.split("\n")) {
    const match = /^@sarj\/(?<rule>\S+)\s+(?<ms>[\d.]+)\s+[\d.]+%\s+\d+\s+js-plugin\s*$/.exec(line);
    if (match?.groups !== undefined) rules[match.groups["rule"] ?? ""] = Number(match.groups["ms"]);
  }
  const total = /Total:\s+(?<ms>[\d.]+)ms/.exec(text)?.groups?.["ms"];
  return { rules, totalMs: total === undefined ? null : Number(total) };
}

export function median(values: readonly number[]): number {
  const sorted = values.toSorted((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] ?? Number.NaN : ((sorted[mid - 1] ?? Number.NaN) + (sorted[mid] ?? Number.NaN)) / 2;
}

export function parseArgs<Key extends string>(argv: readonly string[], defaults: Args<Key>): Args<Key> {
  const options: Record<string, string | undefined> = { ...defaults };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === undefined || !arg.startsWith("--")) throw new Error(`unexpected argument ${String(arg)}`);
    const [key = "", inline] = arg.slice(2).split("=", 2);
    const value = inline ?? argv[++i];
    options[key] = value;
  }
  return options as Args<Key>;
}

/** The checked-out corpora, selected by a comma-separated list of names or name prefixes. */
export async function selectCorpora(filter: string | undefined): Promise<readonly Corpus[]> {
  const wanted = filter === undefined || filter === "" ? null : filter.split(",");
  const selected = CORPORA.filter((corpus) => wanted?.some((name) => corpus.name === name || corpus.name.startsWith(`${name}/`)) ?? true);
  const present = await Promise.all(selected.map(async (corpus) => exists(corpus.cwd)));
  return selected.filter((_, index) => present[index] === true);
}

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Read `--settings`: inline JSON or a path to a JSON file, mapping rule names
 * (with or without the `@sarj/` prefix, as in Platform's config) to Oxlint rule settings.
 */
export async function readRuleSettings(value: string | undefined): Promise<RuleSettings> {
  if (value === undefined || value === "") return {};
  const raw = JSON.parse(value.trimStart().startsWith("{") ? value : await readFile(value, "utf8")) as RuleSettings;
  return Object.fromEntries(Object.entries(raw).map(([name, setting]) => [name.replace(/^@sarj\//, ""), setting]));
}
