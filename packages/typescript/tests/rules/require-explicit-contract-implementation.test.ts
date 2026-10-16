import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/require-explicit-contract-implementation.js";

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

it("checks a fifth owned module that changes the runtime contract", async () => {
  for (const [customization, expectedCount] of [["", 1], ["Object.defineProperty(Publisher, Symbol.hasInstance, { value: () => true });", 0]] as const) {
    await verifyRuleExamples({ ...rule, documentation: { ...rule.documentation, examples: [{
      id: "owned-side-effect-origin", outcome: expectedCount === 0 ? "no-match" : "match", expectedCount,
      public: false, focusPath: "usage.ts", files: [
        { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void }" },
        { path: "consumer.ts", source: "import { Publisher } from './contract'; export class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } }" },
        { path: "implementation.ts", source: "export class Fake { publish(): void {} }" },
        { path: "customize.ts", source: `import { Publisher } from './contract'; ${customization}` },
        { path: "usage.ts", source: "import './customize'; import { Consumer } from './consumer'; import { Fake } from './implementation'; new Consumer(new Fake());" },
      ],
    }] } });
  }
});

it("a structural fake actually fails the nominal runtime guard", () => {
  abstract class Publisher { abstract publish(): void }
  class Consumer {
    constructor(readonly publisher: Publisher) {
      if (!(publisher instanceof Publisher)) throw new TypeError("Nominal publisher required");
    }
  }
  class FakePublisher { publish(): void {} }
  expect(() => new Consumer(new FakePublisher())).toThrow(TypeError);
});

it("tracks escaped owned namespaces while preserving qualified constructors", async () => {
  for (const [customization, expectedCount] of [["", 1], ["configure(contract);", 0], ["const alias = contract; configure(alias);", 0]] as const) {
    await verifyRuleExamples({ ...rule, documentation: { ...rule.documentation, examples: [{
      id: "owned-namespace-value", outcome: expectedCount === 0 ? "no-match" : "match", expectedCount,
      public: false, focusPath: "usage.ts", files: [
        { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void }" },
        { path: "consumer.ts", source: "import * as contract from './contract'; export class Consumer { constructor(readonly publisher: contract.Publisher) { if (!(publisher instanceof contract.Publisher)) throw new Error(); } }" },
        { path: "implementation.ts", source: "export class Fake { publish(): void {} }" },
        { path: "customize.ts", source: "export function configure(value: object): void { const constructor = Reflect.get(value, 'Publisher'); Object.defineProperty(constructor, Symbol.hasInstance, { value: () => true }); }" },
        { path: "usage.ts", source: `import * as contract from './contract'; import * as consumer from './consumer'; import * as implementation from './implementation'; import { configure } from './customize'; ${customization} new consumer.Consumer(new implementation.Fake());` },
      ],
    }] } });
  }
});

it("tracks literal element reads from an owned namespace", async () => {
  await verifyRuleExamples({ ...rule, documentation: { ...rule.documentation, examples: [{
    id: "owned-namespace-element", outcome: "no-match", expectedCount: 0,
    public: false, focusPath: "usage.ts", files: [
      { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void }" },
      { path: "consumer.ts", source: "import { Publisher } from './contract'; export class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } }" },
      { path: "implementation.ts", source: "export class Fake { publish(): void {} }" },
      { path: "customize.ts", source: "export function configure(value: object): void { Object.defineProperty(value, Symbol.hasInstance, { value: () => true }); }" },
      { path: "usage.ts", source: "import * as contract from './contract'; import { configure } from './customize'; import { Consumer } from './consumer'; import { Fake } from './implementation'; configure(contract['Publisher']); new Consumer(new Fake());" },
    ],
  }] } });
});

it("tracks an owned namespace passed implicitly as a method receiver", async () => {
  await verifyRuleExamples({ ...rule, documentation: { ...rule.documentation, examples: [{
    id: "owned-namespace-receiver", outcome: "no-match", expectedCount: 0,
    public: false, focusPath: "usage.ts", files: [
      { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void } export { configure as helper } from './customize';" },
      { path: "consumer.ts", source: "import { Publisher } from './contract'; export class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } }" },
      { path: "implementation.ts", source: "export class Fake { publish(): void {} }" },
      { path: "customize.ts", source: "export function configure(this: object): void { const constructor = Reflect.get(this, 'Publisher'); Object.defineProperty(constructor, Symbol.hasInstance, { value: () => true }); }" },
      { path: "usage.ts", source: "import * as contract from './contract'; import { Consumer } from './consumer'; import { Fake } from './implementation'; contract.helper(); new Consumer(new Fake());" },
    ],
  }] } });
});

it("excludes constructor escapes through static this", async () => {
  await verifyRuleExamples({ ...rule, documentation: { ...rule.documentation, examples: [{
    id: "static-constructor-escape", outcome: "no-match", expectedCount: 0,
    public: false, focusPath: "usage.ts", files: [
      { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void }" },
      { path: "consumer.ts", source: "import { Publisher } from './contract'; export class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } }" },
      { path: "implementation.ts", source: "import { configure } from './customize'; export class Fake { static { configure(this); } publish(): void {} }" },
      { path: "customize.ts", source: "import { Publisher } from './contract'; class Real extends Publisher { publish(): void {} } export function configure(value: { prototype: object }) { Object.setPrototypeOf(value.prototype, new Real()); }" },
      { path: "usage.ts", source: "import { Consumer } from './consumer'; import { Fake } from './implementation'; new Consumer(new Fake());" },
    ],
  }] } });
});

it("prototype changes make structural fakes pass the nominal runtime guard", () => {
  abstract class Publisher { abstract publish(): void }
  class Consumer {
    constructor(readonly publisher: Publisher) {
      if (!(publisher instanceof Publisher)) throw new TypeError("Nominal publisher required");
    }
  }
  class ConstructorFake {
    constructor() { Object.setPrototypeOf(this, Publisher.prototype); }
    publish(): void {}
  }
  class ModuleFake { publish(): void {} }
  Object.setPrototypeOf(ModuleFake.prototype, Publisher.prototype);
  expect(new Consumer(new ConstructorFake())).toBeInstanceOf(Consumer);
  expect(new Consumer(new ModuleFake())).toBeInstanceOf(Consumer);
});

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

TESTER.run("require-explicit-contract-implementation", rule, {
  valid: [
    { name: "keeps nominal inheritance with parenthesized constructors", code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class Fake extends Publisher { publish() {} } new (Consumer)(new (Fake)());" },
    { name: "keeps explicit casts outside direct collaborator construction", code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new (Consumer)(new (Fake)() as Publisher);" },
    { name: "keeps constructor escapes through parentheses opaque", code: "declare function configure(value: object): void; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } configure((Publisher)); new (Consumer)(new (Fake)());" },
    "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (publisher instanceof Publisher) publisher.publish(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) return; } } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake extends Publisher { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void; static [Symbol.hasInstance](value: unknown) { return true; } } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { publisher = new Real(); if (!(publisher instanceof Publisher)) throw new Error(); } } class Real extends Publisher { publish() {} } class Fake { publish() {} } new Consumer(new Fake());",
    "declare function decorate(...args: unknown[]): void; @decorate abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "declare function decorate(...args: unknown[]): void; @decorate class Base {} abstract class Publisher extends Base { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "declare function createBase(): new () => object; abstract class Publisher extends createBase() { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "declare const Base: new () => object; abstract class Publisher extends Base { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "declare function decorate(...args: unknown[]): void; abstract class Publisher { abstract publish(): void } @decorate class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } const Wrapped = new Proxy(Consumer, {}); class Fake { publish() {} } new Wrapped(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { constructor() { Object.setPrototypeOf(this, Publisher.prototype); } publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { initialize = Object.setPrototypeOf(this, Publisher.prototype); publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } Object.setPrototypeOf(Fake.prototype, Publisher.prototype); new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } Reflect.setPrototypeOf(Fake.prototype, Publisher.prototype); new Consumer(new Fake());",
    "declare function configure(value: object): void; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } configure(Publisher); new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } const alias = Publisher; Object.defineProperty(alias, Symbol.hasInstance, { value: () => true }); new Consumer(new Fake());",
    "declare function configure(value: object): void; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } configure(Fake); new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } const setPrototype = Object.setPrototypeOf; setPrototype(Fake.prototype, Publisher.prototype); new Consumer(new Fake());",
    "declare function initialize(value: object): void; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { constructor() { initialize(this); } publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } class Real extends Publisher { publish() {} } function build(): Fake { return new Real(); } new Consumer(build());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } class Real extends Publisher { publish() {} } const Wrapped = new Proxy(Fake, { construct() { return new Real(); } }); new Consumer(new Wrapped());",
  ],
  invalid: [
    { name: "retains the exact parenthesized consumer constructor", code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new (Consumer)(new Fake());", errors: [{ messageId: "declareActualContract" }] },
    { name: "retains the exact parenthesized collaborator constructor", code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new (Fake)());", errors: [{ messageId: "declareActualContract" }] },
    { name: "retains all parenthesized constructors in the recorded attack", code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new (TypeError)('Nominal publisher required'); } } class FakePublisher { publish() {} } new (Consumer)(new (FakePublisher)());", errors: [{ messageId: "declareActualContract" }] },
    {
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake implements Publisher { publish() {} } new Consumer(new Fake());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) { throw new Error(); } } } class Fake { publish() {} } new Consumer(new Fake());",
      errors: [{ messageId: "declareActualContract" }],
    },
  ],
});
