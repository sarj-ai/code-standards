import helpers from "../../.github/scripts/eslint.config.mts";

export default [
  { ignores: ["**/configs/action-parser.cjs"] },
  ...helpers,
];
