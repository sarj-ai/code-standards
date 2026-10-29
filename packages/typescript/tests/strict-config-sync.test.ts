










import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin, {
  RENAMED_RULES,
  RETIRED_RULES,
  RULES,
} from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const STRICT_CONFIG_PATH = resolve(
  HERE,
  "../../standards/src/sarj_standards/configs/eslint.strict.ts",
);
const REPO_ROOT = resolve(HERE, "../../..");


function gitOutput(...args: readonly string[]): string {
  return execFileSync("git", ["-C", REPO_ROOT, ...args], {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
}

function warnIfHistoryIsMissing(log: string, recorded: number): void {
  if (log.trim().length !== 0 || recorded === 0) return;
  console.warn(
    `[strict-config-sync] history corroborates 0 of ${recorded} entries in _retired-rules.ts: ` +
    `\`git log --diff-filter=D\` over src/rules is empty at ${gitOutput("rev-parse", "--short", "HEAD").trim()}. ` +
    "The subset gate still catches a NEW deletion that forgets its entry; it cannot re-derive the existing ones. " +
    "Expected after a history rewrite — investigate if the history was not rewritten.",
  );
}
















function stripComments(source: string): string {
  const QUOTES = new Set(["'", '"', "`"]);
  const parts: string[] = [];
  let index = 0;

  function skipBlockComment(): void {
    index += 2;
    while (
      index < source.length &&
      !(source[index] === "*" && source[index + 1] === "/")
    ) {
      if (source[index] === "\n") parts.push("\n");
      index += 1;
    }
    index += 2;
  }

  function appendQuotedText(quote: string): void {
    parts.push(quote);
    index += 1;
    while (index < source.length && source[index] !== quote) {

      if (source[index] === "\\") {
        parts.push(source.slice(index, index + 2));
        index += 2;
        continue;
      }
      parts.push(source[index] ?? "");
      index += 1;
    }
    parts.push(quote);
    index += 1;
  }

  while (index < source.length) {
    const char = source[index] ?? "";
    const next = source[index + 1] ?? "";

    if (char === "/" && next === "/") {
      while (index < source.length && source[index] !== "\n") index += 1;
      continue;
    }

    if (char === "/" && next === "*") {
      skipBlockComment();
      continue;
    }

    if (QUOTES.has(char)) {
      appendQuotedText(char);
      continue;
    }

    parts.push(char);
    index += 1;
  }

  return parts.join("");
}


function referencedRuleNames(configText: string): string[] {

  return Array.from(
    stripComments(configText).matchAll(/"@sarj\/([a-z0-9-]+)"\s*:/gu),
    (match) => match[1] ?? "",
  );
}


function documentedRuleNames(configText: string): Set<string> {
  const comments = configText.match(/\/\/[^\n]*|\/\*[\s\S]*?\*\//gu) ?? [];
  return new Set(
    comments.flatMap((comment) =>
      Array.from(comment.matchAll(/@sarj\/([a-z0-9-]+)/gu), (match) => match[1] ?? ""),
    ),
  );
}









function baseSeverities(configText: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of stripComments(configText).matchAll(
    /"@sarj\/([a-z0-9-]+)"\s*:\s*"(\w+)"/gu,
  )) {
    const [, name, severity] = match;
    if (name !== undefined && severity !== undefined && !found.has(name)) {
      found.set(name, severity);
    }
  }
  return found;
}

describe("standards eslint.strict.ts stays wired to the plugin", () => {
  it("references only rule names that exist in the plugin's rules export", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = referencedRuleNames(text);
    expect(referenced.length).toBeGreaterThan(0);

    const known = new Set(Object.keys(RULES));
    const missing = referenced.filter((name) => !known.has(name));
    expect(missing).toEqual([]);
  });









  it("every plugin rule is either wired into the strict config or explicitly opted out", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = new Set(referencedRuleNames(text));
    const documented = documentedRuleNames(text);



    // eslint.strict.ts. Adding a name here is a deliberate act — it must come

    const PER_REPO_OPT_IN = new Set([
      "no-storage-in-stateless-modules",
    ]);

    const unwired = Object.keys(RULES)
      .filter((name) => !referenced.has(name) && !PER_REPO_OPT_IN.has(name))
      .sort();
    expect(unwired).toEqual([]);




    for (const name of PER_REPO_OPT_IN) {
      expect(documented).toContain(name);
    }




    const redundant = [...PER_REPO_OPT_IN].filter((name) =>
      referenced.has(name),
    );
    expect(redundant).toEqual([]);
  });

  it.each([
    { filename: "/repo/src/routes/handler.ts", expected: ["@sarj/no-raw-fetch-outside-clients"] },
    { filename: "/repo/src/clients/http-client.ts", expected: [] },
    { filename: "/repo/src/routes/handler.test.ts", expected: [] },
  ])("enforces the managed fetch default for $filename", ({ filename, expected }) => {
    const severity = baseSeverities(readFileSync(STRICT_CONFIG_PATH, "utf8"))
      .get("no-raw-fetch-outside-clients");
    if (severity !== "error") throw new Error("Managed fetch policy must be enabled at error");
    const messages = new Linter({ cwd: "/repo" }).verify(
      "const response = fetch('https://example.com/data');",
      {
        files: ["**/*.ts"],
        plugins: { "@sarj": plugin },
        rules: { "@sarj/no-raw-fetch-outside-clients": severity },
      },
      { filename },
    );
    expect(messages.map(message => message.ruleId)).toEqual(expected);
    expect(messages.every(message => message.severity === 2)).toBe(true);
  });













  it("severities match the plugin's own strict preset, except where declared", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const configured = baseSeverities(text);
    const pluginStrict = plugin.configs.strict.rules as Record<string, string>;




    const DECLARED_DEVIATIONS = new Map<string, readonly [string, string]>([]);

    const comparisons = Object.entries(pluginStrict).flatMap(([name, pluginSeverity]) => {
      const rule = name.replace("@sarj/", "");
      const configSeverity = configured.get(rule);
      return configSeverity === undefined ? [] : [{ configSeverity, pluginSeverity, rule }];
    });
    for (const { configSeverity, pluginSeverity, rule } of comparisons.filter(
      ({ rule }) => DECLARED_DEVIATIONS.has(rule),
    )) {
      const declared = DECLARED_DEVIATIONS.get(rule)!;
      expect([rule, pluginSeverity, configSeverity]).toEqual([
        rule,
        declared[0],
        declared[1],
      ]);
    }
    const drift = comparisons
      .filter(({ rule }) => !DECLARED_DEVIATIONS.has(rule))
      .filter(({ configSeverity, pluginSeverity }) => configSeverity !== pluginSeverity)
      .map(({ configSeverity, pluginSeverity, rule }) =>
        `${rule}: plugin=${pluginSeverity} config=${configSeverity}`
      );
    expect(drift).toEqual([]);
  });

  it("plugin meta.version matches package.json version", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(HERE, "../package.json"), "utf8"),
    ) as { version: string };
    expect(plugin.meta.version).toBe(packageJson.version);
  });







  it("withdrawn rule names are never reused or left configured", () => {


    const live = Object.keys(RETIRED_RULES).filter(
      (name) => name in plugin.rules,
    );
    expect(live).toEqual([]);

    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = new Set(referencedRuleNames(text));
    const stillConfigured = Object.keys(RETIRED_RULES).filter((name) =>
      referenced.has(name),
    );
    expect(stillConfigured).toEqual([]);
  });










































  it("_retired-rules.ts covers every rule file git has seen deleted", () => {
    expect(gitOutput("rev-parse", "--is-shallow-repository").trim()).toBe(
      "false",
    );

    const log = gitOutput(
      "log",
      "--no-renames",
      "--diff-filter=D",
      "--name-only",
      "--format=",
      "HEAD",
      "--",
      "packages/typescript/src/rules",
    );

    const deleted = new Set(
      log.split("\n")
        .map((line) => line.trim())
        .filter((path) => path.endsWith(".ts") && !path.endsWith(".test.ts"))
        .map((path) => path.slice(path.lastIndexOf("/") + 1, -".ts".length))
        .filter((name) => !name.startsWith("_"))
        .filter((name) => !(name in plugin.rules) && !(name in RENAMED_RULES)),
    );

    const unrecorded = [...deleted]
      .filter((name) => !(name in RETIRED_RULES))
      .sort();
    expect(
      unrecorded,
      `git history has deleted rule files that _retired-rules.ts never recorded: ${unrecorded.join(", ")}. ` +
      "Add them, or record the move in _renamed-rules.ts if the rule was renamed rather than withdrawn.",
    ).toEqual([]);
  });











  it("reports whether git history can still corroborate _retired-rules.ts", () => {
    const log = gitOutput(
      "log",
      "--no-renames",
      "--diff-filter=D",
      "--name-only",
      "--format=",
      "HEAD",
      "--",
      "packages/typescript/src/rules",
    );
    const recorded = Object.keys(RETIRED_RULES).length;

    warnIfHistoryIsMissing(log, recorded);




    expect(recorded).toBeGreaterThan(0);
  });
});
