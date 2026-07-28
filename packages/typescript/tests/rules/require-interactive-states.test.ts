import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-interactive-states.js";

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

ruleTester.run("require-interactive-states", rule, {
  valid: [
    { code: "<button className='hover:bg-blue-500 focus-visible:ring' />" },
    { code: "<a href='/test' className='hover:underline focus-visible:outline-none'>Link</a>" },
    { code: "<input className='hover:border-blue-500 focus-visible:ring-2' />" },
    { code: "<select className='hover:bg-gray-100 focus-visible:ring-1' />" },
    { code: "<textarea className='hover:shadow focus-visible:border-black' />" },
    { code: "<button className={cn('hover:bg-red-500', 'focus-visible:ring')} />" },
    { code: "<a href='/foo' className={`hover:text-blue focus-visible:ring ${active ? 'active' : ''}`} />" },
    { code: "<a>No href, not interactive</a>" },
    { code: "<div className='some-class'>Not interactive</div>" },
  ],
  invalid: [
    {
      code: "<button className='hover:bg-blue-500' />",
      errors: [{ messageId: "missingInteractiveStates" }],
    },
    {
      code: "<a href='/test' className='focus-visible:ring' />",
      errors: [{ messageId: "missingInteractiveStates" }],
    },
    {
      code: "<input />",
      errors: [{ messageId: "missingInteractiveStates" }],
    },
    {
      code: "<button className={cn('hover:bg-red-500')} />",
      errors: [{ messageId: "missingInteractiveStates" }],
    },
    {
      code: "<select className='px-2 py-1'>Options</select>",
      errors: [{ messageId: "missingInteractiveStates" }],
    },
    {
      code: "<textarea className='w-full'>Text</textarea>",
      errors: [{ messageId: "missingInteractiveStates" }],
    },
  ],
});
