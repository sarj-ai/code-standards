import { definePlugin } from "@oxlint/plugins";
import preferPromisesFs from "../../vendor/node/prefer-promises-fs.js";
export default definePlugin({
  meta: { name: "sarj-upstream-node" },
  rules: { "prefer-promises-fs": preferPromisesFs },
});
