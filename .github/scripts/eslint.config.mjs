import { createRequire } from "node:module";

const require = createRequire(new URL("../../packages/typescript/package.json", import.meta.url));
const js = require("@eslint/js");
const globals = require("globals");

export default [
  {
    name: "sarj/ci-javascript-helpers",
    files: ["**/*.{js,cjs,mjs}"],
    rules: js.configs.recommended.rules,
    languageOptions: { globals: globals.nodeBuiltin },
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  {
    files: ["**/*.cjs"],
    languageOptions: { globals: globals.node },
  },
];
