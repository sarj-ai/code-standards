import rule from "../../src/rules/prefer-schema-for-http-headers.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("prefer-schema-for-http-headers", rule, {
  valid: [
    {
      name: "instance get replacement abstains",
      code: "function read(headers: Headers) { headers.get = custom; return Number(headers.get('x-attempt')); }",
    },
    {
      name: "request header method replacement abstains",
      code: "function read(request: Request) { request.headers.get = custom; return Number(request.headers.get('x-attempt')); }",
    },
    {
      name: "mutation through a const alias abstains",
      code: "function read(request: Request) { const alias = request.headers; alias.get = custom; return Number(request.headers.get('x-attempt')); }",
    },
    {
      name: "escaped headers abstain",
      code: "function read(headers: Headers) { configure(headers); return Number(headers.get('x-attempt')); }",
    },
    {
      name: "escaped request abstains",
      code: "function read(request: Request) { configure(request); return Number(request.headers.get('x-attempt')); }",
    },
    {
      name: "extracted method abstains",
      code: "function read(headers: Headers) { const get = headers.get; configure(get); return Number(headers.get('x-attempt')); }",
    },
    {
      name: "visible native prototype mutation abstains",
      code: "Headers.prototype.get = custom; const headers = new Headers(); const value = Number(headers.get('x-attempt'));",
    },
    {
      name: "visible native constructor replacement abstains",
      code: "globalThis.Headers = custom; function read(request: Request) { return Number(request.headers.get('x-attempt')); }",
    },
    {
      name: "visible scalar replacement abstains",
      code: "globalThis.Number = custom; function read(request: Request) { return Number(request.headers.get('x-attempt')); }",
    },
    {
      name: "malformed scalar arity abstains",
      code: "function read(request: Request) { return Number(request.headers.get('x-attempt'), 10); }",
    },
    {
      name: "typed Zod header contract",
      code: "import { z } from 'zod'; const Attempt = z.string().default('1').transform(Number); function attempt(request: Request) { return Attempt.parse(request.headers.get('x-attempt') ?? undefined); }",
    },
    {
      name: "text headers retain transport contracts",
      code: "function read(request: Request) { return request.headers.get('authorization'); }",
    },
    {
      name: "custom scalar parser owns its contract",
      code: "function read(request: Request) { return parseAttempt(request.headers.get('x-attempt')); }",
    },
    {
      name: "unknown headers provider",
      code: "function read(headers) { return Number(headers.get('x-attempt')); }",
    },
    {
      name: "dynamic header name",
      code: "function read(request: Request, name: string) { return Number(request.headers.get(name)); }",
    },
    {
      name: "shadowed native header constructor",
      code: "class Headers { get(key) { return '1'; } } function read(headers: Headers) { return Number(headers.get('x-attempt')); }",
    },
    {
      name: "shadowed scalar parser",
      code: "function read(request: Request, Number) { return Number(request.headers.get('x-attempt')); }",
    },
    {
      name: "mutated headers alias",
      code: "function read(request: Request, custom) { let headers = request.headers; headers = custom; return Number(headers.get('x-attempt')); }",
    },
  ],
  invalid: [
    {
      name: "optional nested native scalar reports its outer owner once",
      code: "function read(headers: Headers) { return Number(Number?.(headers.get('x'))); }",
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
    {
      name: "erased wrappers do not consume the logical ownership depth bound",
      code: `function read(headers: Headers) { return Number((Number(headers.get('x'))${" as unknown".repeat(17)})); }`,
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
    {
      name: "header conversion in a radix belongs to the inner parser",
      code: "function read(headers: Headers) { return parseInt('ff', Number(headers.get('x-radix'))); }",
      errors: [{ messageId: "unparsedHeaderContract", type: "CallExpression" }],
    },
    {
      name: "separate value and radix header conversions each report",
      code: "function read(headers: Headers) { return parseInt(headers.get('x-value'), Number(headers.get('x-radix'))); }",
      errors: [{ messageId: "unparsedHeaderContract" }, { messageId: "unparsedHeaderContract" }],
    },
    {
      name: "replaced outer parser cannot suppress the native inner conversion",
      code: "globalThis.parseInt = custom; function read(headers: Headers) { return parseInt(Number(headers.get('x-value')), 10); }",
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
    {
      name: "native Request header scalar",
      code: "function read(request: Request) { return Number(request.headers.get('x-attempt')); }",
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
    {
      name: "native Headers alias",
      code: "function read(headers: Headers) { const alias = headers; return parseInt(alias.get('x-attempt'), 10); }",
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
    {
      name: "native request headers alias and fallback",
      code: "function read(request: Request) { const headers = request.headers; return Number(headers.get('x-attempt') ?? Number(headers.get('x-legacy') ?? '0')); }",
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
    {
      name: "native Headers constructor",
      code: "const headers = new Headers(); const enabled = Boolean(headers.get('x-enabled'));",
      errors: [{ messageId: "unparsedHeaderContract" }],
    },
  ],
});
