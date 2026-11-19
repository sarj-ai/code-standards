// Read actual parser comments; directive-like text inside strings is not editable.
import { readFile, realpath } from "node:fs/promises";
import { createRequire, findPackageJSON } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const packageFile = findPackageJSON("@sarj/eslint-plugin", pathToFileURL(resolve("package.json")));
if (!packageFile) throw new Error("The project has no local @sarj/eslint-plugin");
const { parseSync } = createRequire(await realpath(packageFile))("oxc-parser");
const { values } = parseArgs({ options: { file: { type: "string" } } });
const filename = values.file;
if (!filename) throw new Error("Directive comment parsing requires --file");
const source = await readFile(filename, "utf8");
const parsed = parseSync(filename, source);
if (parsed.errors.length)
  throw new Error("Cannot prove directive comment spans in an unparsed source");
let character = 0;
let byte = 0;
function byteOffset(position) {
  if (position < character) throw new Error("Parser comments are not in source order");
  byte += Buffer.byteLength(source.slice(character, position));
  character = position;
  return byte;
}
process.stdout.write(
  JSON.stringify(
    parsed.comments.map(({ start, end }) => [byteOffset(start), byteOffset(end)]),
  ),
);
