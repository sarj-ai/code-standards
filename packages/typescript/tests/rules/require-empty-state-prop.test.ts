import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-empty-state-prop.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
});

ruleTester.run("require-empty-state-prop", rule, {
  valid: [
    { code: "const x = <Table emptyState={<div>No data</div>} />;" },
    { code: "const x = <List renderEmpty={() => <div>Empty</div>} />;" },
    { code: "const x = <DataGrid emptyState=\"No records\" />;" },
    { code: "const x = <Feed renderEmpty={null} />;" },
    { code: "const x = <Table {...props} />;" },
    { code: "const x = <OtherComponent />;" },
  ],
  invalid: [
    {
      code: "const x = <Table />;",
      errors: [{ messageId: "requireEmptyState", data: { component: "Table" } }],
    },
    {
      code: "const x = <List items={[]} />;",
      errors: [{ messageId: "requireEmptyState", data: { component: "List" } }],
    },
    {
      code: "const x = <DataGrid data={[]} columns={[]} />;",
      errors: [{ messageId: "requireEmptyState", data: { component: "DataGrid" } }],
    },
    {
      code: "const x = <Feed someProp />;",
      errors: [{ messageId: "requireEmptyState", data: { component: "Feed" } }],
    },
  ],
});
