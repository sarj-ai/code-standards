import assert from "node:assert/strict";
import childProcess, { type ExecFileSyncOptions } from "node:child_process";
import {
  existsSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import fsPromises from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import { basename, dirname, join, resolve } from "node:path";
import process from "node:process";
import { test, type TestContext } from "node:test";

import { normalize, prefetchPythonExamples } from "./format-python-examples.ts";

const repositoryRoot = resolve(import.meta.dirname, "../../..");

await test("prefetch retains raw cache identities, stub paths, and real second passes", async (context) => {
  const calls = mockRuff(
    context,
    (source) => source.replaceAll("x=1", "x = 1"),
    0,
  );
  const cache = new Map([["cached.py\0cached=1", "cached = 1\n"]]);
  await prefetchPythonExamples(
    [
      { path: "A.PY", source: "x=1\r\n" },
      { path: "a.py", source: "x=1\r\n" },
      { path: "a.py", source: "x=1\r" },
      { path: "a.py", source: "x=1 \n" },
      { path: "stub.PYI", source: "x=1\n" },
      { path: "cached.py", source: "cached=1" },
      { path: "example.ts", source: "x=1" },
      { path: "empty.py", source: "" },
      { path: "large.py", source: "x".repeat(64 * 1024 + 1) },
      { path: "bad\0.py", source: "x=1" },
    ],
    cache,
    "fixture-ruff",
  );
  assert.equal(calls.length, 2);
  assert.equal(calls[0]?.files.length, 4);
  assert.equal(calls[1]?.files.length, 2);
  assert(calls[0]?.files.includes("example.pyi"));
  for (const source of ["x=1\r\n", "x=1\r", "x=1 \n"]) {
    assert.equal(cache.get(`a.py\0${source}`), "x = 1\n");
  }
  assert.equal(cache.get("a.py\0x = 1\n"), "x = 1\n");
  assert.equal(cache.get("stub.pyi\0x=1\n"), "x = 1\n");
  assert.equal(cache.get("cached.py\0cached=1"), "cached = 1\n");
  assert.equal(cache.size, 7);
  assert(calls.every(({ directory }) => !existsSync(dirname(directory))));
});

for (const pass of [1, 2]) {
  await test(`failed prefetch wave ${String(pass)} publishes nothing and cleans staging`, async (context) => {
    const calls = mockRuff(
      context,
      (source) => source.replace("x=1", "x = 1"),
      pass,
    );
    const cache = new Map([["cached.py\0cached=1", "cached = 1\n"]]);
    const before = new Map(cache);
    await prefetchPythonExamples(
      [{ path: "example.py", source: "x=1\n" }],
      cache,
      "fixture-ruff",
    );
    assert.deepEqual(cache, before);
    assert.equal(calls.length, pass);
    assert(calls.every(({ directory }) => !existsSync(dirname(directory))));
  });
}

await test("prefetch preserves unequal second-wave output for the driver idempotence check", async (context) => {
  const calls = mockRuff(
    context,
    (_source, pass) => (pass === 1 ? "first\n" : "second\n"),
    0,
  );
  const cache = new Map<string, string>();
  await prefetchPythonExamples(
    [{ path: "example.py", source: "start\n" }],
    cache,
    "fixture-ruff",
  );
  assert.equal(calls.length, 2);
  assert.equal(cache.get("example.py\0start\n"), "first\n");
  assert.equal(cache.get("example.py\0first\n"), "second\n");
});

await test("expanded first output falls back before the second input limit is exceeded", async (context) => {
  const calls = mockRuff(context, () => "x".repeat(64 * 1024 + 1), 0);
  const cache = new Map<string, string>();
  await prefetchPythonExamples(
    [{ path: "example.py", source: "x=1\n" }],
    cache,
    "fixture-ruff",
  );
  assert.equal(calls.length, 1);
  assert.equal(cache.size, 0);
  assert(calls.every(({ directory }) => !existsSync(dirname(directory))));
});

await test("file output retains the native byte limit before reading or caching", async (context) => {
  const calls = mockRuff(context, () => "😀".repeat((1024 * 1024) / 4 + 1), 0);
  const reads = context.mock.method(fsPromises, "readFile");
  syncBuiltinESMExports();
  const cache = new Map<string, string>();
  await prefetchPythonExamples(
    [{ path: "example.py", source: "x=1\n" }],
    cache,
    "fixture-ruff",
  );
  assert.equal(calls.length, 1);
  assert.equal(reads.mock.callCount(), 0);
  assert.equal(cache.size, 0);
  assert(calls.every(({ directory }) => !existsSync(dirname(directory))));
});

await test("missing batch output discards the cache and cleans staging", async (context) => {
  let directory = "";
  context.mock.method(
    childProcess,
    "execFileSync",
    (_command: string, args: string[]) => {
      const path = args.at(-1);
      assert(path);
      directory = path;
      rmSync(join(directory, "0", "example.py"));
      return "";
    },
  );
  syncBuiltinESMExports();
  context.after(() => {
    context.mock.restoreAll();
    syncBuiltinESMExports();
  });
  const cache = new Map<string, string>();
  await prefetchPythonExamples(
    [{ path: "example.py", source: "x=1\n" }],
    cache,
    "fixture-ruff",
  );
  assert.equal(cache.size, 0);
  assert(directory);
  assert(!existsSync(dirname(directory)));
});

await test("cleanup failure remains visible and prevents cache publication", async (context) => {
  const calls = mockRuff(
    context,
    (source) => source.replace("x=1", "x = 1"),
    0,
  );
  const remove = fsPromises.rm;
  context.mock.method(fsPromises, "rm", () =>
    Promise.reject(new Error("fixture cleanup failure")),
  );
  syncBuiltinESMExports();
  const cache = new Map<string, string>();
  try {
    await assert.rejects(
      () =>
        prefetchPythonExamples(
          [{ path: "example.py", source: "x=1\n" }],
          cache,
          "fixture-ruff",
        ),
      /fixture cleanup failure/u,
    );
    assert.equal(cache.size, 0);
  } finally {
    context.mock.restoreAll();
    syncBuiltinESMExports();
    for (const { directory } of calls)
      await remove(dirname(directory), { recursive: true, force: true });
  }
});

await test("prefetch preserves an explicit child Rayon budget", async (context) => {
  const previous = process.env["RAYON_NUM_THREADS"];
  context.after(() => {
    if (previous === undefined) delete process.env["RAYON_NUM_THREADS"];
    else process.env["RAYON_NUM_THREADS"] = previous;
  });
  process.env["RAYON_NUM_THREADS"] = "3";
  const calls = mockRuff(context, (source) => source, 0);
  await prefetchPythonExamples(
    [{ path: "example.py", source: "x = 1\n" }],
    new Map(),
    "fixture-ruff",
  );
  assert.equal(calls.length, 1);
});

await test("pinned Ruff bulk output matches isolated stdin for Python and stubs", async () => {
  const ruff = resolve(repositoryRoot, "packages/standards/.venv/bin/ruff");
  const files = [
    { path: "example.py", source: "values=[1,2,3]\r\n" },
    { path: "stub.PYI", source: "class C:\r def f( self,a:int)->str: ...\r" },
  ];
  const cache = new Map<string, string>();
  await prefetchPythonExamples(files, cache, ruff);
  for (const file of files) {
    const path = file.path.toLowerCase().endsWith(".pyi")
      ? "example.pyi"
      : "example.py";
    const options = {
      cwd: repositoryRoot,
      encoding: "utf8" as const,
      input: normalize(file.source),
      maxBuffer: 1024 * 1024,
      timeout: 30_000,
    };
    const expected = normalize(
      childProcess.execFileSync(
        ruff,
        ["format", "--isolated", "--stdin-filename", path, "-"],
        options,
      ),
    );
    assert.equal(
      cache.get(`${file.path.toLowerCase()}\0${file.source}`),
      expected,
    );
    const second = normalize(
      childProcess.execFileSync(
        ruff,
        ["format", "--isolated", "--stdin-filename", path, "-"],
        { ...options, input: expected },
      ),
    );
    assert.equal(cache.get(`${file.path.toLowerCase()}\0${expected}`), second);
  }
});

function mockRuff(
  context: TestContext,
  format: (source: string, pass: number) => string,
  failingPass: number,
) {
  const calls: { directory: string; files: string[] }[] = [];
  context.mock.method(
    childProcess,
    "execFileSync",
    (command: string, args: string[], options: ExecFileSyncOptions) => {
      assert.equal(command, "fixture-ruff");
      assert.deepEqual(args.slice(0, -1), [
        "format",
        "--isolated",
        "--no-cache",
        "--no-respect-gitignore",
      ]);
      assert.equal(options.cwd, repositoryRoot);
      assert.equal(options.timeout, 30_000);
      assert.equal(options.maxBuffer, 1024 * 1024);
      assert.equal(
        options.env?.["RAYON_NUM_THREADS"],
        process.env["RAYON_NUM_THREADS"] ?? "1",
      );
      const directory = args.at(-1);
      assert(directory);
      const files = readdirSync(directory, { encoding: "utf8", recursive: true })
        .filter((path) => /\.pyi?$/u.test(path))
        .toSorted();
      calls.push({ directory, files: files.map((path) => basename(path)) });
      for (const path of files) {
        const target = join(directory, path);
        writeFileSync(
          target,
          format(readFileSync(target, "utf8"), calls.length),
          "utf8",
        );
        if (calls.length === failingPass)
          throw new Error("fixture formatter failure");
      }
      return "";
    },
  );
  syncBuiltinESMExports();
  context.after(() => {
    context.mock.restoreAll();
    syncBuiltinESMExports();
  });
  return calls;
}
