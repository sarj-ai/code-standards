import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { REACT_DOCTOR_RULES } from "oxlint-plugin-react-doctor/core";

const APP_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(APP_ROOT, "../..");
const CONFIG_ROOT = join(
  REPOSITORY_ROOT,
  "packages/standards/src/sarj_standards/configs",
);
const runtimePolicyPath = join(CONFIG_ROOT, "react-doctor-scan.mjs");
const { ruleSeverity } = (await import(runtimePolicyPath)) as {
  ruleSeverity: (
    entry: (typeof REACT_DOCTOR_RULES)[number],
    config: unknown,
  ) => string;
};
const config: unknown = JSON.parse(
  await readFile(join(CONFIG_ROOT, "doctor.config.json"), "utf8"),
);
const FRAMEWORK_CONTEXTS: Readonly<
  Record<string, readonly [string, string] | undefined>
> = {
  global: ["react-project", "React projects"],
  nextjs: ["nextjs-project", "Next.js projects"],
  preact: ["preact-project", "Preact projects"],
  "react-native": ["react-native-project", "React Native projects"],
  "tanstack-query": ["tanstack-query-project", "TanStack Query projects"],
  "tanstack-start": ["tanstack-start-project", "TanStack Start projects"],
};

const rules = REACT_DOCTOR_RULES.filter(
  ({ rule }) => !rule.isProjectRule,
).flatMap((entry) => {
  const severity = ruleSeverity(entry, config);
  if (severity !== "error" && severity !== "warn") return [];

  const context = FRAMEWORK_CONTEXTS[entry.rule.framework];
  if (!context)
    throw new Error(`unknown React Doctor framework ${entry.rule.framework}`);
  const level = severity === "warn" ? "warning" : severity;
  const contexts = [{ id: context[0], label: context[1], level }];
  return [
    {
      key: `react-doctor:${entry.id}`,
      provider: "react-doctor",
      id: entry.id,
      displayId: entry.key,
      summary: entry.rule.recommendation,
      docsUrl: `https://react.doctor/docs/rules/${entry.key}`,
      family: entry.rule.category,
      autofix: "none",
      hasSuggestions: false,
      profiles: ["application", "standard"].map((name) => ({ name, contexts })),
    },
  ];
});

process.stdout.write(`${JSON.stringify({ rules })}\n`);
