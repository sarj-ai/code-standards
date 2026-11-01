import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import ts from "typescript";
import { afterAll, describe, expect, it } from "vitest";

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
const JSX = "/// <reference path=\"./jsx-runtime.d.ts\" />\nexport {}; declare namespace JSX { interface Element {} interface IntrinsicElements { div: {id?: string}; span: {children?: unknown} } interface IntrinsicAttributes {key?: string} }\n";
const AVATAR = "const Avatar = ({name}: {name: string}): JSX.Element => <span>{name}</span>;\n";
const SOURCE = `${JSX}${AVATAR}`;
const IMPORTED_CONTRACT_CASE = `${JSX}import { Avatar as Imported } from './index'; const view = <Imported {...{name: 'Ada', avatar: 'a', accountId: 'a'}} />;`;
const SAFE_REFLECTION = [
  ["reflection on a fresh unrelated const object", "const target = {}; Object.defineProperty(target, 'ref', {get() {return null;}});"],
  ["native constructor alias with an unrelated target", "const Native = Object; const target = {}; Native.defineProperty(target, 'ref', {value: null});"],
  ["a direct fresh target", "Reflect.defineProperty({}, 'ref', {value: null});"],
  ["a same-spelled local object is not the native constructor", "const Object = {prototype: {}, defineProperty(..._args: unknown[]) {}}; Object.defineProperty(Object.prototype, 'ref', {value: null});"],
] as const;

TESTER.run("no-excess-jsx-props", rule, {
  valid: [
    {name: "a later direct eval invalidates a queued private element", filename: "probe.tsx", code: `${SOURCE}const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const summary = {name: (element as {props: {name: string}}).props.name}; export {summary}; eval("void 0");`},
    {name: "default-project unused-local errors make imported alias evidence unavailable", filename: "probe.tsx", code: IMPORTED_CONTRACT_CASE},
    ...[
      ["unresolved lexical value", "runtimeCapability;"],
      ["unresolved shorthand value", "const context = {runtimeCapability};"],
      ["a type-only name used as a value", "type RuntimeCapability = string; RuntimeCapability;"],
      ["an erased namespace used as a value", "namespace RuntimeCapability {export interface Contract {readonly ready: boolean}} RuntimeCapability;"],
      ["a const-enum name has no guaranteed emitted binding", "const enum RuntimeCapability {Ready = 1} RuntimeCapability;"],
      ["an erased imported value retains its native target", "import type {scalarName as runtimeCapability} from './source-values'; runtimeCapability;"],
      ["a named type-only re-export retains its native target", "import {scalarName as runtimeCapability} from './type-only-values'; runtimeCapability;"],
      ["a type-only export star hides alias provenance", "import {scalarName as runtimeCapability} from './type-only-star-values'; runtimeCapability;"],
      ["a suppressed type-only export-star error is unavailable proof", "import {scalarName as runtimeCapability} from './type-only-star-values';\n// @ts-ignore\nruntimeCapability;"],
      ["a const-enum-only namespace is erased without a native error", "namespace RuntimeCapability {export const enum Ready {Yes = 1}} RuntimeCapability;"],
      ["a real namespace value remains conservatively unsupported", "namespace RuntimeCapability {export const ready = true} RuntimeCapability;"],
      ["an ambient initialized global retains its existing veto", "declare global {const runtimeCapability = true;} runtimeCapability;"],
      ["a global typed by another module has no runtime import proof", "import type {CapabilityMarker} from './ambient-capability'; consumerRuntimeCapability;"],
    ].map(([boundary, setup]) => ({
      name: "unavailable runtime value information abstains: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: 'Ada', email: 'needed'}}/>;`,
    })),
    {name: "a declaration-file global has no runtime implementation proof", filename: "probe.tsx", code: `/// <reference path="./ambient-runtime-values.d.ts" />\n${SOURCE}const installed = contractRuntime.ready; const view = <Avatar {...{name: 'Ada', email: 'a'}}/>;`},
    ...SAFE_REFLECTION.map(([boundary, setup]) => ({
      name: "known harmless call remains outside the effect proof: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: 'Ada', email: 'a'}}/>;`,
    })),
    ...[
      ["erased receiver metadata", "(Avatar as unknown as {defaultProps: {email: string}}).defaultProps"],
      ["an immutable alias preserves callable identity", "const runtime = Avatar as unknown as {defaultProps: {email: string}}; runtime.defaultProps"],
    ].map(([boundary, target]) => ({
      name: "callable metadata can observe field omission: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}const target = {ref: 0}; ${target} = {get email() {target.ref = 1; return 'fallback';}}; const view = <Avatar {...{name: 'Ada', email: 'needed'}}/>; const observation = target.ref; export {observation};`,
    })),
    ...[
      ["implicit callable metadata assignment", "const target = {ref: 0}; for ((Avatar as unknown as {defaultProps: {email: string}}).defaultProps of [{get email() {target.ref = 1; return 'fallback';}}]) {}"],
      ["a fresh write target does not prove iterator effects", "const target = {name: ''}; for (target.name of ['Ada']) {}"],
      ["enumeration and implicit member assignment need a separate proof", "const target = {name: ''}; for (target.name in {name: 'Ada'}) {}"],
    ].map(([boundary, setup]) => ({
      name: "iteration remains outside the runtime effect proof: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: 'Ada', email: 'needed'}}/>;`,
    })),
    ...[
      ["opaque whole element", "const element = <Avatar {...{name: 'Ada', email: 'needed'}}/>; inspect(element);"],
      ["opaque whole props", "const element = <Avatar {...{name: 'Ada', email: 'needed'}}/>; inspect((element as {props: unknown}).props);"],
      ["observed extra field", "const element = <Avatar {...{name: 'Ada', email: 'needed'}}/>; const shown = (element as {props: {email: string}}).props.email;"],
      ["a result alias needs its own escape proof", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const alias = element;"],
      ["captured result", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const later = () => (element as {props: {name: string}}).props.name;"],
      ["named export", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; export {element};"],
      ["direct export", "export const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>;"],
      ["default export", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; export default element;"],
      ["returned result", "function make() {const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; return element;}"],
      ["direct returned JSX", "function make() {return <Avatar {...{name: 'Ada', email: 'unused'}}/>;}"],
      ["forwarded child", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const parent = <span>{element}</span>;"],
      ["whole-result aggregate", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const values = [element];"],
      ["property write", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; (element as {props: {name: string}}).props.name = 'changed';"],
      ["type observation", "const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; type Observed = typeof element;"],
    ].map(([boundary, body]) => ({
      name: "created element escapes the closed value proof: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${body.includes("inspect(") ? "declare function inspect(value: unknown): void; " : ""}${body}`,
    })),
    ...[
      ["inherited React ref getter", "Object.defineProperty(Object.prototype, 'ref', {configurable: true, get() {return null;}});"],
      ["const native constructor alias", "const Native = Object; Native.defineProperty(Native.prototype, 'ref', {get() {return null;}});"],
      ["const native prototype alias", "const base: any = Object.prototype; base.ref = null;"],
      ["erased globalThis constructor", "const globals: any = globalThis; globals.Object.defineProperty(globals.Object.prototype, 'ref', {get() {return null;}});"],
      ["uncertain reflective target", "declare const target: object; Object.defineProperty(target, 'ref', {get() {return null;}});"],
      ["escaped reflective method", "declare const target: object; const define = Object.defineProperty; define.call(null, target, 'ref', {value: null});"],
      ["bound reflective method", "declare const target: object; const define = Object.defineProperty.bind(Object, target);"],
      ["native constructor method mutation", "Object.defineProperty = ((...args: any[]) => args[0]) as typeof Object.defineProperty;"],
      ["native reflection namespace", "Reflect.defineProperty(Object.prototype, 'ref', {value: null});"],
      ["prototype discovery", "const base = Object.getPrototypeOf({});"],
      ["unresolved dynamic module", "declare const moduleName: string; void import(moduleName);"],
      ["unresolved value module", "import 'unavailable-effect-module';"],
      ["relative project effect import", "import './prototype-effects';"],
      ["re-exported project effect", "import './prototype-effects-index';"],
      ["resolved bare project path alias", "import 'contract-effects';"],
      ["literal dynamic project import", "void import('./prototype-effects');"],
      ["native indirect eval", "(0, eval)('void 0');"],
      ["native Function constructor", "const dynamic = new Function('return null');"],
      ["aliased native dynamic code", "const execute = eval; execute('void 0');"],
      ["an inherited constructor has no proven callable target", "(() => {}).constructor('return null')();"],
      ["an asserted constructor still invokes opaque code", "const make = (() => {}).constructor as unknown as (source: string) => () => void; make('return null')();"],
      ["tagged templates invoke opaque code", "((() => {}).constructor`return null`)``;"],
      ["ambient property signatures do not exclude getters", "declare const installer: {readonly ready: boolean}; const installed = installer.ready;"],
      ["opaque globalThis members can be getters", "const installed = (globalThis as unknown as {contractRuntime: {readonly ready: boolean}}).contractRuntime.ready;"],
      ["shorthand aliases retain their native global value", "const context = {globalThis}; const installed = (context.globalThis as unknown as {contractRuntime: {readonly ready: boolean}}).contractRuntime.ready;"],
    ].map(([boundary, setup]) => ({
      name: "ordinary Object runtime proof abstains: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: 'Ada', email: 'a'}}/>;`,
    })),
    ...[
      ["argument read", "settings: {readonly ready: boolean}", "const installed = settings.ready;"],
      ["a destructured argument reads even an unused field", "{ready}: {readonly ready: boolean}", ""],
    ].map(([boundary, parameter, setup]) => ({
      name: "element creation has an unproved argument capability: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}export function observe(${parameter}) {${setup} ${AVATAR} const element = <Avatar {...{name: 'Ada', email: 'needed'}}/>; const shown = (element as {props: {name: string}}).props.name; return shown;}`,
    })),
    {name: "an exported captured object can expose a getter before creation", filename: "probe.tsx", code: `${JSX}export const settings = {ready: true}; export function observe() {const installed = settings.ready; ${AVATAR} const element = <Avatar {...{name: 'Ada', email: 'needed'}}/>; const shown = (element as {props: {name: string}}).props.name; return shown;}`},
    ...[
      ["an opaque template operand", "declare const value: unknown;", "`Hello ${value}`"],
      ["typeof an opaque operand", "declare const value: unknown;", "typeof value"],
      ["arithmetic on a declared value", "declare const value: number;", "value + 'Ada'"],
      ["an opaque conditional test", "declare const enabled: boolean;", "enabled ? 'Ada' : 'Grace'"],
      ["a discarded opaque call", "declare function touch(): void;", "(touch(), 'Ada')"],
    ].map(([boundary, setup, value]) => ({
      name: "primitive results still evaluate unproved operands: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: ${value}, email: 'a'}} />;`,
    })),
    {name: "an inner own ref does not prove caller prototype safety", filename: "probe.tsx", code: `${JSX}Object.defineProperty(Object.prototype, 'ref', {get() {return null;}}); const Box = ({name}: {name: string}) => <span ref={null}>{name}</span>; const view = <Box {...{name: 'Ada', email: 'a'}}/>;`},
    {
      name: "coercing a JSX object can observe the outer forwarded props",
      filename: "probe.tsx",
      code: `${JSX}let element: any; Object.prototype.toString = function() {return element.props.email;}; const Box = ({name}: {name: string}) => <span>{\`\${<span>{name}</span>}\`}</span>; element = <Box {...{name: 'Ada', email: 'needed'}}/>;`,
    },
    ...[
      "<span>{`${<span/>}`}</span>",
      "<span>{'name: ' + <span/>}</span>",
      "<span title={`${<span/>}`}/>",
      "<span>{name ? `${<span/>}` : name}</span>",
    ].map((body) => ({
      name: "JSX objects are not scalar coercion operands: " + body,
      filename: "probe.tsx",
      code: `${JSX}const Box = ({name}: {name: string}) => ${body}; const view = <Box {...{name: 'Ada', email: 'needed'}}/>;`,
    })),
    ...[
      ["field mutation", "const user = {name: 'Ada'}; user.name = opaque as unknown as string;"],
      ["later mutation is still visible", "const user = {name: 'Ada'}; const update = () => {user.name = opaque as unknown as string;};"],
      ["whole object alias", "const user = {name: 'Ada'}; const alias = user;"],
      ["reflection or helper escape", "const user = {name: 'Ada'}; Object.keys(user);"],
      ["accessors can mutate their receiver", "const user = {name: 'Ada', get other() {this.name = opaque as unknown as string; return '';}}; const other = user.other;"],
      ["method receiver can mutate", "const user = {name: 'Ada', touch() {this.name = opaque as unknown as string;}}; user.touch();"],
      ["erased method wrapper keeps its receiver", "const user = {name: 'Ada', touch() {this.name = opaque as unknown as string;}}; (user.touch as () => void)();"],
      ["destructuring assignment target", "const user = {name: 'Ada'}; ({value: user.name} = {value: opaque as unknown as string});"],
      ["array assignment target", "const user = {name: 'Ada'}; [user.name] = [opaque as unknown as string];"],
      ["deleting a field through an erased object wrapper", "const user = {name: 'Ada'}; delete (user as {name?: string}).name;"],
      ["dynamic property access", "const user = {name: 'Ada'}; const key = 'name'; const other = user[key];"],
      ["exported mutable object surface", "export const user = {name: 'Ada'};"],
      ["type-only references are outside the initial footprint", "const user = {name: 'Ada'}; type User = typeof user;"],
      ["erasure in a property initializer", "const user = {name: opaque as unknown as string};"],
      ["shorthand preserves an asserted source value", "const name = opaque as unknown as string; const user = {name};"],
      ["erasure in an object initializer", "const user = {name: opaque} as unknown as {name: string};"],
      ["hidden undefined source field", "const user = {name: undefined as unknown as string};"],
    ].map(([boundary, setup]) => ({
      name: "a local object source lacks immutable scalar provenance: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}let element: any; const opaque = {toString() {return element.props.email;}}; ${setup} const Box = ({name}: {name: string}) => <span>{\`\${name}\`}</span>; element = <Box {...{name: user.name, email: 'needed'}} />;`,
    })),
    {name: "await using can implicitly expose a source object to a disposer", filename: "probe.tsx", code: `${SOURCE}declare global {interface Object {[Symbol.asyncDispose](): Promise<void>}} async function make() {await using user = {name: 'Ada'}; return () => <Avatar {...{name: user.name, email: 'a'}}/>;} void make();`},
    ...["eval", "(eval as typeof eval)", "((eval as <T>(code: string) => any)<string>)"].map((callee) => ({
      name: "a later direct eval invalidates local object provenance: " + callee,
      filename: "probe.tsx",
      code: `${SOURCE}const user = {name: 'Ada'}; const make = () => <Avatar {...{name: user.name, email: 'a'}}/>; ${callee}('user.name = {toString() {return "changed"}}'); make();`,
    })),
    ...[
      ["const alias retains an asserted object", "const value = opaque as unknown as string;", "value"],
      ["transitive alias retains an asserted object", "const raw = opaque as unknown as string; const value = raw;", "value"],
      ["annotating Any does not produce a primitive", "const raw: any = opaque; const value: string = raw;", "value"],
      ["non-null assertion retains an opaque alias", "const raw = opaque as unknown as string | null; const value = raw!;", "value"],
      ["a mutable scalar binding has no immutable value proof", "let value = 'Ada'; value = opaque as unknown as string;", "value"],
      ["a getter signature cannot prove its actual result", "const holder = {get value(): string {return opaque as unknown as string;}};", "holder.value"],
      ["an opaque producer signature cannot prove its actual result", "const produce = (): string => opaque as unknown as string;", "produce()"],
      ["a tagged template can return an asserted object", "const tag = (_strings: TemplateStringsArray): string => opaque as unknown as string;", "tag`Ada`"],
      ["a logical result can preserve an opaque operand", "const raw = opaque as unknown as string;", "true && raw"],
      ["a conditional result can preserve an opaque branch", "const raw = opaque as unknown as string;", "true ? raw : 'Ada'"],
      ["an alias can hide undefined and activate runtime defaults", "const value = undefined as unknown as string;", "value"],
    ].map(([boundary, setup, value]) => ({
      name: "source primitive provenance abstains: " + boundary,
      filename: "probe.tsx",
      code: `${JSX}let element: any; const opaque = {toString() {return element.props.email;}}; ${setup} const Box = ({name}: {name: string}) => <span>{\`\${name}\`}</span>; element = <Box {...{name: ${value}, email: 'needed'}} />;`,
    })),
    {name: "imported scalar signatures remain opaque through re-exports", filename: "probe.tsx", code: `${SOURCE}import {scalarName} from './index'; const view = <Avatar {...{name: scalarName, email: 'a'}} />;`},
    {name: "long source alias paths abstain within the analysis resource budget", filename: "probe.tsx", code: `${SOURCE}const value0 = 'Ada'; ${Array.from({length: 256}, (_, index) => `const value${index + 1}: string = value${index};`).join(" ")} const view = <Avatar {...{name: value256, email: 'a'}} />;`},
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
    ...[
      ["a control-flow label is not a value read", "runtimeCapability: {break runtimeCapability;}"],
      ["an own-property key is not a value read", "const own = {runtimeCapability: true}; const {runtimeCapability: ready} = own;"],
      ["type bindings remain erased", "type RuntimeCapability = string; const text: RuntimeCapability = 'Ada'; export {RuntimeCapability};"],
      ["a type parameter is erased", "function unused<RuntimeCapability>() {return 'Ada';}"],
      ["a type-only namespace is erased", "namespace Types {export interface Contract {readonly name: string}}"],
      ["implements has no runtime value reads", "interface Contract {readonly name: string} class Value implements Contract {readonly name = 'Ada';}"],
      ["intrinsic and attribute names are not lexical reads", "const other = <span data-runtime='ordinary'/>;"],
    ].map(([boundary, setup]) => ({
      name: "non-evaluated names preserve the forwarding finding: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: 'Ada', email: 'unused'}}/>;`,
      errors: [{messageId: "excess" as const, data: {fields: "email"}}],
      output: null,
    })),
    {name: "an unused argument does not introduce a runtime read", filename: "probe.tsx", code: `${JSX}export function observe(_unused: {readonly ready: boolean}) {const settings = {ready: true}; const installed = settings.ready; ${AVATAR} const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const shown = (element as {props: {name: string}}).props.name; return shown;}`, errors: [{messageId: "excess", data: {fields: "email"}}], output: null},
    {name: "captured primitive provenance remains closed", filename: "probe.tsx", code: `${JSX}const name = 'Ada'; export function observe() {${AVATAR} const element = <Avatar {...{name, email: 'unused'}}/>; const shown = (element as {props: {name: string}}).props.name; return shown;}`, errors: [{messageId: "excess", data: {fields: "email"}}], output: null},
    {name: "captured nonescaping scalar data reuses the existing object proof", filename: "probe.tsx", code: `${JSX}const settings = {ready: true}; export function observe() {const installed = settings.ready; ${AVATAR} const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const shown = (element as {props: {name: string}}).props.name; return shown;}`, errors: [{messageId: "excess", data: {fields: "email"}}], output: null},
    { name: "a same-spelled data object's metadata is unrelated to the receiver", filename: "probe.tsx", code: `${SOURCE}const settings = {defaultProps: {email: 'fallback'}}; settings.defaultProps = {email: 'updated'}; const view = <Avatar {...{name: 'Ada', email: 'unused'}}/>;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    ...["name", "['name']"].map((field) => ({
      name: "a private element only exposes its proven consumed scalar: " + field,
      filename: "probe.tsx",
      code: `${SOURCE}const element = <Avatar {...{name: 'Ada', email: 'unused'}}/>; const shown = (element as {props: {name: string}}).props${field === "name" ? ".name" : field}; export {shown};`,
      errors: [{messageId: "excess" as const, data: {fields: "email"}}],
      output: null,
    })),
    ...[
      ["an erased type import has no runtime effect", "import type {Missing} from 'unavailable-type-only-module';"],
      ["an erased import of an effectful project module", "import type {EffectMarker} from './prototype-effects';"],
      ["an erased re-export of an effectful project module", "export type {EffectMarker} from './prototype-effects';"],
      ["a type-space Function reference has no runtime capability", "type Factory = Function;"],
    ].map(([boundary, setup]) => ({
      name: "ordinary Object runtime proof preserves a finding: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: 'Ada', email: 'a'}}/>;`,
      errors: [{messageId: "excess" as const, data: {fields: "email"}}],
      output: null,
    })),
    ...[
      "<span><span>{name}</span></span>",
      "<span>{name ? <span>{name}</span> : null}</span>",
      "<span>{name && <span>{name}</span>}</span>",
    ].map((body) => ({
      name: "JSX nodes remain supported in rendered positions: " + body,
      filename: "probe.tsx",
      code: `${JSX}const Box = ({name}: {name: string}) => ${body}; const view = <Box {...{name: 'Ada', email: 'unused'}}/>;`,
      errors: [{messageId: "excess" as const, data: {fields: "email"}}],
      output: null,
    })),
    ...[
      ["fixed own data properties", "const user = {name: 'Ada'};", "user.name"],
      ["readonly const assertion retains actual data", "const user = {name: 'Ada'} as const;", "user.name"],
      ["a scalar field alias retains its origin", "const user = {name: 'Ada'}; const name = user.name;", "name"],
      ["shorthand fields resolve their actual value binding", "const name = 'Ada'; const user = {name};", "user.name"],
      ["fixed literal element lookup", "const user = {name: 'Ada'};", "user['name']"],
    ].map(([boundary, setup, value]) => ({
      name: "read-only nonescaping literal source: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: ${value}, email: 'a'}} />;`,
      errors: [{messageId: "excess" as const, data: {fields: "email"}}],
      output: null,
    })),
    {name: "inline shorthand resolves the scalar binding", filename: "probe.tsx", code: `${SOURCE}const name = 'Ada'; const view = <Avatar {...{name, email: 'a'}}/>;`, errors: [{messageId: "excess", data: {fields: "email"}}], output: null},
    ...[
      ["literal const alias", "const value = 'Ada';", "value"],
      ["transitive literal const aliases", "const raw = 'Ada'; const value = raw;", "value"],
      ["assertions around a genuine primitive", "const value = 'Ada' as unknown as string;", "value"],
      ["a template evaluates proven primitive operands", "const value = 'Ada';", "`Hello ${value}`"],
      ["typeof reads a proven primitive", "const value = 'Ada';", "typeof value"],
      ["numeric operators evaluate proven primitive operands", "const value = 1;", "value + 'Ada'"],
      ["logical alternatives are proven primitives", "const value = 'Ada';", "value || 'Fallback'"],
      ["conditional tests and alternatives are proven primitives", "const enabled = true;", "enabled ? 'Ada' : 'Grace'"],
    ].map(([boundary, setup, value]) => ({
      name: "source primitive provenance retains a finding: " + boundary,
      filename: "probe.tsx",
      code: `${SOURCE}${setup} const view = <Avatar {...{name: ${value}, email: 'a'}} />;`,
      errors: [{messageId: "excess" as const, data: {fields: "email"}}],
      output: null,
    })),
    {name: "flat aliases and scalar template expressions remain a closed view", filename: "probe.tsx", code: `${JSX}const Box = ({name: label}: {name: string}) => <span>{` + "`Hello ${label}`" + `}</span>; const view = <Box {...{name: 'Ada', title: 'Details'}} />;`, errors: [{messageId: "excess", data: {fields: "title"}}], output: null},
    { name: "immutable receiver aliases preserve the inspected function", filename: "probe.tsx", code: `${JSX}const Original = (props: {className: string}) => <span>{props.className}</span>; const Box = Original; const view = <Box {...{className: 'card', title: 'Details'}} />;`, errors: [{messageId: "excess", data: {fields: "title"}}], output: null },
    { name: "implemented named props read only declared fields", filename: "probe.tsx", code: `${JSX}const Box = (props: {className: string}) => <span>{props.className}</span>; const view = <Box {...{className: 'card', title: 'Details'}} />;`, errors: [{messageId: "excess", data: {fields: "title"}}], output: null },
    { name: "reserved development metadata does not hide ordinary excess fields", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', __self: null, __source: {fileName: 'avatar.tsx'}, email: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "implicit capabilities do not hide unrelated fields when receiver reads scalar data", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', toString() {return 'shown';}, email: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "a literal method is an enumerable own field", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email() { return 'a'; }}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "a statically computed literal key is enumerable", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', ['email']: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { name: "hyphenated JSX keys are preserved without exempting ordinary keys", filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', 'api-key': 'a', api_key: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "api_key" } }], output: null },
    { name: "transitive structural inheritance preserves every declared field", filename: "probe.tsx", code: `${JSX}interface Base {readonly name: string} interface Props extends Base {email?: string} type Alias = Props; const Avatar = (props: Alias): JSX.Element => null!; const view = <Avatar {...{name: 'Ada', email: 'a', unrelated: true}} />;`, errors: [{ messageId: "excess", data: { fields: "unrelated" } }], output: null },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a'}} />;`, errors: [{ messageId: "excess", data: { fields: "email" } }], output: null },
    { filename: "probe.tsx", code: `${SOURCE}const view = <Avatar {...{name: 'Ada', email: 'a', id: 1}} />;`, errors: [{ messageId: "excess", data: { fields: "email, id" } }], output: null },
  ],
});

const IMPORTED_POLICY_TESTER = new RuleTester({languageOptions: {parser: tsParser}});
IMPORTED_POLICY_TESTER.run("no-excess-jsx-props imported contract under native unused-local policy", rule, {
  valid: [importedContractPolicyCase("unused-local errors keep imported runtime evidence unavailable", true)],
  invalid: [{...importedContractPolicyCase("import alias and re-export preserve transitive structural keys", false),
    errors: [{messageId: "excess", data: {fields: "accountId"}}], output: null}],
});

function importedContractPolicyCase(name: string, noUnusedLocals: boolean) {
  const filename = join(import.meta.dirname, "..", "fixtures", "minimal-consumer", "probe.tsx");
  const code = IMPORTED_CONTRACT_CASE;
  const options: ts.CompilerOptions = {strict: true, noUnusedLocals, noUnusedParameters: false, noEmit: true, types: [],
    target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, jsx: ts.JsxEmit.ReactJSX};
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, code, version, true) : original(path, version, onError, create);
  const program = ts.createProgram([filename], options, host);
  const source = program.getSourceFile(filename);
  if (!source) throw new Error("Imported JSX policy fixture was not loaded");
  expect(program.getOptionsDiagnostics()).toEqual([]);
  expect(program.getGlobalDiagnostics()).toEqual([]);
  expect(program.getSyntacticDiagnostics()).toEqual([]);
  expect(program.getSemanticDiagnostics(source).map((diagnostic) => diagnostic.code)).toEqual(noUnusedLocals ? [6133] : []);
  return {name, code, filename, languageOptions: {parserOptions: {programs: [program], projectService: false, ecmaFeatures: {jsx: true}}}};
}

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
