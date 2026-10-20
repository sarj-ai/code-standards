import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { relative, resolve, sep } from "node:path";

import type { ESLint as NativeESLint } from "eslint";
import { record, strings } from "./tool-json.mts";

import format from "./eslint-compact-formatter.mts";

// Resolve the consumer's installed ESLint, including workspace hoisting and PnP.
const require = createRequire(resolve("package.json"));
const { ESLint } = require("eslint") as typeof import("eslint");
const argument = process.argv[2];
if (argument === undefined)
  throw new Error("Selected ESLint request is required");
const rawRequest = record(
  JSON.parse(argument) as unknown,
  "Selected ESLint request",
);
const configPath = rawRequest["config"];
if (configPath !== null && typeof configPath !== "string")
  throw new Error("Selected ESLint config must be a path or null");
const request = {
  full: rawRequest["full"] === true,
  consoleOutput: rawRequest["consoleOutput"] === true,
  failOnWarnings: rawRequest["failOnWarnings"] === true,
  rules: strings(rawRequest["rules"], "Selected ESLint rules"),
  config: configPath,
  upstreamRules: strings(
    rawRequest["upstreamRules"] ?? [],
    "Selected upstream rules",
  ),
  upstreamAdvisories: strings(
    rawRequest["upstreamAdvisories"] ?? [],
    "Selected upstream advisories",
  ),
  passOnUnpruned: rawRequest["passOnUnpruned"] === true,
};
const selected = new Set([
  ...request.rules.map((rule) => `@sarj/${rule}`),
  ...(request.upstreamRules ?? []),
]);
const options: NativeESLint.Options = {
  cwd: process.cwd(),
  ...(request.config === null ? {} : { overrideConfigFile: request.config }),
  // A partial rule run cannot validate whether unrelated inline directives are
  // needed. Full lint owns those checks; live selected suppressions still apply.
  ...(request.full
    ? {}
    : {
        overrideConfig: {
          linterOptions: {
            reportUnusedDisableDirectives: "off",
            reportUnusedInlineConfigs: "off",
          },
        },
      }),
  cache: false,
  warnIgnored: false,
  applySuppressions: true,
  // Preserve repository parsers, plugins, options, and suppressions;
  // the predicate prevents unrelated rule visitors from running.
  ...(request.full
    ? {}
    : { ruleFilter: ({ ruleId }: { ruleId: string }) => selected.has(ruleId) }),
};
const eslint = new ESLint(options);
const files = process.argv.slice(4);
const advisories = request.upstreamAdvisories ?? [];
let results: NativeESLint.LintResult[];
if (advisories.length === 0) {
  results = await eslint.lintFiles(files);
} else {
  const packages: Record<string, string> = {
    "@sarj": "@sarj/eslint-plugin",
    vitest: "@vitest/eslint-plugin",
  };
  const namespaces = [
    ...new Set(advisories.map((rule) => rule.slice(0, rule.lastIndexOf("/")))),
  ];
  const groups = new Map<string, { missing: string[]; files: string[] }>();
  for (const file of files) {
    const configured: unknown = await eslint.calculateConfigForFile(file);
    const plugins =
      configured === undefined
        ? {}
        : record(
            record(configured, "effective ESLint config")["plugins"] ?? {},
            "effective ESLint plugins",
          );
    const missing =
      configured === undefined
        ? []
        : namespaces.filter((name) => !plugins[name]);
    const key = missing.join(",");
    const group = groups.get(key) ?? { missing, files: [] };
    group.files.push(file);
    groups.set(key, group);
  }
  results = [];
  for (const group of groups.values()) {
    const plugins = Object.fromEntries(
      group.missing.map((name) => {
        const packageName = packages[name];
        if (packageName === undefined)
          throw new Error(`Unsupported advisory namespace ${name}`);
        const loaded = require(packageName) as NativeESLint.Plugin & {
          readonly default?: NativeESLint.Plugin;
        };
        return [name, loaded.default ?? loaded];
      }),
    );
    const analyzer = new ESLint({
      ...options,
      overrideConfig: {
        ...options.overrideConfig,
        plugins,
        // Errors preserve bulk suppressions; advisories become warnings in the report.
        rules: Object.fromEntries(advisories.map((rule) => [rule, "error"])),
      },
    });
    results.push(...(await analyzer.lintFiles(group.files)));
  }
}
// ESLint's API applies bulk suppressions but leaves the CLI's unused check to
// callers. Check only rules that actually ran; unselected entries remain valid.
let unused = false;
if (!request.passOnUnpruned) {
  const suppressions = new Map<string, Map<string, { count: number }>>();
  try {
    const document = record(
      JSON.parse(await readFile("eslint-suppressions.json", "utf8")) as unknown,
      "ESLint suppressions",
    );
    for (const [path, value] of Object.entries(document)) {
      const entries = new Map<string, { count: number }>();
      for (const [id, entry] of Object.entries(
        record(value, "ESLint file suppressions"),
      )) {
        const count = record(entry, "ESLint suppression")["count"];
        if (typeof count !== "number" || !Number.isInteger(count) || count < 0)
          throw new Error(
            "ESLint suppression count must be a nonnegative integer",
          );
        entries.set(id, { count });
      }
      suppressions.set(path, entries);
    }
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ENOENT"))
      throw error;
  }
  unused = results.some((result) => {
    const file = relative(process.cwd(), result.filePath).split(sep).join("/");
    const actual = [
      ...result.messages,
      ...result.suppressedMessages.filter((message) =>
        message.suppressions.some((suppression) => suppression.kind === "file"),
      ),
    ];
    return [...(suppressions.get(file) ?? [])].some(
      ([ruleId, entry]) =>
        (request.full || selected.has(ruleId)) &&
        entry.count >
          actual.filter(
            (message) => message.ruleId === ruleId && message.severity === 2,
          ).length,
    );
  });
}
if (request.full) {
  const { requiredSuppressionResults } =
    await import("./eslint-required-policy.mts");
  const required = new Map(
    (
      await requiredSuppressionResults(results.map((result) => result.filePath))
    ).map((result) => [resolve(result.filePath), result]),
  );
  results = results.map((result) => {
    const policy = required.get(resolve(result.filePath));
    if (policy === undefined)
      throw new Error(
        "Required suppression policy missed a linted source file",
      );
    const key = (
      message: NativeESLint.LintResult["messages"][number],
    ): string =>
      JSON.stringify([
        message.ruleId,
        message.line,
        message.column,
        message.endLine,
        message.endColumn,
        message.message,
      ]);
    const messages = new Map(
      result.messages.map((message) => [key(message), message]),
    );
    for (const message of policy.messages) messages.set(key(message), message);
    const combined = [...messages.values()];
    return {
      ...result,
      messages: combined,
      errorCount: combined.filter((message) => message.severity === 2).length,
      warningCount: combined.filter((message) => message.severity === 1).length,
      fatalErrorCount: combined.filter((message) => message.fatal === true)
        .length,
    };
  });
}
process.stdout.write(
  request.consoleOutput
    ? await (await eslint.loadFormatter("stylish")).format(results)
    : format(results),
);
if (unused)
  process.stderr.write(
    "Selected ESLint rules have unused bulk suppressions; prune them or pass --pass-on-unpruned-suppressions.\n",
  );
process.exitCode =
  unused || results.some((result) => result.fatalErrorCount > 0)
    ? 2
    : results.some(
          (result) =>
            result.errorCount > 0 ||
            (request.failOnWarnings && result.warningCount > 0),
        )
      ? 1
      : 0;
