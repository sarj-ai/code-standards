import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-excess-jsx-props.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.tsx"], defaultProject: "tsconfig.json" },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures", "minimal-consumer"),
      ecmaFeatures: { jsx: true },
    },
  },
});
const JSX = "export {}; declare namespace JSX { interface Element {} interface IntrinsicElements { div: {id?: string}; span: {children?: unknown} } interface IntrinsicAttributes {key?: string} }\n";
const AVATAR = "const Avatar = ({name}: {name: string}): JSX.Element => <span>{name}</span>;\n";
const SOURCE = `${JSX}${AVATAR}`;

TESTER.run("no-excess-jsx-props", rule, {
  valid: [
    ...["name={opaque as any}", "{...{name: opaque as any}}"].map((override) => ({
      name: "sibling attributes can override a proven scalar: " + override,
      filename: "probe.tsx",
      code: `${JSX}let element: any; const opaque = {toString() {return element.props.email;}}; const Box = ({name}: {name: string}) => <span title={\`\${name}\`}/>; element = <Box {...{name: 'Ada', email: 'needed'}} ${override}/>;`,
    })),
    {name: "JSX children override a literal children field", filename: "probe.tsx", code: `${JSX}declare const child: any; const Box = ({children}: {children: string}) => <span>{\`\${children}\`}</span>; const view = <Box {...{children: 'Ada', email: 'needed'}}>{child}</Box>;`},
    {name: "async component execution needs an independent runtime proof", filename: "probe.tsx", code: `${JSX}const Box = async ({name}: {name: string}) => <span>{name}</span>; const view = <Box {...{name: 'Ada', title: 'Details'}} />;`},
    {name: "ordinary functions can inherit class dispatch metadata", filename: "probe.tsx", code: `${JSX}function Box({name}: {name: string}) {return <span>{name}</span>;} const view = <Box {...{name: 'Ada', title: 'Details'}} />;`},
    ...[
      ["Any source values cannot establish scalar runtime data", "declare const value: any;", "value"],
      ["unknown source values cannot establish scalar runtime data", "declare const value: unknown;", "value"],
      ["asserting a callback into a scalar does not remove its capabilities", "const value = () => 'Ada';", "value as unknown as string"],
      ["undefined can activate runtime defaults", "", "undefined"],
    ].map(([boundary, setup, value]) => ({
      name: "source data proof abstains: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}${setup} const Box = ({name}: {name?: string}) => <span>{name}</span>; const view = <Box {...{name: ${value}, title: 'Details'}} />;`,
    })),
    ...[
      ["captured element props alias", "let element: any; const Box = ({name}: {name: string}) => <span title={element.props.title}>{name}</span>; element = <Box {...{name: 'Ada', title: 'Details'}} />;"],
      ["callback observes the captured element", "let element: any; const Box = ({render}: {render: () => JSX.Element}) => <span>{render()}</span>; element = <Box {...{render: () => <span>{element.props.title}</span>, title: 'Details'}} />;"],
      ["object field can contain an opaque child", "declare const child: JSX.Element; const Box = ({child}: {child: JSX.Element}) => <span>{child}</span>; const view = <Box {...{child, title: 'Details'}} />;"],
      ["custom element behavior is opaque", "const Box = ({name}: {name: string}) => <custom-widget name={name}/>; const view = <Box {...{name: 'Ada', title: 'Details'}} />;"],
    ].map(([boundary, code]) => ({
      name: "a view with external runtime capabilities abstains: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}${code}`,
    })),
    {name: "named function expression can mutate its prototype through an internal binding", filename: "probe.tsx", code: `${JSX}const Box = function Impl(props: {name: string}): any {Impl.prototype.isReactComponent = {}; return null;}; const view = <Box {...{name: 'Ada', title: 'Details'}} />;`},
    ...[
      ["explicit this pseudo-parameter", "const Box = function(this: void, props: {className?: string}) {return <div {...props} />;};"],
      ["secondary default aliases the root", "const Box = (props: {className?: string}, forwarded = props) => <div {...forwarded} />;"],
      ["constructible component prototype dispatch", "function Box(props: {className?: string}): any {return null;} Box.prototype.isReactComponent = {}; Box.prototype.render = function() {return <div {...this.props} />;};"],
      ["public constructible component has an open metadata surface", "export function Box(props: {className?: string}) {return <span>{props.className}</span>;}"],
    ].map(([boundary, receiver]) => ({
      name: "receiver parameter or dispatch evidence is incomplete: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}${receiver} const view = <Box {...{className: 'card', title: 'Details'}} />;`,
    })),
    ...["@jsx h", "@jsximportsource custom-runtime", "@JSX h", "@jsxRuntime classic"].map((directive) => ({
      name: "explicit JSX directive has unsupported forwarding semantics: " + directive,
      filename: "probe.tsx",
      code: `/** ${directive} */\n${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`,
    })),
    ...["(props.render)", "(props.render as (() => JSX.Element))", "props.render!", "(props.render satisfies (() => JSX.Element))"].map((callee) => ({
      name: "an erased wrapper preserves the root method receiver: " + callee,
      filename: "probe.tsx",
      code: `${JSX}const Box = (props: {name: string; render(this: {name?: string; email?: string}): JSX.Element}) => ${callee}(); const view = <Box {...{name: 'Ada', render(this: {name?: string; email?: string}) {return <span>{this.email}</span>;}, email: 'a'}} />;`,
    })),
    {name: "value-derived namespace surfaces require another completeness proof", filename: "probe.tsx", code: `${JSX}namespace Contract {export const name = 'Ada';} const Box = (props: typeof Contract) => <span>{props.name}</span>; const view = <Box {...{name: 'Ada', title: 'Details'}} />;`},
    ...[
      ["direct DOM forwarding", "const Box = (props: {className?: string}) => <div {...props} />;"],
      ["rest DOM forwarding", "const Box = ({className, ...rest}: {className?: string}) => <div {...rest} />;"],
      ["aliased forwarding", "const Box = (props: {className?: string}) => {const forwarded = props; return <div {...forwarded} />;};"],
      ["helper forwarding", "const Box = (props: {className?: string}) => forward(props); declare function forward(value: object): JSX.Element;"],
      ["shorthand alias escape", "const Box = (props: {className?: string}) => {const forwarded = {props}; return <div {...forwarded.props} />;};"],
      ["reflection", "const Box = (props: {className?: string}) => <span>{Object.keys(props).join()}</span>;"],
      ["dynamic access", "const Box = (props: {className?: string}) => <span>{props[key]}</span>; declare const key: string;"],
      ["captured root forwarding", "const Box = (props: {className?: string}) => {const Nested = () => <div {...props} />; return <Nested />;};"],
      ["implicit receiver method can observe extras", "const Box = (props: {className?: string}) => <span>{props.toString()}</span>;"],
      ["arguments bypass destructuring", "function Box({className}: {className?: string}) {return <div {...arguments[0]} />;}"],
      ["eval bypasses destructuring", "const Box = ({className}: {className?: string}) => eval('arguments[0].title');"],
      ["opaque implementation", "declare function Box(props: {className?: string}): JSX.Element;"],
    ].map(([boundary, receiver]) => ({
      name: "intentional or unknown runtime forwarding abstains: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}${receiver} const view = <Box {...{className: 'card', title: 'Details'}} />;`,
    })),
    ...[
      ["mutable local value", "let Box = (props: {className?: string}) => <span>{props.className}</span>; Box = props => <div {...props} />;"],
      ["reassigned function declaration", "function Box(props: {className?: string}) {return <span>{props.className}</span>;} Box = props => <div {...props} />;"],
      ["mutable member receiver", "const components = {Box: (props: {className?: string}) => <span>{props.className}</span>}; components.Box = props => <div {...props} />;"],
      ["proxy preserves callable type but changes execution", "const Original = (props: {className?: string}) => <span>{props.className}</span>; const Box = new Proxy(Original, {apply(_fn, _this, [props]) {return <div {...props} />;}});"],
      ["HOC preserves callable type but changes execution", "const Original = (props: {className?: string}) => <span>{props.className}</span>; declare function wrap<T>(value: T): T; const Box = wrap(Original);"],
      ["direct eval outside the declaration", "function Box(props: {className?: string}) {return <span>{props.className}</span>;} eval('Box = props => null');"],
    ].map(([boundary, receiver]) => ({
      name: "receiver value identity is not established: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}${receiver} const view = <${boundary === "mutable member receiver" ? "components.Box" : "Box"} {...{className: 'card', title: 'Details'}} />;`,
    })),
    {name: "sloppy script receiver can expose caller arguments indirectly", filename: "probe.tsx", code: "declare namespace JSX {interface Element {} interface IntrinsicElements {span: {children?: unknown}}} declare function helper(value: string): JSX.Element; const Box = (props: {name: string}) => helper(props.name); const view = <Box {...{name: 'Ada', title: 'Details'}} />;"},
    ...["props: {name: string; displayLabel?: string}", "{name, displayLabel}: {name: string; displayLabel?: string}"].map((parameter) => ({
      name: "an omitted consumed field can invoke an inherited getter: " + parameter,
      filename: "probe.tsx",
      code: `${JSX}const Box = (${parameter}) => <span>${parameter.startsWith("props:") ? "{props.displayLabel}" : "{displayLabel}"}</span>; const view = <Box {...{name: 'Ada', email: 'a'}} />;`,
    })),
    { name: "opaque instantiated HOC has an unknown runtime forwarding surface", filename: "probe.tsx", code: `${SOURCE}declare function memo<P>(view: (props: P) => JSX.Element): (props: P) => JSX.Element; const Memo = memo(Avatar); const view = <Memo {...{name: 'Ada', email: 'a'}} />;` },
    ...["interface Props {name: string; [key: boolean]: string}", "declare const key: string; interface Props {name: string; [key]: string}"].map((contract) => ({
      name: "incomplete declared key space abstains: " + contract,
      filename: "probe.tsx",
      code: `${JSX}${contract} const Avatar = (props: Props): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`,
    })),
    { name: "resolved literal receiver keys remain supported", filename: "probe.tsx", code: `${JSX}declare const key: 'email'; interface Props {name: string; [key]?: string} const Avatar = (props: Props): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;` },
    { name: "implicit Object toString capability can be consumed", filename: "probe.tsx", code: `${JSX}function Label(props: {name: string}): JSX.Element { return <span>{props.toString()}</span>; } const view = <Label {...{name: 'Ada', toString() {return 'shown';}}} />;` },
    { name: "implicit Object hasOwnProperty capability can be consumed", filename: "probe.tsx", code: `${JSX}function Label(props: {name: string}): JSX.Element { return <span>{props.hasOwnProperty('name')}</span>; } const view = <Label {...{name: 'Ada', hasOwnProperty() {return true;}}} />;` },
    { name: "native Object declaration augmentation is a capability", filename: "probe.tsx", code: "export {}; declare global { namespace JSX { interface Element {} interface IntrinsicElements {span: {children?: unknown}} } interface Object {domainLabel(): string} } function Label(props: {name: string}): JSX.Element { return <span>{props.domainLabel()}</span>; } const view = <Label {...{name: 'Ada', domainLabel() {return 'shown';}}} />;" },
    { name: "imported re-exported structural contract retains optional fields", filename: "probe.tsx", code: `${JSX}import { Avatar as Imported } from './index'; const view = <Imported {...{name: 'Ada', avatar: 'a'}} />;` },
    { name: "unavailable imported contracts abstain", filename: "probe.tsx", code: `${JSX}import type { Props } from 'unavailable-contract'; declare function Imported(props: Props): JSX.Element; const view = <Imported {...{name: 'Ada', accountId: 'a'}} />;` },
    ...[
      "{name: 'Ada', get email() { return 'a'; }}",
      "{name: 'Ada', set email(value: string) {}}",
      "{name: 'Ada', __proto__: {email: 'a'}, accountId: 'a'}",
      "{name: 'Ada', ['__proto__']: {email: 'a'}}",
      "{name: 'Ada', [dynamic]: 'a'}",
    ].map((literal) => ({
      name: "runtime own-key proof deliberately unavailable: " + literal,
      filename: "probe.tsx",
      code: `${SOURCE}declare const dynamic: string; const view = <Avatar {...${literal}} />;`,
    })),
    ...[
      "declare function View<T extends object>(props: T): JSX.Element;",
      "declare function View(props: {name: string}): JSX.Element; declare function View(props: {id: number}): JSX.Element;",
      "declare function View(props: {name: string; kind: 'a'} | {id: number; kind: 'b'}): JSX.Element;",
      "declare const View: ((props: {name: string}) => JSX.Element) | ((props: {id: number}) => JSX.Element);",
      "declare class View { constructor(props: {name: string}); render(): JSX.Element; }",
      "declare function withAttrs<P>(view: (props: P) => JSX.Element): (props: P & Record<string, unknown>) => JSX.Element; const View = withAttrs(Avatar);",
      "declare const View: any;",
    ].map((receiver) => ({
      name: "unsupported or open receiving contract: " + receiver,
      filename: "probe.tsx",
      code: `${SOURCE}${receiver} const view = <View {...{name: 'Ada', email: 'a'}} />;`,
    })),
    ...["interface Props extends Missing {name: string}", "interface Props extends Props {name: string}", "interface Base extends Props {} interface Props extends Base {name: string}"].map((contract) => ({
      name: "incomplete inherited contract abstains: " + contract,
      filename: "probe.tsx",
      code: `${JSX}${contract} const Avatar = (props: Props): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`,
    })),
    { name: "constrained captured mapped contract is valid native code", filename: "probe.tsx", code: `${JSX}function factory<T extends 'email'>() { const Avatar = (props: Record<T, string>): JSX.Element => null!; return <Avatar {...{email: 'a'}} />; }` },
    { name: "inherited optional readonly fields are part of the contract", filename: "probe.tsx", code: `${JSX}interface Base {readonly name: string} interface Left extends Base {} interface Right extends Base {} interface Props extends Left, Right {email?: string} const Avatar = (props: Props): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;` },
    ...["Partial<T>", "Omit<T, 'name'>", "{[K in keyof T]: T[K]}"].map((props) => ({
      name: "unresolved captured mapped keys: " + props,
      filename: "probe.tsx",
      code: `${JSX}function factory<T extends object>() { const Avatar = (props: ${props}): JSX.Element => null!; return <Avatar {...{email: 'a'}} />; }`,
    })),
    { name: "unknown mapped operand abstains", filename: "probe.tsx", code: `${JSX}const Avatar = (props: Partial<unknown>): JSX.Element => null!; const view = <Avatar {...{email: 'a'}} />;` },
    { name: "concrete mapped props remain a documented false negative", filename: "probe.tsx", code: `${JSX}type User = {name: string; email: string}; const Avatar = (props: Pick<User, 'name'>): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;` },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada'}} />;` },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar name='Ada' />;` },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', key: 'a', ref: null, __self: null, __source: {fileName: 'avatar.tsx'}, 'data-id': 1, 'aria-label': 'name', 'custom-prop': true}} />;` },
    { filename: "probe.tsx", code: `${JSX}declare function Avatar(props: {name: string; [key: string]: unknown}): JSX.Element; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;` },
    { filename: "probe.tsx", code: `${SOURCE}declare const props: {name: string; email: string}; const view = <Avatar {...props} />;` },
    { filename: "probe.tsx", code: `${JSX}const view = <Missing {...{name: 'Ada', email: 'a'}} />;` },
    { filename: "probe.tsx", code: `${JSX}const view = <div {...{id: 'a', email: 'a'}} />;` },
    { filename: "probe.tsx", code: `${SOURCE}declare const other: object; const view = <Avatar {...{...other, name: 'Ada', email: 'a'}} />;` },
    { filename: "probe.tsx", code: `// @generated\n${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a'}} />;` },
  ],
  invalid: [
    {name: "flat aliases and scalar template expressions remain a closed view", filename: "probe.tsx", code: `${JSX}const Box = ({name: label}: {name: string}) => <span>{` + "`Hello ${label}`" + `}</span>; const view = <Box {...{name: 'Ada', title: 'Details'}} />;`, errors: [{messageId: "excess", data: {fields: "title"}}], output: null},
    { name: "immutable receiver aliases preserve the inspected function", filename: "probe.tsx", code: `${JSX}const Original = (props: {className: string}) => <span>{props.className}</span>; const Box = Original; const view = <Box {...{className: 'card', title: 'Details'}} />;`, errors: [{messageId: "excess", data: {fields: "title"}}], output: null },
    { name: "implemented named props read only declared fields", filename: "probe.tsx", code: `${JSX}const Box = (props: {className: string}) => <span>{props.className}</span>; const view = <Box {...{className: 'card', title: 'Details'}} />;`, errors: [{messageId: "excess", data: {fields: "title"}}], output: null },
    { name: "reserved development metadata does not hide ordinary excess fields", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', __self: null, __source: {fileName: 'avatar.tsx'}, email: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "implicit capabilities do not hide unrelated fields when receiver reads scalar data", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', toString() {return 'shown';}, email: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "import alias and re-export preserve transitive structural keys", filename: "probe.tsx", code: `${JSX}import { Avatar as Imported } from './index'; const view = <Imported {...{name: 'Ada', avatar: 'a', accountId: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "accountId" } }], output: null },
    { name: "a literal method is an enumerable own field", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email() { return 'a'; }}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "a statically computed literal key is enumerable", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', ['email']: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "hyphenated JSX keys are preserved without exempting ordinary keys", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', 'api-key': 'a', api_key: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "api_key" } }], output: null },
    { name: "transitive structural inheritance preserves every declared field", filename: "probe.tsx", code: `${JSX}interface Base {readonly name: string} interface Props extends Base {email?: string} type Alias = Props; const Avatar = (props: Alias): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a', unrelated: true}} />;`, errors: [{ messageId: "excess", data: { fields: "unrelated" } }], output: null },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a', id: 1}} />;`, errors: [{ messageId: "excess", data: { fields: "email, id" } }], output: null },
  ],
});

new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true } } } }).run("no-excess-jsx-props without types", rule, {
  valid: ["declare function Avatar(props: {name: string}): unknown; const view = <Avatar {...{name: 'Ada', email: 'a'}} />;"],
  invalid: [],
});

new RuleTester({ languageOptions: { parser: tsParser, parserOptions: {
  projectService: false,
  project: "./tsconfig.json",
  tsconfigRootDir: join(import.meta.dirname, "..", "fixtures", "minimal-consumer-no-lib"),
} } }).run("no-excess-jsx-props without core Object information", rule, {
  valid: [{filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`}],
  invalid: [],
});

for (const mode of ["preserve", "classic", "custom-factory", "custom-source", "downlevel", "commonjs"]) {
  new RuleTester({ languageOptions: { parser: tsParser, parserOptions: {
    projectService: false,
    project: `./${mode}.tsconfig.json`,
    tsconfigRootDir: join(import.meta.dirname, "..", "fixtures", "minimal-consumer"),
  } } }).run(`no-excess-jsx-props with unsupported ${mode} emitter`, rule, {
    valid: [{filename: "policy.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`}],
    invalid: [],
  });
}
