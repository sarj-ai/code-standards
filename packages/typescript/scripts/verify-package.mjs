import { readFile, stat } from "node:fs/promises";
import { resolve, relative, isAbsolute } from "node:path";

const root = resolve(import.meta.dirname, "..");
const manifest = JSON.parse(
  await readFile(resolve(root, "package.json"), "utf8"),
);
const entries = [
  ...exportEntries(manifest.main),
  ...exportEntries(manifest.module),
  ...exportEntries(manifest.types, true),
  ...exportEntries(manifest.exports),
  ...(typeof manifest.bin === "string"
    ? exportEntries(manifest.bin)
    : Object.values(manifest.bin ?? {}).flatMap((target) =>
        exportEntries(target),
      )),
];
for (const [target, declaration] of entries) {
  const path = target.startsWith("./") ? target.slice(2) : target;
  const authoredDeclaration =
    declaration && path.startsWith("types/") && path.endsWith(".d.ts");
  if (!path.startsWith("dist/") && !authoredDeclaration)
    throw new Error(
      `runtime exports must live under dist/; declarations may use types/*.d.ts: ${path}`,
    );
  const location = resolve(root, path);
  const local = relative(root, location);
  if (isAbsolute(local) || local.startsWith(".."))
    throw new Error(`export escapes package root: ${target}`);
  const artifact = await stat(location);
  if (!artifact.isFile() || artifact.size === 0)
    throw new Error(`missing or empty export: ${target}`);
}

function exportEntries(value, declaration = false) {
  if (typeof value === "string") return [[value, declaration]];
  if (Array.isArray(value))
    return value.flatMap((item) => exportEntries(item, declaration));
  if (value === null || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, item]) =>
    exportEntries(item, declaration || key === "types"),
  );
}
