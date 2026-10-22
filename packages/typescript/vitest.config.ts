import { readdir, readFile } from "node:fs/promises";
import { availableParallelism } from "node:os";

import { defineConfig } from "vitest/config";

const TEST_DIRECTORY = new URL("./tests/", import.meta.url);
const TEST_FILE_PATTERN = "tests/**/*.test.ts";
const SHARED_MODULE_GRAPH_MARKER = /^\/\/ vitest: shared-module-graph$/m;
const SHARED_MODULE_GRAPH_FORBIDDEN =
  /vi\.(?:mock|doMock|spyOn|stubGlobal|stubEnv|useFakeTimers|setSystemTime)|process\.env\b[^=\n]*=[^=]|process\.chdir|projectService|tsconfigRootDir/;

// Opted-in files reuse one module graph per worker instead of re-importing the
// plugin and parser for every file. Only mark untyped RuleTester suites that use
// no fake timers, mocks, spies, environment writes or other process-wide state.
async function isSharedModuleGraphTest(file: string): Promise<boolean> {
  const source = await readFile(new URL(file, TEST_DIRECTORY), "utf8");
  if (!SHARED_MODULE_GRAPH_MARKER.test(source)) return false;
  if (SHARED_MODULE_GRAPH_FORBIDDEN.test(source)) {
    throw new Error(`tests/${file} touches process-wide or typed-parser state, so it cannot opt into the shared module graph`);
  }
  return true;
}

async function sharedModuleGraphTests(): Promise<string[]> {
  const testFiles = (await readdir(TEST_DIRECTORY, { recursive: true })).filter((file) => file.endsWith(".test.ts"));
  const marked = await Promise.all(testFiles.map(isSharedModuleGraphTest));
  return testFiles.filter((_, index) => marked[index]).map((file) => `tests/${file.replaceAll("\\", "/")}`);
}

function localCheckWorkerOptions(): { maxWorkers?: number } {
  const options: { maxWorkers?: number } = {};
  const capacityText = process.env["SARJ_LOCAL_CHECK_JOBS"];
  if (capacityText === undefined || !/^[1-9]\d*$/u.test(capacityText)) return options;
  const capacity = Number(capacityText);
  if (Number.isSafeInteger(capacity)) options.maxWorkers = Math.max(1, Math.floor(availableParallelism() / capacity));
  return options;
}

const LOCAL_CHECK_WORKER_OPTIONS = localCheckWorkerOptions();
const SHARED_MODULE_GRAPH_TESTS = await sharedModuleGraphTests();

export default defineConfig({
  resolve: {
    alias: {
      "@sarj/eslint-plugin": new URL("./src/index.ts", import.meta.url).pathname,
    },
  },
  test: {
    ...LOCAL_CHECK_WORKER_OPTIONS,
    globals: false,
    testTimeout: 60_000,
    hookTimeout: 60_000,
    projects: [
      {
        extends: true,
        test: { name: "isolated", include: [TEST_FILE_PATTERN], exclude: SHARED_MODULE_GRAPH_TESTS },
      },
      {
        extends: true,
        test: { name: "shared-module-graph", include: SHARED_MODULE_GRAPH_TESTS, isolate: false },
      },
    ],
  },
});
