import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-monolithic-components.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const smallComponent = `
function SmallComponent() {
  return null;
}
`;

const hugeFunction = `
function MegaComponent() {
${Array(260).fill("  console.log('huge');").join("\n")}
  return null;
}
`;

const hugeArrow = `
const MegaArrowComponent = () => {
${Array(260).fill("  console.log('huge');").join("\n")}
  return null;
};
`;

const hugeClass = `
class MegaClassComponent extends React.Component {
${Array(260).fill("  someMethod() { return true; }").join("\n")}
  render() {
    return null;
  }
}
`;

const hugeHelperFunction = `
function notAComponent() {
${Array(260).fill("  console.log('huge');").join("\n")}
}
`;

ruleTester.run("no-monolithic-components", rule, {
  valid: [
    { code: smallComponent },
    { code: hugeHelperFunction }, // Not PascalCase, so ignored
  ],
  invalid: [
    {
      code: hugeFunction,
      errors: [{ messageId: "monolithicComponent" }],
    },
    {
      code: hugeArrow,
      errors: [{ messageId: "monolithicComponent" }],
    },
    {
      code: hugeClass,
      errors: [{ messageId: "monolithicComponent" }],
    },
  ],
});
