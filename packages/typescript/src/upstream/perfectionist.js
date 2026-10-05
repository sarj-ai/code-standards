import { definePlugin } from "@oxlint/plugins";
import rule0 from "../../vendor/perfectionist/rules/sort-interfaces.js";
import rule1 from "../../vendor/perfectionist/rules/sort-jsx-props.js";
import rule2 from "../../vendor/perfectionist/rules/sort-union-types.js";
import sortClasses from "../../vendor/perfectionist/rules/sort-classes.js";
export default definePlugin({
  meta: { name: "sarj-upstream-perfectionist" },
  rules: {
    "sort-interfaces": rule0,
    "sort-jsx-props": rule1,
    "sort-union-types": rule2,
    "sort-classes": sortClasses,
  },
});
