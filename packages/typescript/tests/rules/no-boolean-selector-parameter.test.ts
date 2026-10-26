import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION,
} from "../../src/rules/no-boolean-selector-parameter.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({
  languageOptions: {
    parser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

const SELECT = "if (flag) { a(); } else { b(); }";
const FORWARDING_ADAPTER =
  "declare function save(id: string, options: {required: boolean; default?: string}): void; declare function defaultValue(): string; function adapt(id: string, flag: boolean) { if (flag) { save(id, {required: true}); } else { save(id, {required: false, default: defaultValue()}); } }";
const FIXED_TOGGLE =
  "declare function Toggle(props: {onChange: (checked: boolean) => void}): unknown;";
const CONDITIONAL_HANDLER =
  "declare const compact: boolean; declare const otherHandler: (flag: boolean) => void; const handler = (flag: boolean) => flag ? a() : b();";

TESTER.run("no-boolean-selector-parameter", rule, {
  valid: [
    {
      name: "public pure return mapping",
      code: NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION.examples[1].files[0]
        .source,
    },
    ...[
      [
        "pure concise value mapping",
        'const label = (flag: boolean) => flag ? "yes" : "no";',
      ],
      [
        "pure numeric return mapping",
        "function label(flag: boolean) { if (flag) { return 1 + 2; } else { return 3 * 4; } }",
      ],
      [
        "pure return object values",
        "function label(flag: boolean) { if (flag) { return {value: 1}; } else { return {value: 2}; } }",
      ],
      [
        "ordinary returned property mapping remains data selection",
        "declare const data: {a: number; b: number}; function map(flag: boolean) { if (flag) { return data.a; } else { return data.b; } }",
      ],
      [
        "pure boolean negation values",
        "function label(flag: boolean, other: boolean) { if (flag) { return other; } else { return !other; } }",
      ],
      [
        "same lexical operation receives selected pure data",
        "const format = (value: string) => value; function label(flag: boolean) { return flag ? format('yes') : format('no'); }",
      ],
      [
        "concise same lexical operation receives selected pure data",
        "const format = (value: string) => value; const label = (flag: boolean) => flag ? format('yes') : format('no');",
      ],
      [
        "if branches feed pure data to one lexical operation",
        "const format = (value: string) => value; function label(flag: boolean) { if (flag) { return format('yes'); } else { return format('no'); } }",
      ],
      [
        "same lexical storage target receives selected pure data",
        "let value = 0; function store(flag: boolean) { if (flag) { value = 1; } else { value = 2; } }",
      ],
      [
        "concise same lexical storage target receives selected pure data",
        "let value = 0; const store = (flag: boolean) => flag ? value = 1 : value = 2;",
      ],
      [
        "boolean data assignment",
        "function store(flag: boolean) { state.flag = flag; }",
      ],
      [
        "boolean return value",
        "function enabled(flag: boolean) { return flag; }",
      ],
      [
        "explicit string mode",
        "function select(mode: 'a' | 'b') { if (mode === 'a') { a(); } else { b(); } }",
      ],
      [
        "destructured named options",
        `function select({flag}: {flag: boolean}) { ${SELECT} }`,
      ],
      [
        "optional boolean has absence state",
        `function select(flag?: boolean) { ${SELECT} }`,
      ],
      [
        "nullable boolean has absence state",
        `function select(flag: boolean | null) { ${SELECT} }`,
      ],
      [
        "literal true belongs to constant condition owner",
        `function select(flag: true) { ${SELECT} }`,
      ],
      [
        "literal false belongs to constant condition owner",
        `const select = (flag: false) => flag ? a() : b();`,
      ],
      [
        "generic constrained boolean contract",
        `function select<T extends boolean>(flag: T) { ${SELECT} }`,
      ],
      [
        "boolean is input to predicate",
        "function select(flag: boolean) { if (validate(flag)) { a(); } else { b(); } }",
      ],
      [
        "nested condition is not inferred",
        "function select(flag: boolean, other: boolean) { if (flag && other) { a(); } else { b(); } }",
      ],
      [
        "comparison is outside direct test",
        "function select(flag: boolean) { if (flag === true) { a(); } else { b(); } }",
      ],
      [
        "multiple responsibilities are not broadened",
        `function select(flag: boolean) { record(); ${SELECT} }`,
      ],
      [
        "short circuit can be optional guarded work",
        "function maybe(flag: boolean) { flag && a(); }",
      ],
      [
        "guard return is not alternate dispatch",
        "function maybe(flag: boolean) { if (!flag) return; a(); }",
      ],
      [
        "local alias is not inferred",
        "function select(flag: boolean) { const enabled = flag; return enabled ? a() : b(); }",
      ],
      [
        "outer boolean is not inner callable parameter",
        "function outer(flag: boolean) { return function inner() { if (flag) { a(); } else { b(); } }; }",
      ],
      [
        "inline native callback",
        `events.subscribe((flag: boolean) => { ${SELECT} });`,
      ],
      [
        "inline concise callback remains exempt without contextual type",
        "events.subscribe((flag: boolean) => flag ? a() : b());",
      ],
      [
        "inline function callback",
        `events.subscribe(function(flag: boolean) { ${SELECT} });`,
      ],
      [
        "explicit callable variable contract",
        `const handler: (flag: boolean) => void = (flag: boolean) => { ${SELECT} };`,
      ],
      [
        "explicit instantiated generic callable contract",
        `type Listener<T> = (value: T) => void; const handler: Listener<boolean> = (flag: boolean) => { ${SELECT} };`,
      ],
      [
        "parenthesized concise generic callable binding",
        "type Listener<T> = (value: T) => void; const handler: Listener<boolean> = ((flag: boolean) => flag ? a() : b());",
      ],
      [
        "erased satisfies wrapper preserves generic callable binding",
        "type Listener<T> = (value: T) => void; const handler: Listener<boolean> = ((flag: boolean) => flag ? a() : b()) satisfies Listener<boolean>;",
      ],
      [
        "typed inline concise callback",
        "declare function accept(handler: (flag: boolean) => void): void; accept((flag: boolean) => flag ? a() : b());",
      ],
      [
        "named callback passed to typed subscriber",
        `declare function accept(handler: (flag: boolean) => void): void; function handler(flag: boolean) { ${SELECT} } accept(handler);`,
      ],
      [
        "immutable callback alias preserves external contract",
        `declare function accept(handler: (flag: boolean) => void): void; const handler = (flag: boolean) => { ${SELECT} }; const alias = handler; accept(alias);`,
      ],
      [
        "contextually typed object callback with arbitrary property name",
        `const handlers: {deliver: (flag: boolean) => void} = { deliver(flag: boolean) { ${SELECT} } };`,
      ],
      [
        "interface member requires boolean signature",
        `interface Port { select(flag: boolean): void; } class Service implements Port { select(flag: boolean) { ${SELECT} } }`,
      ],
      [
        "unique symbol inherited member contract",
        `declare const key: unique symbol; interface Port { [key](flag: boolean): void; } class Service implements Port { [key](flag: boolean) { ${SELECT} } }`,
      ],
      [
        "inherited method contract",
        `class Base { select(flag: boolean): void {} } class Service extends Base { override select(flag: boolean) { ${SELECT} } }`,
      ],
      [
        "setter has required assignment contract",
        `class State { set enabled(flag: boolean) { ${SELECT} } }`,
      ],
      [
        "bound receiver passed to typed callback retains its contract",
        `declare function accept(handler: (flag: boolean) => void): void; class Service { select(flag: boolean) { ${SELECT} } } const service = new Service(); accept(service.select.bind(service));`,
      ],
      [
        "upstream on-property exemption remains documented",
        `const handlers = { onState: (flag: boolean) => { ${SELECT} } };`,
      ],
    ].map(([name, code]) => ({ name, code })),
    {
      name: "generated code",
      filename: "selector.generated.ts",
      code: `function select(flag: boolean) { ${SELECT} }`,
    },
    {
      name: "reasoned exact suppression",
      code: `function select(flag: boolean) {\n// eslint-disable-next-line @rule-tester/no-boolean-selector-parameter -- Reviewed legacy public API remains stable.\n${SELECT}\n}`,
    },
    {
      name: "named actual JSX callback",
      filename: "component.tsx",
      code: `declare function Toggle(props: {onChange: (flag: boolean) => void}): unknown; const handler = (flag: boolean) => { ${SELECT} }; const element = <Toggle onChange={handler} />;`,
    },
    {
      name: "named JSX callback retains independently instantiated generic prop",
      filename: "component.tsx",
      code: "type Listener<T> = (value: T) => void; declare function Toggle(props: {onChange: Listener<boolean>}): unknown; const handler = (flag: boolean) => flag ? a() : b(); const element = <Toggle onChange={handler} />;",
    },
    {
      name: "actual JSX callback forwards its unchanged boolean at the second adapter parameter",
      filename: "component.tsx",
      code: `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} const element = <Toggle onChange={checked => { adapt('field', checked); }} />;`,
    },
    {
      name: "typed API callback forwards its unchanged boolean at the second adapter parameter",
      code: `${FORWARDING_ADAPTER} declare function subscribe(callback: (checked: boolean) => void): void; subscribe(checked => adapt('field', checked));`,
    },
    {
      name: "immutable conditional callback alias preserves its false value arm",
      filename: "component.tsx",
      code: `${CONDITIONAL_HANDLER} ${FIXED_TOGGLE} const chosen = compact ? otherHandler : handler; const element = <Toggle onChange={chosen} />;`,
    },
    {
      name: "immutable conditional callback alias preserves its true value arm",
      filename: "component.tsx",
      code: `${CONDITIONAL_HANDLER} ${FIXED_TOGGLE} const chosen = compact ? handler : otherHandler; const element = <Toggle onChange={chosen} />;`,
    },
    {
      name: "callable component alias fixes independently authored generic props",
      filename: "component.tsx",
      code: "type Listener<T> = (value: T) => void; type FC<P> = (props: P) => unknown; type Props = {onChange: Listener<boolean>}; declare const Toggle: FC<Props>; const handler = (flag: boolean) => flag ? a() : b(); const element = <Toggle onChange={handler} />;",
    },
    {
      name: "callable interface component fixes independently authored generic props",
      filename: "component.tsx",
      code: "type Listener<T> = (value: T) => void; interface ForwardComponent<P> { (props: P): unknown; displayName?: string; } type Props = {onChange: Listener<boolean>}; declare const Toggle: ForwardComponent<Props>; const handler = (flag: boolean) => flag ? a() : b(); const element = <Toggle onChange={handler} />;",
    },
  ],
  invalid: [
    {
      name: "routes literal calls to existing operations",
      code: NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION.examples[2].files[0]
        .source,
      errors: [
        { messageId: "booleanSelector", data: { parameterName: "premium" } },
      ],
      output:
        NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION.examples[2].fixedFiles[0]
          .source,
    },
    {
      name: "public concise dispatch",
      code: NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION.examples[0].files[0]
        .source,
      errors: [
        { messageId: "booleanSelector", data: { parameterName: "premium" } },
      ],
      output: null,
    },
    ...[
      [
        "native block dispatcher",
        `function select(flag: boolean) { ${SELECT} }`,
      ],
      [
        "returned effectful conditional",
        "function select(flag: boolean) { return flag ? a() : b(); }",
      ],
      [
        "expression statement conditional",
        "function select(flag: boolean) { flag ? a() : b(); }",
      ],
      [
        "native arrow block",
        `const select = (flag: boolean) => { ${SELECT} };`,
      ],
      [
        "native function expression",
        `const select = function(flag: boolean) { ${SELECT} };`,
      ],
      [
        "concise negated arrow",
        "const select = (flag: boolean) => !flag ? b() : a();",
      ],
      [
        "concise parentheses",
        "const select = (flag: boolean) => (flag ? a() : b());",
      ],
      [
        "async concise dispatch",
        "const select = async (flag: boolean) => flag ? await a() : await b();",
      ],
      [
        "async block dispatch",
        `async function select(flag: boolean) { ${SELECT} }`,
      ],
      [
        "generator dispatch",
        "function* select(flag: boolean) { return flag ? yield a() : yield b(); }",
      ],
      [
        "boolean type alias",
        `type Flag = boolean; function select(flag: Flag) { ${SELECT} }`,
      ],
      [
        "inferred boolean default",
        `function select(flag = false) { ${SELECT} }`,
      ],
      [
        "boolean literal union is broad boolean",
        `function select(flag: true | false) { ${SELECT} }`,
      ],
      [
        "class method without external contract",
        `class Service { select(flag: boolean) { ${SELECT} } }`,
      ],
      [
        "unrelated heritage does not hide own method",
        `interface Named { name: string; } class Service implements Named { name = 'service'; select(flag: boolean) { ${SELECT} } }`,
      ],
      [
        "a handler-like variable name is not a contract",
        `const onState = (flag: boolean) => { ${SELECT} };`,
      ],
      [
        "concise property name alone does not prove callback contract",
        "const handlers = { onState: (flag: boolean) => flag ? a() : b() };",
      ],
      [
        "constructor choice has effects",
        "const create = (flag: boolean) => flag ? new A() : new B();",
      ],
      [
        "array retains nested calls",
        "const create = (flag: boolean) => flag ? [a()] : [b()];",
      ],
      [
        "object retains nested calls",
        "const create = (flag: boolean) => flag ? {value: a()} : {value: b()};",
      ],
      [
        "call inside return mapping is not proven pure",
        "function label(flag: boolean) { if (flag) { return format('yes'); } else { return format('no'); } }",
      ],
      [
        "same callee with effectful arguments still dispatches effects",
        "const format = (value: string) => value; const label = (flag: boolean) => flag ? format(a()) : format(b());",
      ],
      [
        "one returning branch is not equivalent selected data flow",
        "declare function save(value: number): number; function select(flag: boolean) { if (flag) { return save(1); } else { save(2); } }",
      ],
      [
        "computed receiver effects are not data selection",
        "const label = (flag: boolean) => flag ? receiver().format('yes') : receiver().format('no');",
      ],
      [
        "computed assignment target effects are not data selection",
        "const store = (flag: boolean) => flag ? target()[key()] = 1 : target()[key()] = 2;",
      ],
      [
        "effectful returned property receiver remains operation selection",
        "function map(flag: boolean) { if (flag) { return receiver().a; } else { return receiver().b; } }",
      ],
      [
        "effectful returned computed key remains operation selection",
        "declare const data: Record<string, number>; function map(flag: boolean) { if (flag) { return data[firstKey()]; } else { return data[secondKey()]; } }",
      ],
    ].map(([name, code]) => ({
      name,
      code,
      errors: [{ messageId: "booleanSelector" as const }],
      output: null,
    })),
    {
      name: "independent dispatcher remains checked in JSX",
      filename: "component.tsx",
      code: `function select(flag: boolean) { ${SELECT} } const element = <div />;`,
      errors: [{ messageId: "booleanSelector" }],
      output: null,
    },
    {
      name: "concise helper remains checked in JSX",
      filename: "component.tsx",
      code: "const select = (flag: boolean) => flag ? a() : b(); const element = <div />;",
      errors: [{ messageId: "booleanSelector" }],
      output: null,
    },
    {
      name: "JSX generic inferred from callback does not author a boolean contract",
      filename: "component.tsx",
      code: "type Listener<T> = (value: T) => void; declare function Toggle<T>(props: {onChange: Listener<T>}): unknown; const handler = (flag: boolean) => flag ? a() : b(); const element = <Toggle onChange={handler} />;",
      errors: [{ messageId: "booleanSelector" }],
      output: null,
    },
    ...[
      [
        "forwarded literal chooses an operation",
        `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} const element = <Toggle onChange={checked => adapt('field', true)} />;`,
      ],
      [
        "forwarded negation derives a different boolean",
        `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} const element = <Toggle onChange={checked => adapt('field', !checked)} />;`,
      ],
      [
        "captured boolean is not the callback input",
        `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} declare const captured: boolean; const element = <Toggle onChange={checked => adapt('field', captured)} />;`,
      ],
      [
        "member boolean is not the callback input",
        `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} declare const state: {value: boolean}; const element = <Toggle onChange={checked => adapt('field', state.value)} />;`,
      ],
      [
        "reassigned callback parameter loses forwarding ownership",
        `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} const element = <Toggle onChange={checked => { checked = false; adapt('field', checked); }} />;`,
      ],
      [
        "spread argument forwarding is outside the direct proof",
        `${FORWARDING_ADAPTER} ${FIXED_TOGGLE} const element = <Toggle onChange={checked => adapt(...(['field', checked] as const))} />;`,
      ],
      [
        "generic JSX inferred from wrapper does not own forwarded boolean",
        `${FORWARDING_ADAPTER} declare function Toggle<T>(props: {onChange: (checked: T) => void}): unknown; const element = <Toggle onChange={(checked: boolean) => adapt('field', checked)} />;`,
      ],
      [
        "ordinary wrapper without an external callback contract still dispatches",
        `${FORWARDING_ADAPTER} const dispatch = (checked: boolean) => adapt('field', checked);`,
      ],
      [
        "unused conditional alias proves no callback contract",
        `${CONDITIONAL_HANDLER} const chosen = compact ? otherHandler : handler;`,
      ],
      [
        "conditional test is not a callback value arm",
        `${CONDITIONAL_HANDLER} ${FIXED_TOGGLE} declare const fallback: (flag: boolean) => void; const chosen = handler ? otherHandler : fallback; const element = <Toggle onChange={chosen} />;`,
      ],
      [
        "mutable conditional alias does not prove callback ownership",
        `${CONDITIONAL_HANDLER} ${FIXED_TOGGLE} let chosen = compact ? otherHandler : handler; chosen = otherHandler; const element = <Toggle onChange={chosen} />;`,
      ],
      [
        "generic callable component still infers domain from callback",
        "type Listener<T> = (value: T) => void; type GenericFC = <T>(props: {onChange: Listener<T>}) => unknown; declare const Toggle: GenericFC; const handler = (flag: boolean) => flag ? a() : b(); const element = <Toggle onChange={handler} />;",
      ],
    ].map(([name, code]) => ({
      name,
      code,
      filename: "component.tsx",
      errors: [{ messageId: "booleanSelector" as const }],
      output: null,
    })),
  ],
});

const UNTYPED_TESTER = new RuleTester({ languageOptions: { parser } });
UNTYPED_TESTER.run(
  "no-boolean-selector-parameter without type information",
  rule,
  {
    valid: [
      { code: `function select(flag: boolean) { ${SELECT} }` },
      { code: "const select = (flag: boolean) => flag ? a() : b();" },
    ],
    invalid: [],
  },
);
