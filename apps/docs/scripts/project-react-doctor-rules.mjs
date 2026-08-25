import { execFileSync } from "node:child_process";
import { cp, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { REACT_DOCTOR_RULES } from "oxlint-plugin-react-doctor/core";

const APP_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(APP_ROOT, "../..");
const CONFIG_PATH = join(
  REPOSITORY_ROOT,
  "packages/standards/src/sarj_standards/configs/doctor.config.json",
);
const REACT_DOCTOR_BIN = join(
  APP_ROOT,
  "node_modules/react-doctor/bin/react-doctor.js",
);
const FRAMEWORK_CONTEXTS = {
  global: ["react-project", "React projects"],
  nextjs: ["nextjs-project", "Next.js projects"],
  preact: ["preact-project", "Preact projects"],
  "react-native": ["react-native-project", "React Native projects"],
  "tanstack-query": ["tanstack-query-project", "TanStack Query projects"],
  "tanstack-start": ["tanstack-start-project", "TanStack Start projects"],
};

async function project() {
  const projectRoot = await mkdtemp(join(tmpdir(), "sarj-react-doctor-catalog-"));
  try {
    await Promise.all([
      cp(CONFIG_PATH, join(projectRoot, "doctor.config.json")),
      writeFile(join(projectRoot, "package.json"), '{"private":true}\n', "utf8"),
    ]);
    const output = execFileSync(
      process.execPath,
      [REACT_DOCTOR_BIN, "rules", "list", "--json"],
      {
        cwd: projectRoot,
        encoding: "utf8",
        env: { ...process.env, CI: "1", DO_NOT_TRACK: "1", NO_COLOR: "1" },
        maxBuffer: 16 * 1024 * 1024,
      },
    );
    const effectiveRules = JSON.parse(output);
    if (!Array.isArray(effectiveRules)) {
      throw new TypeError("React Doctor rules list must return an array");
    }
    const metadata = new Map(REACT_DOCTOR_RULES.map((entry) => [entry.key, entry]));
    const rules = effectiveRules
      .filter(({ severity }) => severity === "error" || severity === "warn")
      .map(({ key, id, category, framework, severity }) => {
        const entry = metadata.get(key);
        if (entry === undefined) throw new Error(`missing React Doctor metadata for ${key}`);
        const context = FRAMEWORK_CONTEXTS[framework];
        if (context === undefined) throw new Error(`unknown React Doctor framework ${framework}`);
        const level = severity === "warn" ? "warning" : severity;
        const contexts = [{ id: context[0], label: context[1], level }];
        return {
          key: `react-doctor:${id}`,
          provider: "react-doctor",
          id,
          displayId: key,
          summary: entry.rule.recommendation,
          docsUrl: `https://react.doctor/docs/rules/${key}`,
          family: category,
          autofix: "none",
          hasSuggestions: false,
          profiles: ["application", "standard"].map((name) => ({ name, contexts })),
        };
      });
    process.stdout.write(`${JSON.stringify({ rules })}\n`);
  } finally {
    await rm(projectRoot, { recursive: true, force: true });
  }
}

await project();
