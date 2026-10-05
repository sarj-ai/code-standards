import { createStrictOxlintConfig } from "@sarj/oxlint-plugin/config";

export { createStrictOxlintConfig };
export default await createStrictOxlintConfig({ root: import.meta.dirname });
