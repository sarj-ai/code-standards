import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(
  new URL("../../packages/typescript/package.json", import.meta.url),
);
const { defineConfig } =
  require("eslint/config") as typeof import("eslint/config");
const js = require("@eslint/js") as typeof import("@eslint/js");
const globals = require("globals") as typeof import("globals");
const tseslint =
  require("typescript-eslint") as typeof import("typescript-eslint");

export default defineConfig(
  {
    name: "sarj/ci-javascript-helpers",
    files: ["**/*.{js,cjs,mjs}"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.nodeBuiltin },
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
  {
    files: ["**/*.cjs"],
    languageOptions: { globals: globals.node },
  },
  {
    name: "sarj/typed-node-tooling",
    files: ["**/*.{ts,mts,cts}"],
    extends: [js.configs.recommended, tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      globals: globals.nodeBuiltin,
      parserOptions: {
        tsconfigRootDir: fileURLToPath(
          new URL("../../packages/typescript/", import.meta.url),
        ),
        projectService: false,
        project: fileURLToPath(
          new URL(
            "../../packages/typescript/tsconfig.tools.json",
            import.meta.url,
          ),
        ),
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
  },
);
