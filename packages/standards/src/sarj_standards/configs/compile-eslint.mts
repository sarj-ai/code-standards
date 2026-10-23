import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";

const compiled = stripTypeScriptTypes(readFileSync(0, "utf8"), {
  // @ts-expect-error -- Pinned Node 24 supports transform; shared Node 26 types expose only strip.
  mode: "transform",
});
process.stdout.write("// Generated from eslint.strict.ts by compile-eslint.mts.\n" + compiled);
