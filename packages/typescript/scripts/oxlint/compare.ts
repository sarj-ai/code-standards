#!/usr/bin/env node
// Compare two @sarj plugin builds under Oxlint: `--original` (for example a
// published release's dist/index.js) and `--port` (this checkout's build).
//
//   node scripts/oxlint/compare.ts --rules duplicate-test-body --original <plugin.js> [--runs 5]
//     [--port dist/index.js]
//     [--corpora platform,wiki] [--settings '{"rule":["error",{}]}' | rules.json]
//     [--env KEY=VALUE,...] [--no-callback-timings true] [--json out.json]
//
// Every corpus is linted by both builds with only the given rules on.
// `--settings` gives some of them an Oxlint rule setting (the rest run as
// "error"); without `--rules` it selects the rules itself. Parity means the
// same (filename, rule, offset, message) set on every corpus and no plugin
// crash on either side. Files Oxlint cannot parse are reported apart: they
// fail the same way on both sides and say nothing about the rules. Timing
// interleaves the two builds, alternating which goes first, and reports
// medians of the summed wall time across corpora. One extra --debug=timings
// run per side reports Oxlint's own JS callback time for the selected rules.

import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  PORT_PLUGIN,
  findingKey,
  median,
  parseArgs,
  parseJson,
  parseTimings,
  readRuleSettings,
  runOxlint,
  selectCorpora,
  writeConfig,
  type Finding,
  type ParsedOutput,
  type Problem,
} from "./lib.ts";

type Side = "original" | "port";

interface SideRun extends ParsedOutput {
  readonly ms: number;
}

interface SideRow {
  readonly files: number;
  readonly findings: number;
  readonly crashes: number;
  readonly parseErrors: number;
  readonly crashSamples: readonly Problem[];
  readonly stable: boolean;
  readonly medianMs: number;
  callbackMs?: number;
  jsTotalMs?: number | null;
}

interface SideSummary {
  readonly keys: ReadonlySet<string>;
  readonly list: readonly Finding[];
  readonly row: SideRow;
}

interface Options {
  readonly ruleNames: readonly string[];
  readonly runs: number;
  readonly corpora: Awaited<ReturnType<typeof selectCorpora>>;
  readonly env: Readonly<Record<string, string>>;
  readonly configs: Readonly<Record<Side, string>>;
  readonly callbackTimings: boolean;
  readonly json: string | undefined;
}

interface CorpusRow {
  readonly name: string;
  readonly original: SideRow;
  readonly port: SideRow;
  readonly parity: boolean;
  readonly onlyOriginal: readonly Finding[];
  readonly onlyPort: readonly Finding[];
  readonly onlyOriginalCount: number;
  readonly onlyPortCount: number;
}

const SIDES: readonly Side[] = ["original", "port"];

await main();

async function main(): Promise<void> {
  const options = await readOptions(process.argv.slice(2));
  const { ruleNames, runs, corpora, env, configs, callbackTimings } = options;
  const rows: CorpusRow[] = [];
  const totals: Record<Side, number[]> = { original: new Array<number>(runs).fill(0), port: new Array<number>(runs).fill(0) };
  for (const corpus of corpora) {
    const results = lintCorpus(corpus.cwd, runs, configs, env, totals);
    const row = corpusRow(corpus.name, summarize(results.original), summarize(results.port));
    if (callbackTimings) {
      for (const name of SIDES) Object.assign(row[name], callbackTimingsOf(configs[name], corpus.cwd, env, ruleNames));
    }
    rows.push(row);
    printRow(row);
  }

  const parity = rows.every((row) => row.parity);
  const t = {
    originalMedianMs: median(totals.original),
    portMedianMs: median(totals.port),
    originalCallbackMs: sum(rows, "original", "callbackMs"),
    portCallbackMs: sum(rows, "port", "callbackMs"),
    originalFindings: sum(rows, "original", "findings"),
    portFindings: sum(rows, "port", "findings"),
    parity,
  };
  console.log(`\n${parity ? "PARITY on every corpus" : "NO PARITY"} for ${ruleNames.join(", ")}`);
  console.log(`wall (median of ${String(runs)}, summed over ${String(corpora.length)} corpora): original ${t.originalMedianMs.toFixed(0)}ms, ` +
    `port ${t.portMedianMs.toFixed(0)}ms (${change(t.originalMedianMs, t.portMedianMs)})`);
  if (callbackTimings) {
    console.log(`rule callbacks (--debug=timings, one run): original ${t.originalCallbackMs.toFixed(1)}ms, ` +
      `port ${t.portCallbackMs.toFixed(1)}ms (${change(t.originalCallbackMs, t.portCallbackMs)})`);
  }
  if (options.json !== undefined) await writeFile(options.json, JSON.stringify({ rules: ruleNames, runs, corpora: rows, totals: t }, null, 2));
  process.exitCode = parity ? 0 : 1;
}

/** Parse and check the command line, and write one config per side. */
async function readOptions(argv: readonly string[]): Promise<Options> {
  const args = parseArgs<"rules" | "runs" | "original" | "port" | "corpora" | "settings" | "env" | "no-callback-timings" | "json">(
    argv,
    { runs: "5", port: PORT_PLUGIN },
  );
  if (args.original === undefined || args.original === "") throw new Error("--original is required");
  const settings = await readRuleSettings(args.settings);
  const ruleNames = args.rules !== undefined && args.rules !== "" ? args.rules.split(",") : Object.keys(settings);
  if (ruleNames.length === 0) throw new Error("--rules or --settings is required");
  const unlisted = Object.keys(settings).filter((name) => !ruleNames.includes(name));
  if (unlisted.length > 0) throw new Error(`--settings names rules missing from --rules: ${unlisted.join(", ")}`);
  const rules = Object.fromEntries(ruleNames.map((name) => [name, settings[name] ?? "error"]));
  return {
    ruleNames,
    runs: Number(args.runs),
    corpora: await selectCorpora(args.corpora),
    // --env KEY=VALUE[,KEY=VALUE] passes variables to Oxlint (for example SARJ_TYPE_AWARE=0).
    env: Object.fromEntries((args.env ?? "").split(",").filter(Boolean).map((pair) => pair.split("=", 2) as [string, string])),
    configs: {
      original: await writeConfig(resolve(args.original), rules),
      port: await writeConfig(resolve(args.port ?? ""), rules),
    },
    callbackTimings: args["no-callback-timings"] === undefined || args["no-callback-timings"] === "",
    json: args.json === "" ? undefined : args.json,
  };
}

/** Lint one corpus `runs` times per side, alternating which side goes first, and add each run's wall time to `totals`. */
function lintCorpus(
  cwd: string,
  runs: number,
  configs: Readonly<Record<Side, string>>,
  env: Readonly<Record<string, string>>,
  totals: Record<Side, number[]>,
): Record<Side, SideRun[]> {
  const results: Record<Side, SideRun[]> = { original: [], port: [] };
  for (let i = 0; i < runs; i++) {
    for (const name of i % 2 === 0 ? SIDES : SIDES.toReversed()) {
      const run = runOxlint({ configPath: configs[name], cwd, env });
      results[name].push({ ms: run.ms, ...parseJson(run.stdout) });
      totals[name][i] = (totals[name][i] ?? 0) + run.ms;
    }
  }
  return results;
}

function corpusRow(name: string, original: SideSummary, port: SideSummary): CorpusRow {
  const onlyOriginal = original.list.filter((finding) => !port.keys.has(findingKey(finding)));
  const onlyPort = port.list.filter((finding) => !original.keys.has(findingKey(finding)));
  return {
    name,
    original: original.row,
    port: port.row,
    parity: onlyOriginal.length === 0 && onlyPort.length === 0 && original.row.findings === port.row.findings && clean(original) && clean(port),
    onlyOriginal: onlyOriginal.slice(0, 10),
    onlyPort: onlyPort.slice(0, 10),
    onlyOriginalCount: onlyOriginal.length,
    onlyPortCount: onlyPort.length,
  };
}

function printRow(row: CorpusRow): void {
  console.log(`${row.parity ? "PARITY " : "DIFFER "} ${row.name.padEnd(22)} files ${String(row.original.files).padStart(5)}  ` +
    `original ${formatSide(row.original)}  port ${formatSide(row.port)}` +
    (row.parity ? "" : `  only-original ${String(row.onlyOriginalCount)} only-port ${String(row.onlyPortCount)}`));
  for (const finding of row.onlyOriginal.slice(0, 3)) console.log(`    - ${finding.filename}@${String(finding.offset)} ${finding.rule}: ${finding.message.slice(0, 120)}`);
  for (const finding of row.onlyPort.slice(0, 3)) console.log(`    + ${finding.filename}@${String(finding.offset)} ${finding.rule}: ${finding.message.slice(0, 120)}`);
  for (const name of SIDES) {
    for (const crash of row[name].crashSamples) console.log(`    ! ${name} crash ${crash.filename}: ${crash.message.slice(0, 200)}`);
  }
}

/** Summarize one side's runs on a corpus: the first run's results plus whether every run agreed. */
function summarize(sideRuns: readonly SideRun[]): SideSummary {
  const [first] = sideRuns;
  if (first === undefined) throw new Error("--runs must be at least 1");
  const keys = new Set(first.findings.map(findingKey));
  const stable = sideRuns.every((run) => run.findings.length === first.findings.length && run.findings.every((finding) => keys.has(findingKey(finding))));
  return {
    keys,
    list: first.findings,
    row: {
      files: first.files,
      findings: first.findings.length,
      crashes: first.crashes.length,
      parseErrors: first.parseErrors.length,
      crashSamples: first.crashes.slice(0, 3),
      stable,
      medianMs: median(sideRuns.map((run) => run.ms)),
    },
  };
}

function clean(side: SideSummary): boolean {
  return side.row.crashes === 0 && side.row.stable;
}

function callbackTimingsOf(
  configPath: string,
  cwd: string,
  env: Readonly<Record<string, string>>,
  ruleNames: readonly string[],
): { callbackMs: number; jsTotalMs: number | null } {
  const run = runOxlint({ configPath, cwd, format: "default", extraArgs: ["--debug=timings"], env });
  const timings = parseTimings(run.stdout + run.stderr);
  return { callbackMs: ruleNames.reduce((total, rule) => total + (timings.rules[rule] ?? 0), 0), jsTotalMs: timings.totalMs };
}

function formatSide(side: SideRow): string {
  return `${String(side.findings)}f ${String(side.crashes)}c` + (side.parseErrors > 0 ? ` ${String(side.parseErrors)}p` : "") + ` ${side.medianMs.toFixed(0)}ms` +
    (side.callbackMs === undefined ? "" : ` cb ${side.callbackMs.toFixed(1)}ms`);
}

function sum(rows: readonly CorpusRow[], name: Side, key: "callbackMs" | "findings"): number {
  return rows.reduce((total, row) => total + (row[name][key] ?? 0), 0);
}

function change(a: number, b: number): string {
  return `${(((b - a) / a) * 100).toFixed(1)}%`;
}
