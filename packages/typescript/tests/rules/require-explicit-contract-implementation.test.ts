// vitest: shared-module-graph
import { RuleTester } from "oxlint/plugins-dev";
import { describe, expect, it } from "vitest";
import rule from "../../src/rules/require-explicit-contract-implementation.js";
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

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});

TESTER.run("require-explicit-contract-implementation", rule, {
  valid: [
    "class Base { private token: number; } abstract class Publisher extends Base { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",

    "abstract class Publisher { private token: number; abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract get status(): string; abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",

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
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } const setPrototype = Object.setPrototypeOf; setPrototype(Fake.prototype, Publisher.prototype); new Consumer(new Fake());",
    "declare function initialize(value: object): void; abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { constructor() { initialize(this); } publish() {} } new Consumer(new Fake());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } class Real extends Publisher { publish() {} } function build(): Fake { return new Real(); } new Consumer(build());",
    "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } class Real extends Publisher { publish() {} } const Wrapped = new Proxy(Fake, { construct() { return new Real(); } }); new Consumer(new Wrapped());",
  ],
  invalid: [
    {
      code: "abstract class Publisher { abstract publish(): void } type Contract = Publisher; class Consumer { constructor(readonly publisher: Contract) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
      errors: [{ messageId: "declareActualContract" }],
    },
    {
      code: "abstract class Publisher { abstract publish(): void } type Contract<T> = T; class Consumer { constructor(readonly publisher: Contract<Publisher>) { if (!(publisher instanceof Publisher)) throw new Error(); } } class Fake { publish() {} } new Consumer(new Fake());",
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
});
