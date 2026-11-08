import { createRequire } from "node:module";
import { RuleTester } from "./rules/_tester.js";

const require = createRequire(import.meta.url);
const { default: plugin } = require("../dist/next.js") as {
  default: { rules: Record<string, Parameters<RuleTester["run"]>[1]> };
};
const err = (expression: string) => ({ messageId: "noLocationAssign", data: { expression } });
new RuleTester({
  eslintCompat: true,
  languageOptions: {
    globals: {
      location: "readonly",
      window: "readonly",
      globalThis: "readonly",
      document: "readonly",
      self: "readonly",
    },
  },
}).run(
  "no-location-assign-relative-destination",
  plugin.rules["no-location-assign-relative-destination"]!,
  {
    valid: [
      "const method = 'assign'; location[method]('/ignored')",
      "function nested(window) { window.location.assign('/ignored') }",
      "const a = b; const b = a; location.assign(a)",
      "let url; url = 'https://example.com'; location.assign(url)",
      "location.assign(...paths)",
      "location.assign()",
      "location.assign('https://example.com'.toLowerCase())",
      "location.href = 'https://example.com'",
      "location.href = 'https://example.com/path?q=1'",
      "window.location.href = 'https://example.com'",
      "globalThis.location.href = 'https://example.com'",
      "location.assign('https://example.com')",
      "window.location.assign('https://example.com')",
      "globalThis.location.assign('https://example.com')",

      "location.href = '//example.com/path'",
      "location.assign('//cdn.example.com/file.js')",

      "location.href = 'ftp://files.example.com'",
      "location.href = 'mailto:user@example.com'",

      "location.href = `https://example.com/${path}`",
      "location.assign(`https://example.com/${path}`)",

      "location.href = someVariable",
      "location.assign(someVariable)",
      "window.location.href = computedUrl()",
      "window.location.assign(computedUrl())",

      `
      const url = 'https://example.com';
      location.href = url;
      location.assign(url);
    `,

      `
      const url = 'https://example.com/' + someVariable;
      location.href = url;
      location.assign(url);
    `,
      `
      const url = \`https://example.com/\${someVariable}\`;
      location.href = url;
      location.assign(url);
    `,

      "foo.location.href = '/path'",
      "foo.location.assign('/path')",

      `
      const location = { href: '' };
      location.href = '/foo'
    `,
      `function handler(location) { location.href = '/foo'; location.assign('/foo') }`,
      `
      const window = { location: { href: '' } };
      window.location.href = '/foo'
    `,
      `
      function handler(globalThis) {
        globalThis.location.assign('/foo')
      }
    `,
      `
      import { location } from './my-module';
      location.href = '/foo'
    `,
    ],
    invalid: [
      { code: "location = replacement; location.assign('/a')", errors: [err("location.assign()")] },
      { code: "document.location.assign('/a')", errors: [err("document.location.assign()")] },
      {
        code: "const urls = {page: '/a'}; location.assign(urls['page'])",
        errors: [err("location.assign()")],
      },
      {
        code: "const a = b; const b = a; location.assign(`/relative/${a}`)",
        errors: [err("location.assign()")],
      },
      { code: "const a = '/prefix/' + a; location.assign(a)", errors: [err("location.assign()")] },
      {
        code: "const url = '/a'; location.assign(url); location.assign(url)",
        errors: [err("location.assign()"), err("location.assign()")],
      },
      {
        code: "const a = b; const b = a; location.assign(a); location.assign('/still-checked')",
        errors: [err("location.assign()")],
      },
      {
        code: "const base = '/a'; const alias = base; location.assign(alias)",
        errors: [err("location.assign()")],
      },
      { code: "location.assign('/A'.toLowerCase())", errors: [err("location.assign()")] },
      { code: "location.assign(['', 'page'].join('/'))", errors: [err("location.assign()")] },
      { code: "self['location']['href'] = '/a'", errors: [err("self['location']['href']")] },
      {
        code: "let url = '/a'; location.assign(url); url = 'https://example.com'",
        errors: [err("location.assign()")],
      },
      { code: `location.href = '/foo'`, errors: [err("location.href")] },
      { code: `location['href'] = '/foo'`, errors: [err("location['href']")] },
      {
        code: `location.href = \`/users/\${id}\``,
        errors: [err("location.href")],
      },
      {
        code: `window.location.href = '/foo'`,
        errors: [err("window.location.href")],
      },
      {
        code: `window.location.href = '/dashboard'`,
        errors: [err("window.location.href")],
      },
      {
        code: `window.location['href'] = '/foo'`,
        errors: [err("window.location['href']")],
      },
      {
        code: `window.location['href'] = '/dashboard'`,
        errors: [err("window.location['href']")],
      },
      {
        code: `globalThis.location.href = '/foo'`,
        errors: [err("globalThis.location.href")],
      },
      {
        code: `globalThis.location.href = '/dashboard'`,
        errors: [err("globalThis.location.href")],
      },
      { code: `location.assign('/foo')`, errors: [err("location.assign()")] },
      {
        code: `location.assign('/dashboard')`,
        errors: [err("location.assign()")],
      },
      {
        code: `location['assign']('/foo')`,
        errors: [err("location['assign']()")],
      },
      {
        code: `location['assign']('/dashboard')`,
        errors: [err("location['assign']()")],
      },
      {
        code: `location.assign(\`/users/\${id}/profile\`)`,
        errors: [err("location.assign()")],
      },
      {
        code: `window.location.assign('/foo')`,
        errors: [err("window.location.assign()")],
      },
      {
        code: `window.location.assign('/dashboard')`,
        errors: [err("window.location.assign()")],
      },
      {
        code: `window.location['assign']('/foo')`,
        errors: [err("window.location['assign']()")],
      },

      {
        code: `globalThis.location.assign('/foo')`,
        errors: [err("globalThis.location.assign()")],
      },
      {
        code: `globalThis.location.assign('/dashboard')`,
        errors: [err("globalThis.location.assign()")],
      },

      { code: `location.href = './page'`, errors: [err("location.href")] },
      { code: `location.href = '../page'`, errors: [err("location.href")] },
      {
        code: `location.assign('?tab=settings')`,
        errors: [err("location.assign()")],
      },
      {
        code: `location.assign('#section')`,
        errors: [err("location.assign()")],
      },

      {
        code: `
          const url = '/dashboard';
          location.href = url;
        `,
        errors: [err("location.href")],
      },
      {
        code: `
          const url = '/dashboard/' + someVariable;
          location.href = url;
        `,
        errors: [err("location.href")],
      },
      {
        code: `
          const url = \`/dashboard/\${someVariable}\`;
          location.href = url;
        `,
        errors: [err("location.href")],
      },
      {
        code: `
          let url = 'https://example.com';
          url = '/other-path';
          location.href = url;
        `,
        errors: [err("location.href")],
      },

      {
        code: `
          function handleClick() {
            window.location.href = '/dashboard'
          }
        `,
        errors: [err("window.location.href")],
      },
      {
        code: `
          function handleClick() {
            location.assign('/dashboard')
          }
        `,
        errors: [err("location.assign()")],
      },
    ],
  },
);
