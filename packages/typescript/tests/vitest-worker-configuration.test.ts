import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { availableParallelism, tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, it } from "vitest";

import { record } from "../../standards/src/sarj_standards/configs/tool-json.mts";

const CONFIG_PATH = fileURLToPath(new URL("../vitest.config.ts", import.meta.url));
const VITEST_NODE_MODULE = new URL("../node_modules/vitest/dist/node.js", import.meta.url).href;
const AVAILABLE_CPUS = availableParallelism();
const CONFIGURATION_PROBE = `
import { resolveConfig } from ${JSON.stringify(VITEST_NODE_MODULE)};
const options = JSON.parse(process.argv[2]);
const resolved = await resolveConfig({
  root: process.cwd(), config: process.argv[1], configLoader: "native", ...options,
});
const projects = Object.fromEntries(resolved.test.resolvedProjects.map(({ projectConfig }) => [
  projectConfig.name,
  {
    maxWorkers: projectConfig.maxWorkers,
    groupOrder: projectConfig.sequence.groupOrder,
    isolate: projectConfig.isolate,
    include: projectConfig.include,
    exclude: projectConfig.exclude,
  },
]));
console.log(JSON.stringify({
  maxWorkers: resolved.test.maxWorkers,
  globals: resolved.test.globals,
  testTimeout: resolved.test.testTimeout,
  hookTimeout: resolved.test.hookTimeout,
  projects,
}));
`;

async function resolveRepositoryConfig(
  capacity: string | undefined,
  options: { maxWorkers?: number; fileParallelism?: boolean } = {},
  nativeBudget?: string,
): Promise<Record<string, unknown>> {
  const root = await mkdtemp(join(tmpdir(), "sarj-vitest-budget-"));
  try {
    await mkdir(join(root, ".git"));
    const environment: NodeJS.ProcessEnv = { ...process.env, XDG_DATA_HOME: join(root, "private-data") };
    delete environment["VITEST_MAX_WORKERS"];
    delete environment["SARJ_LOCAL_CHECK_JOBS"];
    if (capacity !== undefined) environment["SARJ_LOCAL_CHECK_JOBS"] = capacity;
    if (nativeBudget !== undefined) environment["VITEST_MAX_WORKERS"] = nativeBudget;
    const output = execFileSync(process.execPath, [
      "--input-type=module", "--eval", CONFIGURATION_PROBE, CONFIG_PATH, JSON.stringify(options),
    ], { cwd: root, env: environment, encoding: "utf8", timeout: 15_000 });
    return record(JSON.parse(output) as unknown, "resolved Vitest configuration");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

function withBudget(baseline: Record<string, unknown>, maxWorkers: number) {
  const projects = record(baseline["projects"], "resolved projects");
  return {
    ...baseline,
    maxWorkers,
    projects: Object.fromEntries(Object.entries(projects).map(([name, project]) => [
      name, { ...record(project, "resolved project"), maxWorkers },
    ])),
  };
}

let baseline: Record<string, unknown>;

beforeAll(async () => {
  baseline = await resolveRepositoryConfig(undefined);
});

describe("native repository Vitest worker configuration", () => {
  it.each([
    ["shared capacity", "3", Math.max(1, Math.floor(AVAILABLE_CPUS / 3))],
    ["single reservation", "1", AVAILABLE_CPUS],
    ["serial floor", String(AVAILABLE_CPUS + 1), 1],
  ] as const)("uses the admitted budget for %s without changing either project", async (_name, capacity, budget) => {
    expect(await resolveRepositoryConfig(capacity)).toEqual(withBudget(baseline, budget));
  });

  it.each([undefined, "", "invalid", "0", "-1", "1.5", "0x3", "03", "9007199254740992"])(
    "retains native defaults for absent or invalid capacity %s", async (capacity) => {
      expect(await resolveRepositoryConfig(capacity)).toEqual(baseline);
    },
  );

  it("preserves project membership, isolation and timeouts", () => {
    const projects = record(baseline["projects"], "resolved projects");
    expect(Object.keys(projects)).toEqual(["isolated", "shared-module-graph"]);
    const isolated = record(projects["isolated"], "isolated project");
    const shared = record(projects["shared-module-graph"], "shared project");
    expect(isolated).toMatchObject({ groupOrder: 0, isolate: true, include: ["tests/**/*.test.ts"] });
    expect(shared).toMatchObject({ groupOrder: 0, isolate: false });
    expect(shared["include"]).toEqual(expect.arrayContaining(["tests/rules/no-secret-in-log.test.ts"]));
    expect(isolated["exclude"]).toEqual(shared["include"]);
    expect(baseline).toMatchObject({ globals: false, testTimeout: 60_000, hookTimeout: 60_000 });
  });

  it("retains native explicit worker, environment and serial options", async () => {
    expect(await resolveRepositoryConfig("3", { maxWorkers: 4 })).toEqual(withBudget(baseline, 4));
    expect(await resolveRepositoryConfig("3", { maxWorkers: 4 }, "5")).toEqual(withBudget(baseline, 5));
    expect(await resolveRepositoryConfig("3", { fileParallelism: false })).toEqual(withBudget(baseline, 1));
  });
});
