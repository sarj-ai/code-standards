import { definePlugin } from "@oxlint/plugins";
import { rule as S3923 } from "../../vendor/sonarjs/S3923/rule.cjs";
import { rule as S1066 } from "../../vendor/sonarjs/S1066/rule.cjs";
import { rule as S4143 } from "../../vendor/sonarjs/S4143/rule.cjs";
import { rule as S1764 } from "../../vendor/sonarjs/S1764/rule.cjs";
import { rule as S4144 } from "../../vendor/sonarjs/S4144/rule.cjs";
import { rule as S3626 } from "../../vendor/sonarjs/S3626/rule.cjs";
import { rule as S3699 } from "../../vendor/sonarjs/S3699/rule.cjs";
import { rule as S1488 } from "../../vendor/sonarjs/S1488/rule.cjs";

export default definePlugin({
  meta: { name: "sarj-upstream-sonarjs", version: "2.0.4" },
  rules: {
    "no-all-duplicated-branches": S3923,
    "no-collapsible-if": S1066,
    "no-element-overwrite": S4143,
    "no-identical-expressions": S1764,
    "no-identical-functions": S4144,
    "no-redundant-jump": S3626,
    "no-use-of-empty-return-value": S3699,
    "prefer-immediate-return": S1488,
  },
});
