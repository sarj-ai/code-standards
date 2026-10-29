import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import process from "node:process";

import type { ExampleFile } from "../src/lib/catalog.ts";

const repositoryRoot = resolve(import.meta.dirname, "../../..");

export async function prefetchPythonExamples(
  files: readonly ExampleFile[],
  cache: Map<string, string>,
  ruffExecutable: string,
) {
  const inputs = collectPythonInputs(files, cache);
  if (inputs.size === 0) return;

  let pending: Map<string, string>;
  let directory: string | undefined;
  try {
    directory = await fs.mkdtemp(join(tmpdir(), "sarj-docs-ruff-"));
    pending = await formatBatch(
      inputs,
      join(directory, "first"),
      ruffExecutable,
    );
    const secondInputs = new Map<string, ExampleFile>();
    for (const [key, file] of inputs) {
      const formatted = pending.get(key);
      if (formatted === undefined || formatted.length > 64 * 1024) return;
      const secondKey = `${file.path.toLowerCase()}\0${formatted}`;
      if (!cache.has(secondKey) && !pending.has(secondKey)) {
        secondInputs.set(secondKey, { path: file.path, source: formatted });
      }
    }
    for (const [key, formatted] of await formatBatch(
      secondInputs,
      join(directory, "second"),
      ruffExecutable,
    )) {
      pending.set(key, formatted);
    }
  } catch {
    // A cache miss retains the original per-file formatter and its diagnostics.
    return;
  } finally {
    if (directory !== undefined)
      await fs.rm(directory, { recursive: true, force: true });
  }
  for (const [key, formatted] of pending) cache.set(key, formatted);
}

function collectPythonInputs(
  files: readonly ExampleFile[],
  cache: ReadonlyMap<string, string>,
) {
  const inputs = new Map<string, ExampleFile>();
  for (const file of files) {
    if (typeof file.path !== "string" || typeof file.source !== "string")
      continue;
    const lower = file.path.toLowerCase();
    if (
      !/\.pyi?$/u.test(lower) ||
      !file.source ||
      file.source.length > 64 * 1024 ||
      file.path.includes("\0")
    )
      continue;
    const key = `${lower}\0${file.source}`;
    if (!cache.has(key)) inputs.set(key, file);
  }
  return inputs;
}

async function formatBatch(
  inputs: ReadonlyMap<string, ExampleFile>,
  directory: string,
  ruffExecutable: string,
) {
  if (inputs.size === 0) return new Map<string, string>();
  await fs.mkdir(directory);
  const manifest: { key: string; path: string }[] = [];
  let index = 0;
  for (const [key, file] of inputs) {
    const parent = join(directory, String(index));
    index += 1;
    await fs.mkdir(parent);
    const path = join(
      parent,
      file.path.toLowerCase().endsWith(".pyi") ? "example.pyi" : "example.py",
    );
    await fs.writeFile(path, normalize(file.source), "utf8");
    manifest.push({ key, path });
  }
  execFileSync(
    ruffExecutable,
    ["format", "--isolated", "--no-cache", "--no-respect-gitignore", directory],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        RAYON_NUM_THREADS: process.env["RAYON_NUM_THREADS"] ?? "1",
      },
      maxBuffer: 1024 * 1024,
      timeout: 30_000,
    },
  );
  const outputs = new Map<string, string>();
  for (const { key, path } of manifest) {
    if ((await fs.stat(path)).size > 1024 * 1024) {
      throw new RangeError(
        "batch formatter output exceeds the native output limit",
      );
    }
    outputs.set(key, normalize(await fs.readFile(path, "utf8")));
  }
  return outputs;
}

export function normalize(source: string) {
  return `${source.replaceAll("\r\n", "\n").replaceAll("\r", "\n").trimEnd()}\n`;
}
