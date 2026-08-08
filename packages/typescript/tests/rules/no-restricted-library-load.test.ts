import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noRestrictedLibraryLoadDocumentation } from "../../src/rules/no-restricted-library-load.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});

const options = [
  {
    libraries: [
      { id: "LIB101", module: "axios", replacement: "Ky" },
      {
        id: "LIB102",
        module: "lodash",
        replacement: "Remeda",
        note: "The APIs are not drop-in equivalents.",
      },
    ],
  },
] as const;

ruleTester.run("no-restricted-library-load", rule, {
  valid: [
    { name: "accepts the documented static import", code: noRestrictedLibraryLoadDocumentation.examples[0].files[0].source, options },
    { code: 'import axios from "axios";', options },
    { code: 'export { default } from "axios";', options },
    { code: 'const client = require(name);', options },
    { code: 'const client = require(`axios`);', options },
    { code: 'const client = loader("axios");', options },
    { code: 'const client = require("axios-retry");', options },
    { code: 'const require = makeLoader(); require("axios");', options },
    {
      code: 'function load(require: (name: string) => unknown) { return require("axios"); }',
      options,
    },
    {
      code: 'function resolve(require: { resolve(name: string): string }) { return require.resolve("axios"); }',
      options,
    },
  ],
  invalid: [
    { name: "reports the documented runtime load", code: noRestrictedLibraryLoadDocumentation.examples[1].files[0].source, options, errors: [{ messageId: "restrictedLibraryLoad" }] },
    {
      code: 'const client = await import("axios");',
      options,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const fp = await import("lodash/fp");',
      options,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const client = require("axios");',
      options,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const client = require("axios");',
      options,
      languageOptions: { globals: { require: "readonly" } },
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const path = require.resolve("axios");',
      options,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'import client = require("axios");',
      options,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
  ],
});
