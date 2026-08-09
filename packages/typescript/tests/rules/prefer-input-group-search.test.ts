import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferInputGroupSearchDocumentation } from "../../src/rules/prefer-input-group-search.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

const imports = `
  import { Search } from "lucide-react";
  import { Input } from "@/components/ui/input";
  import { InputGroup } from "@/components/ui/input-group";
`;

ruleTester.run("prefer-input-group-search", rule, {
  valid: [
    {
      name: "does not prescribe an optional primitive without local adoption evidence",
      code: `import { Search } from "lucide-react"; import { Input } from "@/components/ui/input"; <div><Search /><Input /></div>`,
    },
    {
      name: "does not confuse a search action with input decoration",
      code: `import { Search } from "lucide-react"; import { Input } from "@/components/ui/input"; <div><button><Search /></button><Input placeholder="Rename file" /></div>`,
    },
    { name: "public no-match example", filename: preferInputGroupSearchDocumentation.examples[0].focusPath, code: preferInputGroupSearchDocumentation.examples[0].files[0].source },
    {
      name: "accepts the shared input group",
      code: `
        import { Search } from "lucide-react";
        import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
        <InputGroup><InputGroupAddon><Search /></InputGroupAddon><InputGroupInput /></InputGroup>
      `,
    },
    {
      name: "does not pair a grouped search with an unrelated input",
      code: `
        import { Search } from "lucide-react";
        import { Input } from "@/components/ui/input";
        import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
        <form>
          <InputGroup><InputGroupAddon><Search /></InputGroupAddon><InputGroupInput /></InputGroup>
          <section><Input /></section>
        </form>
      `,
    },
    {
      name: "accepts unrelated locally declared components",
      code: `<div><Search /><Input /></div>`,
    },
    {
      name: "accepts similarly named imports from unrelated modules",
      code: `
        import { Search } from "@/components/search";
        import { Input } from "third-party-kit";
        <div><Search /><Input /></div>
      `,
    },
    {
      name: "accepts search and input in separate visual regions",
      code: `${imports}<form><header><Search /></header><section><div><Input /></div></section></form>`,
    },
    {
      name: "accepts an input without a search icon",
      code: `${imports}<div><Input /></div>`,
    },
    {
      name: "accepts a search icon without an input",
      code: `${imports}<div><Search /></div>`,
    },
  ],
  invalid: [
    {
      name: "recognizes official lucide search aliases",
      code: `import { SearchIcon } from "lucide-react"; import { Input } from "@/components/ui/input"; import { InputGroup } from "@/components/ui/input-group"; <div><SearchIcon /><Input /></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    { name: "public match example", filename: preferInputGroupSearchDocumentation.examples[1].focusPath, code: preferInputGroupSearchDocumentation.examples[1].files[0].source, errors: [{ messageId: "preferInputGroup" }] },
    {
      name: "rejects direct search and input siblings",
      code: `${imports}<div><Search /><Input /></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "rejects reversed controls with intervening siblings",
      code: `${imports}<div><Input /><span>Search</span><Search /></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "resolves aliased imports",
      code: `
        import { Search as SearchIcon } from "lucide-react";
        import { Input as TextInput } from "@/components/ui/input";
        import { InputGroup } from "@/components/ui/input-group";
        <div><SearchIcon /><TextInput /></div>
      `,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "rejects a nested icon",
      code: `${imports}<div><span><Search /></span><Input /></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "rejects a nested input",
      code: `${imports}<div><Search /><span><Input /></span></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "rejects a loading search wrapper",
      code: `${imports}<div><Search /><Input />{pending ? <Spinner /> : null}</div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "rejects a clearable search wrapper",
      code: `${imports}<div><Search /><Input />{value ? <Button><X /></Button> : null}</div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "rejects a constrained search wrapper",
      code: `${imports}<div className="relative max-w-md"><Search className="absolute" /><Input placeholder="Search" /></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
    {
      name: "reports a wrapper once when it contains multiple inputs",
      code: `${imports}<div><Search /><Input /><Input /></div>`,
      errors: [{ messageId: "preferInputGroup" }],
    },
  ],
});
