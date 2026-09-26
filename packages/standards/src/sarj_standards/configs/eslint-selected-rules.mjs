import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { relative, resolve, sep } from "node:path";

import format from "./eslint-compact-formatter.mjs";

// Resolve the consumer's installed ESLint, including workspace hoisting and PnP.
const require = createRequire(resolve("package.json"));
const { ESLint } = require("eslint");
const request = JSON.parse(process.argv[2]);
const selected = new Set(request.rules.map((rule) => `@sarj/${rule}`));
const eslint = new ESLint({
  cwd: process.cwd(),
  ...(request.config === null ? {} : { overrideConfigFile: request.config }),
  cache: false,
  warnIgnored: false,
  applySuppressions: true,
  // ESLint preserves each file's parser, plugins, options, severity and inline
  // directives; the predicate prevents unrelated rule visitors from running.
  ruleFilter: ({ ruleId }) => selected.has(ruleId),
});
const results = await eslint.lintFiles(process.argv.slice(4));
// ESLint's API applies bulk suppressions but leaves the CLI's unused check to
// callers. Check only rules that actually ran; unselected entries remain valid.
let unused = false;
if (!request.passOnUnpruned) {
  let suppressions = {};
  try {
    suppressions = JSON.parse(await readFile("eslint-suppressions.json", "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  unused = results.some((result) => {
    const file = relative(process.cwd(), result.filePath).split(sep).join("/");
    const actual = [...result.messages, ...result.suppressedMessages.filter((message) =>
      message.suppressions.some((suppression) => suppression.kind === "file"))];
    return Object.entries(suppressions[file] ?? {}).some(([ruleId, entry]) =>
      selected.has(ruleId) && entry.count > actual.filter((message) =>
        message.ruleId === ruleId && message.severity === 2).length);
  });
}
process.stdout.write(format(results));
if (unused) process.stderr.write("Selected ESLint rules have unused bulk suppressions; prune them or pass --pass-on-unpruned-suppressions.\n");
process.exitCode = unused || results.some((result) => result.fatalErrorCount > 0)
  ? 2
  : results.some((result) => result.errorCount > 0) ? 1 : 0;
