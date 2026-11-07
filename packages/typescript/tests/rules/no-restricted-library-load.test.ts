// vitest: shared-module-graph
import rule from "../../src/rules/no-restricted-library-load.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

const CONFIGURED_REPLACEMENT_EXAMPLE = "import ky from 'ky'; const client = ky;";
const RUNTIME_LOAD_EXAMPLE = "const client = require('axios');";

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
    { name: "preserves erased import-type equals declarations", code: "import type Axios = require('axios');", options: OPTIONS },
    { name: "accepts the documented static import", code: CONFIGURED_REPLACEMENT_EXAMPLE, options: OPTIONS },
    { code: 'import axios from "axios";', options: OPTIONS },
    { code: 'export { default } from "axios";', options: OPTIONS },
    { code: 'const client = require(name);', options: OPTIONS },
    { code: 'const client = require(`axios-${variant}`);', options: OPTIONS },
    { code: 'const client = loader("axios");', options: OPTIONS },
    { code: 'const client = require("axios-retry");', options: OPTIONS },
    { code: 'const require = makeLoader(); require("axios");', options: OPTIONS },
    { code: 'const require = makeLoader(); require["resolve"]("axios");', options: OPTIONS },
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
    { name: "reports the documented runtime load", code: RUNTIME_LOAD_EXAMPLE, options: OPTIONS, errors: [{ messageId: "restrictedLibraryLoad" }] },
    {
      code: 'const client = await import("axios");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      name: "reports a static template dynamic import",
      code: 'const client = await import(`axios`);',
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
      name: "reports a static template CommonJS load",
      code: 'const client = require(`axios`);',
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
      name: "reports a static template CommonJS resolution reference",
      code: 'const path = require.resolve(`axios`);',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      name: "reports a computed CommonJS resolution reference",
      code: 'const path = require["resolve"]("axios");',
      options: OPTIONS,
      errors: [{ messageId: "restrictedLibraryLoad" }],
    },
    {
      name: "reports a computed CommonJS resolution reference with a static template",
      code: 'const path = require["resolve"](`axios`);',
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
