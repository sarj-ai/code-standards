import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_RESTRICTED_LIBRARY_LOAD_DOCUMENTATION } from "../../src/rules/no-restricted-library-load.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parser: tsParser },
});

const OPTIONS = [
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

RULE_TESTER.run("no-restricted-library-load", rule, {
  valid: [
    { name: "accepts the documented static import", code: NO_RESTRICTED_LIBRARY_LOAD_DOCUMENTATION.examples[0].files[0].source, options: OPTIONS },
    { code: 'import axios from "axios";', options: OPTIONS },
    { code: 'export { default } from "axios";', options: OPTIONS },
    { code: 'const client = require(name);', options: OPTIONS },
    { code: 'const client = require(`axios`);', options: OPTIONS },
    { code: 'const client = loader("axios");', options: OPTIONS },
    { code: 'const client = require("axios-retry");', options: OPTIONS },
    { code: 'const require = makeLoader(); require("axios");', options: OPTIONS },
    {
      code: 'function load(require: (name: string) => unknown) { return require("axios"); }',
      options: OPTIONS,
    },
    {
      code: 'function resolve(require: { resolve(name: string): string }) { return require.resolve("axios"); }',
      options: OPTIONS,
    },
  ],
  invalid: [
    { name: "reports the documented runtime load", code: NO_RESTRICTED_LIBRARY_LOAD_DOCUMENTATION.examples[1].files[0].source, options: OPTIONS, errors: [{ messageId: "restrictedLibraryLoad" }] },
    {
      code: 'const client = await import("axios");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const fp = await import("lodash/fp");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const client = require("axios");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const client = require("axios");',
      options: OPTIONS,
      languageOptions: { globals: { require: "readonly" } },
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'const path = require.resolve("axios");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      code: 'import client = require("axios");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
  ],
});
