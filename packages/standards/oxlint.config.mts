import type { OxlintConfig } from "oxlint";

import repositoryTooling from "../../.github/scripts/oxlint.config.mts";
import { SARJ_RULES } from "../typescript/oxlint.config.mts";

// The Standards TypeScript helpers follow the repository tooling gate. The
// action parser is a generated bundle.
const config: OxlintConfig = {
  extends: [repositoryTooling],
  jsPlugins: [{ name: "@sarj", specifier: "../typescript/dist/index.js" }],
  ignorePatterns: ["src/sarj_standards/configs/action-parser.cjs"],
  overrides: [
    {
      files: [
        "src/sarj_standards/configs/react-doctor-*.mjs",
        "src/sarj_standards/configs/project-*.mjs",
        "src/sarj_standards/configs/html-script-source.mjs",
        "src/sarj_standards/configs/staged-request.mjs",
      ],
      rules: SARJ_RULES,
    },
  ],
};

export default config;
