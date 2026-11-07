import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { afterAll, expect, it } from "vitest";

import rule from "../../src/rules/require-explicit-contract-implementation.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

it("a structural fake actually fails the nominal runtime guard", () => {
  abstract class Publisher {
    abstract publish(): void;
  }
  class Consumer {
    constructor(readonly publisher: Publisher) {
      if (!(publisher instanceof Publisher))
        throw new TypeError("Nominal publisher required");
    }
  }
  class FakePublisher {
    publish(): void {}
  }
  expect(() => new Consumer(new FakePublisher())).toThrow(TypeError);
});

it("prototype changes make structural fakes pass the nominal runtime guard", () => {
  abstract class Publisher {
    abstract publish(): void;
  }
  class Consumer {
    constructor(readonly publisher: Publisher) {
      if (!(publisher instanceof Publisher))
        throw new TypeError("Nominal publisher required");
    }
  }
  class ConstructorFake {
    constructor() {
      Object.setPrototypeOf(this, Publisher.prototype);
    }
    publish(): void {}
  }
  class ModuleFake {
    publish(): void {}
  }
  Object.setPrototypeOf(ModuleFake.prototype, Publisher.prototype);
  expect(new Consumer(new ConstructorFake())).toBeInstanceOf(Consumer);
  expect(new Consumer(new ModuleFake())).toBeInstanceOf(Consumer);
});

const TESTER = ruleTester({ cwd: FIXTURES });

TESTER.run("require-explicit-contract-implementation", rule, typed({
  valid: [
    {
      name: "keeps nominal inheritance with parenthesized constructors",
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class Fake extends Publisher { publish() {} } new (Consumer)(new (Fake)());",
    },
    {
      name: "keeps explicit casts outside direct collaborator construction",
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new (Consumer)(new (Fake)() as Publisher);",
    },
    {
      name: "keeps constructor escapes through parentheses opaque",
      code: "declare function configure(value: object): void; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } configure((Publisher)); new (Consumer)(new (Fake)());",
    },
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
    {
      name: "inherits the already authored inert nominal contract",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output:
        "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "preserves existing raw names and CRLF",
      code: "export {}; abstract class Dispatcher { abstract dispatch(): void }\r\nclass Consumer { constructor(readonly dispatcher: Dispatcher) { if (!(dispatcher instanceof Dispatcher)) throw new TypeError('Nominal dispatcher required'); } }\r\nclass FakeDispatcher { dispatch() {} } new Consumer(new FakeDispatcher());",
      output:
        "export {}; abstract class Dispatcher { abstract dispatch(): void }\r\nclass Consumer { constructor(readonly dispatcher: Dispatcher) { if (!(dispatcher instanceof Dispatcher)) throw new TypeError('Nominal dispatcher required'); } }\r\nclass FakeDispatcher extends Dispatcher { dispatch() {} } new Consumer(new FakeDispatcher());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "preserves the exact rejecting guard block",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) { throw new TypeError('Nominal publisher required'); } } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output:
        "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) { throw new TypeError('Nominal publisher required'); } } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains scripts without an authored module boundary",
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains base constructor ownership",
      code: "export {}; abstract class Publisher { constructor() {} abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains other consumer behavior",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { other(): void {} constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains extra module declarations",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher()); function observe(): void {}",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains non-retained constructor contracts",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains other exception policies",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new RangeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains comments and directives",
      code: "/* nominal contract */ export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains nonempty implementation bodies",
      code: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() { return; } } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains exported runtime authorities",
      code: "export {}; export abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());",
      output: null,
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains the exact parenthesized consumer constructor",
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new (Consumer)(new Fake());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains the exact parenthesized collaborator constructor",
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new (Fake)());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      name: "retains all parenthesized constructors in the recorded attack",
      code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new (TypeError)('Nominal publisher required'); } } class FakePublisher { publish() {} } new (Consumer)(new (FakePublisher)());",
      errors: [{ messageId: "declareActualContract" }],
    },
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
}));

TESTER.run("require-explicit-contract-implementation without type information", rule, {
  valid: [{
    code: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    settings: { sarj: { typeAware: false } },
  }],
  invalid: [],
});

interface ExampleFile { readonly path: string; readonly source: string }
interface Example {
  readonly id: string;
  readonly files: readonly ExampleFile[];
  readonly focusPath: string;
  readonly expectedCount: number;
  readonly fixed?: string;
}
const EXAMPLE_ROOT = mkdtempSync(join(tmpdir(), "require-explicit-contract-implementation-"));
afterAll(() => rmSync(EXAMPLE_ROOT, { recursive: true, force: true }));
function exampleCase(example: Example) {
  const root = join(EXAMPLE_ROOT, example.id);
  for (const file of example.files) {
    mkdirSync(dirname(join(root, file.path)), { recursive: true });
    writeFileSync(join(root, file.path), file.source);
  }
  writeFileSync(join(root, "tsconfig.json"), JSON.stringify({ compilerOptions: {
    target: "ESNext", module: "ESNext", moduleResolution: "Bundler", strict: true, allowJs: true, jsx: "preserve", noEmit: true,
  }, include: ["**/*"] }));
  const focus = example.files.find((file) => file.path === example.focusPath)!;
  const base = { name: example.id, code: focus.source, filename: join(root, focus.path), cwd: root, settings: { sarj: { typeAware: true } } };
  return example.expectedCount === 0 ? base : {
    ...base,
    output: example.fixed ?? null,
    errors: Array.from({ length: example.expectedCount }, () => ({ messageId: "declareActualContract" as const })),
  };
}
const CONTRACT = { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void }" };
const CONSUMER = { path: "consumer.ts", source: "import { Publisher } from './contract'; export class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } }" };
const IMPLEMENTATION = { path: "implementation.ts", source: "export class Fake { publish(): void {} }" };
const NAMESPACE_CUSTOMIZE = { path: "customize.ts", source: "export function configure(value: object): void { const constructor = Reflect.get(value, 'Publisher'); Object.defineProperty(constructor, Symbol.hasInstance, { value: () => true }); }" };
const EXAMPLES: Example[] = [
  {
    id: "runtime-nominal-guard-with-structural-fake", focusPath: "src/service.ts", expectedCount: 1,
    files: [{ path: "src/service.ts", source: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());" }],
  },
  {
    id: "runtime-nominal-guard-with-inherited-fake", focusPath: "src/service.ts", expectedCount: 0,
    files: [{ path: "src/service.ts", source: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());" }],
  },
  {
    id: "safe-autofix", focusPath: "src/service.ts", expectedCount: 1,
    files: [{ path: "src/service.ts", source: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());" }],
    fixed: "export {}; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());",
  },
  ...([["", 1], ["Object.defineProperty(Publisher, Symbol.hasInstance, { value: () => true });", 0]] as const).map(([customization, expectedCount], i): Example => ({
    id: `owned-side-effect-origin-${i}`, focusPath: "usage.ts", expectedCount,
    files: [CONTRACT, CONSUMER, IMPLEMENTATION,
      { path: "customize.ts", source: `import { Publisher } from './contract'; ${customization}` },
      { path: "usage.ts", source: "import './customize'; import { Consumer } from './consumer'; import { Fake } from './implementation'; new Consumer(new Fake());" }],
  })),
  ...([["", 1], ["configure(contract);", 0], ["const alias = contract; configure(alias);", 0]] as const).map(([customization, expectedCount], i): Example => ({
    id: `owned-namespace-value-${i}`, focusPath: "usage.ts", expectedCount,
    files: [CONTRACT,
      { path: "consumer.ts", source: "import * as contract from './contract'; export class Consumer { constructor(readonly publisher: contract.Publisher) { if (!(publisher instanceof contract.Publisher)) throw new Error(); } }" },
      IMPLEMENTATION, NAMESPACE_CUSTOMIZE,
      { path: "usage.ts", source: `import * as contract from './contract'; import * as consumer from './consumer'; import * as implementation from './implementation'; import { configure } from './customize'; ${customization} new consumer.Consumer(new implementation.Fake());` }],
  })),
  {
    id: "owned-namespace-element", focusPath: "usage.ts", expectedCount: 0,
    files: [CONTRACT, CONSUMER, IMPLEMENTATION,
      { path: "customize.ts", source: "export function configure(value: object): void { Object.defineProperty(value, Symbol.hasInstance, { value: () => true }); }" },
      { path: "usage.ts", source: "import * as contract from './contract'; import { configure } from './customize'; import { Consumer } from './consumer'; import { Fake } from './implementation'; configure(contract['Publisher']); new Consumer(new Fake());" }],
  },
  {
    id: "owned-namespace-receiver", focusPath: "usage.ts", expectedCount: 0,
    files: [
      { path: "contract.ts", source: "export abstract class Publisher { abstract publish(): void } export { configure as helper } from './customize';" },
      CONSUMER, IMPLEMENTATION,
      { path: "customize.ts", source: "export function configure(this: object): void { const constructor = Reflect.get(this, 'Publisher'); Object.defineProperty(constructor, Symbol.hasInstance, { value: () => true }); }" },
      { path: "usage.ts", source: "import * as contract from './contract'; import { Consumer } from './consumer'; import { Fake } from './implementation'; contract.helper(); new Consumer(new Fake());" }],
  },
  {
    id: "static-constructor-escape", focusPath: "usage.ts", expectedCount: 0,
    files: [CONTRACT, CONSUMER,
      { path: "implementation.ts", source: "import { configure } from './customize'; export class Fake { static { configure(this); } publish(): void {} }" },
      { path: "customize.ts", source: "import { Publisher } from './contract'; class Real extends Publisher { publish(): void {} } export function configure(value: { prototype: object }) { Object.setPrototypeOf(value.prototype, new Real()); }" },
      { path: "usage.ts", source: "import { Consumer } from './consumer'; import { Fake } from './implementation'; new Consumer(new Fake());" }],
  },
];
const EXAMPLE_CASES = EXAMPLES.map(exampleCase);
TESTER.run("require-explicit-contract-implementation examples", rule, {
  valid: EXAMPLE_CASES.filter((testCase) => !("errors" in testCase)),
  invalid: EXAMPLE_CASES.filter<Extract<(typeof EXAMPLE_CASES)[number], { errors: unknown }>>((testCase) => "errors" in testCase),
});
