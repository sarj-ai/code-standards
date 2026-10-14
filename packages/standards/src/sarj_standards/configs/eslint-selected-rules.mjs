import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { relative, resolve, sep } from "node:path";

import format from "./eslint-compact-formatter.mjs";

// Resolve the consumer's installed ESLint, including workspace hoisting and PnP.
const require = createRequire(resolve("package.json"));
const { ESLint } = require("eslint");
const request = JSON.parse(process.argv[2]);
const selected = new Set([
  ...request.rules.map((rule) => `@sarj/${rule}`),
  ...(request.upstreamRules ?? []),
]);
const options = {
  cwd: process.cwd(),
  ...(request.config === null ? {} : { overrideConfigFile: request.config }),
  // A partial rule run cannot validate whether unrelated inline directives are
  // needed. Full lint owns those checks; live selected suppressions still apply.
  overrideConfig: {
    linterOptions: {
      reportUnusedDisableDirectives: "off",
      reportUnusedInlineConfigs: "off",
    },
  },
  cache: false,
  warnIgnored: false,
  applySuppressions: true,
  // Preserve repository parsers, plugins, options, and suppressions;
  // the predicate prevents unrelated rule visitors from running.
  ruleFilter: ({ ruleId }) => selected.has(ruleId),
};
const eslint = new ESLint(options);
const files = process.argv.slice(4);
const advisories = request.upstreamAdvisories ?? [];
let results;
if (advisories.length === 0) {
  results = await eslint.lintFiles(files);
} else {
  const packages = {
    "@sarj": "@sarj/eslint-plugin",
    vitest: "@vitest/eslint-plugin",
  };
  const namespaces = [
    ...new Set(advisories.map((rule) => rule.slice(0, rule.lastIndexOf("/")))),
  ];
  const groups = new Map();
  for (const file of files) {
    const config = await eslint.calculateConfigForFile(file);
    const missing = config
      ? namespaces.filter((name) => !config.plugins?.[name])
      : [];
    const key = missing.join(",");
    if (!groups.has(key)) groups.set(key, { missing, files: [] });
    groups.get(key).files.push(file);
  }
  results = [];
  for (const group of groups.values()) {
    const plugins = Object.fromEntries(
      group.missing.map((name) => {
        const loaded = require(packages[name]);
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
  let suppressions = {};
  try {
    suppressions = JSON.parse(
      await readFile("eslint-suppressions.json", "utf8"),
    );
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  unused = results.some((result) => {
    const file = relative(process.cwd(), result.filePath).split(sep).join("/");
    const actual = [
      ...result.messages,
      ...result.suppressedMessages.filter((message) =>
        message.suppressions.some((suppression) => suppression.kind === "file"),
      ),
    ];
    return Object.entries(suppressions[file] ?? {}).some(
      ([ruleId, entry]) =>
        selected.has(ruleId) &&
        entry.count >
          actual.filter(
            (message) => message.ruleId === ruleId && message.severity === 2,
          ).length,
    );
  });
}
process.stdout.write(format(results));
if (unused)
  process.stderr.write(
    "Selected ESLint rules have unused bulk suppressions; prune them or pass --pass-on-unpruned-suppressions.\n",
  );
process.exitCode =
  unused || results.some((result) => result.fatalErrorCount > 0)
    ? 2
    : results.some((result) => result.errorCount > 0)
      ? 1
      : 0;
