import { join } from "node:path";

import { FIXTURES, RuleTester, ruleTester, typed } from "./_tester.js";

const TESTER = ruleTester({ cwd: join(FIXTURES, "minimal-consumer") });

export const CONSUMER_PREFIX = 'export {}; const account = {name: "Ada", email: "a"};';
export const INLINE_CONTRACT = "{readonly name: string; readonly email: string}";
export const UNION_DECLARATIONS = "interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string}";

export function runPrivateConsumerBoundaries(name: string, tested: Parameters<RuleTester["run"]>[1], contract: string, setup = ""): void {
  TESTER.run(name + " private boundaries", tested, typed({valid: privateConsumerBoundaries(contract, setup), invalid: []}));
}

function privateConsumerBoundaries(contract: string, setup: string): { name: string; filename: string; code: string }[] {
  const declaration = `function label(p: ${contract}): string {return p.name;}`;
  const cases = [
    ["public declaration", `export ${declaration} label(account);`],
    ["type-only exported callable", `${declaration} export type {label}; label(account);`],
    ["typeof callable retains signature information", `${declaration} type Signature = typeof label; label(account);`],
    ["callback escapes", `${declaration} [account].map(label);`],
    ["stored alias escapes", `${declaration} const alias = label; alias(account);`],
    ["fresh object can change excess-property acceptance", `${declaration} label({name: 'Ada', email: 'a'});`],
    ["reassigned callable", `${declaration} label = p => p.email; label(account);`],
    ["direct eval bypasses ordinary references", `${declaration} eval('label(account)'); label(account);`],
    ...["(eval as typeof eval)", "eval!", "(eval satisfies typeof eval)", "((eval as <T>(source: string) => any)<string>)"].map((callee) => ["erased wrappers retain lexical eval: " + callee, `${declaration} ${callee}('globalThis.leaked = label'); label(account);`]),
    ["whole-object helper", `declare function helper(value: unknown): string; function label(p: ${contract}): string {return helper(p);} label(account);`],
    ["identity is observed", `function label(p: ${contract}): string {return p === account ? p.name : '';} label(account);`],
    ["field mutation", `function label(p: ${contract}): string {return p.name = 'updated';} label(account);`],
    ["dynamic key", `declare const key: 'name'; function label(p: ${contract}): string {return p[key];} label(account);`],
    ["in narrowing", `function label(p: ${contract}): string {return 'email' in p ? p.email : p.name;} label(account);`],
    ["captured closure", `function label(p: ${contract}): string {return (() => p.name)();} label(account);`],
    ["rest forwarding", `function label({...p}: ${contract}): string {return p.name;} label(account);`],
    ["defaulted binding", `function label({name = ''}: ${contract}): string {return name;} label(account);`],
    ["predicate return is a refinement contract", `function label(p: ${contract}): p is ${contract} {return !!p.name;} label(account);`],
    ["inferred return can expose narrowing", `function label(p: ${contract}) {return p.name;} label(account);`],
    ["contextual arrow signature", `const label: (p: ${contract}) => string = (p: ${contract}): string => p.name; label(account);`],
    ["overloaded declaration", `function label(p: ${contract}): string; ${declaration} label(account);`],
    ["generic signature", `function label<T>(p: ${contract}): string {return p.name;} label(account);`],
    ["invalid independent return", `function label(p: ${contract}): number {return p.name;} label(account);`],
    ["multiple arguments", `${declaration} label(account, account);`],
    ["nested callable is outside the module-private proof", `function outer(): string {${declaration} return label(account);} outer();`],
    ["generated source", `// @generated\n${declaration} label(account);`],
    ["JSX even inside a template needs runtime proof", `declare namespace JSX {interface Element {} interface IntrinsicElements {span: {}}} function label(p: ${contract}): string {return \`\${<span/>}\${p.name}\`;} label(account);`],
  ];
  return cases.map(([name, code]) => ({name: name ?? "boundary", filename: "probe.tsx", code: name === "generated source" ? `// @generated\n${CONSUMER_PREFIX}${setup}${code}` : `${CONSUMER_PREFIX}${setup}${code}`}));
}
