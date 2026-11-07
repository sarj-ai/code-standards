import type { OxlintConfig } from "oxlint";

import repositoryTooling from "../../.github/scripts/oxlint.config.mts";

// The Standards TypeScript helpers follow the repository tooling gate. The
// action parser is a generated bundle.
const config: OxlintConfig = {
  extends: [repositoryTooling],
  ignorePatterns: ["src/sarj_standards/configs/action-parser.cjs"],
};

export default config;
