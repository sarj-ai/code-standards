// Compare layout with a fixed formatter policy; never load repository configuration.
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const limit = 32 * 1024 * 1024;
const chunks = [];
let size = 0;
for await (const chunk of process.stdin) {
  size += chunk.length;
  if (size >= limit)
    throw new Error("Formatting comparison input exceeds its limit");
  chunks.push(chunk);
}

const requests = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const policy = {
  embeddedLanguageFormatting: "off",
  jsdoc: false,
  objectWrap: "collapse",
  sortImports: false,
  sortPackageJson: false,
};
const equivalent = [];
for (const request of requests) {
  const module = createRequire(request.entrypoint).resolve("oxfmt");
  const { format } = await import(pathToFileURL(module).href);
  const before = await format(request.path, request.before, policy);
  const after = await format(request.path, request.after, policy);
  if (
    before.errors.length === 0 &&
    after.errors.length === 0 &&
    before.code === after.code
  ) {
    equivalent.push(request.path);
  }
}
process.stdout.write(JSON.stringify(equivalent));
