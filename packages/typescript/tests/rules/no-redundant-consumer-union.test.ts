import rule from "../../src/rules/no-redundant-consumer-union.js";
import { CONSUMER_PREFIX, PRIVATE_CONSUMER_TESTER, UNION_DECLARATIONS, runPrivateConsumerBoundaries } from "../private-consumer-cases.js";

const PREFIX = `${CONSUMER_PREFIX}${UNION_DECLARATIONS}`;
const NULLABLE_PREFIX = `${CONSUMER_PREFIX}interface Animal {readonly name: string | null} interface Dog extends Animal {readonly email: string}`;
runPrivateConsumerBoundaries("no-redundant-consumer-union", rule, "Dog | Animal", UNION_DECLARATIONS);
PRIVATE_CONSUMER_TESTER.run("no-redundant-consumer-union property declaration origins", rule, {
  valid: [
    ...[
      ["conflicting nullable merge", "interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string | null} interface Dog {readonly email: number | null}"],
      ["compatible repeated merge", "interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string | null} interface Dog {readonly email: string | null}"],
      ["incompatible own override", "interface Animal {readonly name: string} interface Base extends Animal {readonly email: string | null} interface Dog extends Base {readonly email: number | null}"],
      ["recovered dual-base field is assignable to both bases", "interface Animal {readonly name: string} interface First extends Animal {readonly email: string} interface Second extends Animal {readonly email: string | null} interface Dog extends First, Second {}"],
      ["valid narrower own override", "interface Animal {readonly name: string | null} interface Dog extends Animal {readonly name: string; readonly email: string}"],
      ["compatible independent bases", "interface Animal {readonly name: string} interface First extends Animal {readonly email: string} interface Second extends Animal {readonly email: string} interface Dog extends First, Second {}"],
      ["legal overlapping intersection", "interface Animal {readonly name: string} type Dog = Animal & {readonly email: string | null} & {readonly email: string};"],
      ["legal never intersection", "interface Animal {readonly name: string} type Dog = Animal & {readonly email: string} & {readonly email: number};"],
    ].map(([name, declarations]) => ({name, filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}${declarations} export type KeptDog = Dog; declare const input: Dog; function label(p: Dog | Animal): string {return p.name ?? '';} label(input);`})),
  ],
  invalid: [
    ...[
      ["shared-base diamond", "interface Animal {readonly name: string | null} interface Left extends Animal {readonly email: string} interface Right extends Animal {} interface Dog extends Left, Right {}"],
      ["disjoint merged fragments", "interface Animal {readonly name: string | null} interface Dog extends Animal {} interface Dog {readonly email: string}"],
      ["disjoint intersection fields", "interface Animal {readonly name: string | null} type Dog = Animal & {readonly email: string};"],
    ].map(([name, declarations]) => {
      const code = `${CONSUMER_PREFIX}${declarations} export type KeptDog = Dog; function label(p: Dog | Animal): string {return p.name ?? '';} label(account);`;
      return {name, filename: "probe.tsx", code, output: code.replace("Dog | Animal", "Animal"), errors: [{messageId: "redundant" as const}]};
    }),
  ],
});
PRIVATE_CONSUMER_TESTER.run("no-redundant-consumer-union", rule, {
  valid: [
    ...["", "declare global {interface Object {readonly __optionalToken: any}}"].map((augmentation) => ({
      name: "an optional covering key can reject a valid existing identifier: " + (augmentation ? "implicit Any" : "ordinary"),
      filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}${augmentation} interface Source {readonly name: string; readonly email: string} interface Covering {readonly name: string; readonly __optionalToken?: string} const value = {name: 'Ada', email: 'a', __optionalToken: 123}; function label(p: Source | Covering): string {return p.name;} label(value);`,
    })),
    ...[
      ["type-level Extract is observable", "type Values = Extract<Dog | Animal, Dog>;"],
      ["producer retains alternatives", "const produce = (): Dog | Animal => account;"],
      ["disjoint required fields", "interface Other {readonly name: string; readonly age: number} function label(p: Dog | Other): string {return p.name;} label(account);"],
      ["identity duplicates owned upstream", "function label(p: Animal | Animal): string {return p.name;} label(account);"],
      ["mutually assignable nonidentical contracts remain unsupported", "interface Other {readonly name: string} function label(p: Animal | Other): string {return p.name;} label(account);"],
      ["Any cannot witness coverage", "interface Loose {readonly name: string; readonly email: any} function label(p: Loose | Animal): string {return p.name;} label(account);"],
      ["unknown field", "interface Loose {readonly name: string; readonly email: unknown} function label(p: Loose | Animal): string {return p.name;} label(account);"],
      ["callback variance", "interface Callback extends Animal {readonly callback: (value: Dog) => void} function label(p: Callback | Animal): string {return p.name;} label(account);"],
      ["class identity", "class Account {readonly name = ''; readonly email = ''} function label(p: Account | Animal): string {return p.name;} label(account);"],
      ["literal discriminant", "interface Tagged extends Animal {readonly kind: 'account'} function label(p: Tagged | Animal): string {return p.name;} label(account);"],
      ["index signature", "interface Open {readonly name: string; readonly [key: string]: string} function label(p: Open | Animal): string {return p.name;} label(account);"],
      ["generic declaration", "interface Generic<T> extends Animal {readonly payload: T} function label(p: Generic<string> | Animal): string {return p.name;} label(account);"],
      ["missing imported base", "import type {Missing} from 'unavailable'; interface Broken extends Missing {readonly name: string; readonly email: string} function label(p: Broken | Animal): string {return p.name;} label(account);"],
      ["Object Any is not an explicit required property", "declare global {interface Object {readonly token: any}} interface Covered {readonly name: string; readonly email: string} interface Covering {readonly name: string; readonly token: string} function label(p: Covered | Covering): string {return p.name;} label(account);"],
      ["all-optional covering can be weak", "interface Weak {readonly name?: string} interface Strong {readonly name?: string; readonly email: string} const emailOnly = {email: 'a'}; function label(p: Strong | Weak): string {return p.name ?? '';} label(emailOnly);"],
      ["methods may observe other fields", "interface Methods extends Animal {run(): string} function label(p: Methods | Animal): string {return p.name;} label(account);"],
      ["recursive field has no flat scalar proof", "interface Recursive extends Animal {readonly child: Recursive} function label(p: Recursive | Animal): string {return p.name;} label(account);"],
    ].map(([name, code]) => ({name, filename: "probe.tsx", code: `${PREFIX}${code}`})),
  ],
  invalid: [
    ...["Dog | Animal", "Animal | Dog"].map((contract) => ({name: "preserve covering Animal: " + contract, filename: "probe.tsx", code: `${PREFIX}function label(p: ${contract}): string {return p.name;} label(account);`, output: null, errors: [{messageId: "redundant" as const, data: {covered: "Dog", covering: "Animal"}}]})),
    {name: "destructured inherited field", filename: "probe.tsx", code: `${PREFIX}const label = ({name: displayName}: Dog | Animal): string => displayName; label(account);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "imports aliases and re-exports preserve native identity", filename: "probe.tsx", code: `${CONSUMER_PREFIX}import type {ConsumerAlias, ConsumerName} from './consumer-index'; function label(p: ConsumerAlias | ConsumerName): string {return p.name;} label(account);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "boolean and optional readonly fields", filename: "probe.tsx", code: `${CONSUMER_PREFIX}interface Base {readonly name: string; readonly enabled: boolean; readonly note?: string} interface Child extends Base {readonly email: string} const value = {name: 'Ada', enabled: true, email: 'a'}; function label(p: Child | Base): string {return p.enabled ? p.name + (p.note ?? '') : '';} label(value);`, output: null, errors: [{messageId: "redundant"}]},
  ],
});

PRIVATE_CONSUMER_TESTER.run("no-redundant-consumer-union nullable readonly fields", rule, {
  valid: [
    ...["Nullable", "'a' | null", "any | null", "unknown | null", "string | null | undefined", "(string) | null", "(string | null)"].map((type) => ({
      name: "unsupported nullable declaration domain " + type, filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}export type Nullable = string | null; interface Animal {readonly name: string} interface Dog extends Animal {readonly email: ${type}} function label(p: Dog | Animal): string {return p.name;} label(account);`,
    })),
    ...[
      ["mutable nullable declaration", "interface Animal {readonly name: string} interface Dog extends Animal {email: string | null} function label(p: Dog | Animal): string {return p.name;} label(account);"],
      ["mutually assignable nullable contracts", "interface Animal {readonly name: string | null} interface Dog {readonly name: string | null} function label(p: Dog | Animal): string {return p.name ?? '';} label(account);"],
      ["incompatible nullable fields", "interface Animal {readonly name: string; readonly email: number | null} interface Dog {readonly name: string; readonly email: string | null} function label(p: Dog | Animal): string {return p.name;} label(account);"],
      ["optional covering key can reject a valid original caller", "interface Source {readonly name: string; readonly email: string | null} interface Covering {readonly name: string; readonly note?: string | null} const input = {name: 'Ada', email: null, note: 42}; function label(p: Source | Covering): string {return p.name;} label(input);"],
      ["all-optional nullable reads lack a required read", "interface Animal {readonly name?: string | null} interface Dog extends Animal {readonly email: string} const input = {email: 'a'}; function label(p: Dog | Animal): string {return p.name ?? '';} label(input);"],
      ["nullable return annotations stay unsupported", "interface Animal {readonly name: string | null} interface Dog extends Animal {readonly email: string} function label(p: Dog | Animal): string | null {return p.name;} label(account);"],
    ].map(([name, code]) => ({name, filename: "probe.tsx", code: `${CONSUMER_PREFIX}${code}`})),
  ],
  invalid: [
    ...([
      ["string", "null", "''"],
      ["string", "undefined", "''"],
      ["number", "null", "0"],
      ["number", "undefined", "0"],
      ["boolean", "null", "false"],
      ["boolean", "undefined", "false"],
      ["bigint", "null", "0n"],
      ["bigint", "undefined", "0n"],
    ] as const).map(([keyword, nullish, fallback]) => {
      const code = `export {}; interface Covering {readonly value: ${keyword} | ${nullish}} interface Covered extends Covering {readonly extra: string} export type KeptCovered = Covered; const input: Covered = {value: ${nullish}, extra: 'a'}; function label(p: Covered | Covering): ${keyword} {return p.value ?? ${fallback};} label(input);`;
      return {name: "required nullable read " + keyword + " | " + nullish, filename: "probe.tsx", code,
        output: code.replace("Covered | Covering", "Covering"), errors: [{messageId: "redundant" as const, data: {covered: "Covered", covering: "Covering"}}]};
    }),
    ...["Dog | Animal", "Animal | Dog"].map((contract) => ({
      name: "retain nullable covering contract " + contract, filename: "probe.tsx",
      code: `${NULLABLE_PREFIX}export type KeptDog = Dog; function label(p: ${contract}): string {return p.name ?? '';} label(account);`,
      output: `${NULLABLE_PREFIX}export type KeptDog = Dog; function label(p: Animal): string {return p.name ?? '';} label(account);`,
      errors: [{messageId: "redundant" as const, data: {covered: "Dog", covering: "Animal"}}],
    })),
    {name: "nullable field only on the covered contract", filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string | null} export type KeptDog = Dog; function label(p: Dog | Animal): string {return p.name;} label(account);`,
      output: `${CONSUMER_PREFIX}interface Animal {readonly name: string} interface Dog extends Animal {readonly email: string | null} export type KeptDog = Dog; function label(p: Animal): string {return p.name;} label(account);`, errors: [{messageId: "redundant"}]},
    {name: "retain optional nullable field alongside a required read", filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}interface Animal {readonly name: string; readonly note?: string | null} interface Dog extends Animal {readonly email: string} export type KeptDog = Dog; function label(p: Dog | Animal): string {return p.name + (p.note ?? '');} label(account);`,
      output: `${CONSUMER_PREFIX}interface Animal {readonly name: string; readonly note?: string | null} interface Dog extends Animal {readonly email: string} export type KeptDog = Dog; function label(p: Animal): string {return p.name + (p.note ?? '');} label(account);`, errors: [{messageId: "redundant"}]},
    {name: "native nullable value widening proves proper coverage with the same keys", filename: "probe.tsx",
      code: "export {}; interface Narrow {readonly name: string} interface Broad {readonly name: string | null} export type KeptNarrow = Narrow; const input: Narrow = {name: 'Ada'}; function label(p: Narrow | Broad): string {return p.name ?? '';} label(input);",
      output: "export {}; interface Narrow {readonly name: string} interface Broad {readonly name: string | null} export type KeptNarrow = Narrow; const input: Narrow = {name: 'Ada'}; function label(p: Broad): string {return p.name ?? '';} label(input);", errors: [{messageId: "redundant", data: {covered: "Narrow", covering: "Broad"}}]},
    {name: "nullable annotation comments retain a manual finding", filename: "probe.tsx",
      code: `${NULLABLE_PREFIX}export type KeptDog = Dog; function label(p: Dog /* reviewed domain */ | Animal): string {return p.name ?? '';} label(account);`,
      output: null, errors: [{messageId: "redundant"}]},
  ],
});

PRIVATE_CONSUMER_TESTER.run("no-redundant-consumer-union safe source edits", rule, {
  valid: [],
  invalid: [
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({
      name: "exported type anchor retains raw covering name and terminators " + JSON.stringify(ending), filename: "probe.tsx",
      code: `${PREFIX}export type KeptDog = Dog; const compass = '🧭'; const typedAccount: Dog = account; function label(p: Dog${ending}| Animal): string {return p.name;} label(typedAccount);`,
      output: `${PREFIX}export type KeptDog = Dog; const compass = '🧭'; const typedAccount: Dog = account; function label(p: ${ending}Animal): string {return p.name;} label(typedAccount);`,
      errors: [{messageId: "redundant" as const}],
    })),
    ...["Dog\r|\nAnimal", "Dog|\nAnimal", "Animal\r|Dog"].map((contract, index) => ({
      name: "exported type anchor still refuses mixed terminator merges " + index, filename: "probe.tsx",
      code: `${PREFIX}export type KeptDog = Dog; function label(p:${index === 1 ? "\r" : " "}${contract}${index === 2 ? "\n" : ""}): string {return p.name;} label(account);`,
      output: null, errors: [{messageId: "redundant" as const}],
    })),
    {name: "a direct exported type read keeps the covered contract", filename: "probe.tsx",
      code: `${PREFIX}export type { Dog }; function label(p: Dog | Animal): string {return p.name;} label(account);`,
      output: `${PREFIX}export type { Dog }; function label(p: Animal): string {return p.name;} label(account);`, errors: [{messageId: "redundant"}]},
    {name: "an exported alias keeps an imported contract", filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}import type {ConsumerAlias as Domain, ConsumerName} from './consumer-index'; export type KeptDomain = Domain; function label(p: Domain | ConsumerName): string {return p.name;} label(account);`,
      output: `${CONSUMER_PREFIX}import type {ConsumerAlias as Domain, ConsumerName} from './consumer-index'; export type KeptDomain = Domain; function label(p: ConsumerName): string {return p.name;} label(account);`, errors: [{messageId: "redundant"}]},
    {name: "an exported qualified type keeps its namespace import", filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}import type * as Models from './consumer-index'; export type KeptModels = Models.ConsumerAlias; function label(p: Models.ConsumerAlias | Models.ConsumerName): string {return p.name;} label(account);`,
      output: `${CONSUMER_PREFIX}import type * as Models from './consumer-index'; export type KeptModels = Models.ConsumerAlias; function label(p: Models.ConsumerName): string {return p.name;} label(account);`, errors: [{messageId: "redundant"}]},
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({
      name: "retain raw covering name and all line terminators " + JSON.stringify(ending), filename: "probe.tsx",
      code: `${PREFIX}const compass = '🧭'; const typedAccount: Dog = account; function label(p: Dog${ending}| Animal): string {return p.name;} label(typedAccount);`,
      output: null,
      errors: [{messageId: "redundant" as const}],
    })),
    ...["Dog\r|\nAnimal", "Dog|\nAnimal", "Animal\r|Dog"].map((contract, index) => ({
      name: "mixed CR token LF merges stay manual at boundary " + index, filename: "probe.tsx",
      code: `${PREFIX}const typedAccount: Dog = account; function label(p:${index === 1 ? "\r" : " "}${contract}${index === 2 ? "\n" : ""}): string {return p.name;} label(typedAccount);`,
      output: null, errors: [{messageId: "redundant" as const}],
    })),
    {name: "independent producer annotation retains the covered binding", filename: "probe.tsx", code: `${PREFIX}const typedAccount: Dog = account; function label(p: Dog | Animal): string {return p.name;} label(typedAccount);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "two sole covered uses are not independent retained references", filename: "probe.tsx", code: `${PREFIX}function first(p: Dog | Animal): string {return p.name;} function second(p: Dog | Animal): string {return p.name;} first(account); second(account);`, output: null, errors: [{messageId: "redundant"}, {messageId: "redundant"}]},
    {name: "aliased imported type retains its producer use", filename: "probe.tsx", code: `${CONSUMER_PREFIX}import type {ConsumerAlias as Domain, ConsumerName} from './consumer-index'; const typedAccount: Domain = account; function label(p: Domain | ConsumerName): string {return p.name;} label(typedAccount);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "a qualified namespace binding remains in the exact covering node", filename: "probe.tsx", code: `${CONSUMER_PREFIX}import type * as Models from './consumer-index'; function label(p: Models.ConsumerAlias | Models.ConsumerName): string {return p.name;} label(account);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "inline covering contract is retained verbatim", filename: "probe.tsx",
      code: `${CONSUMER_PREFIX}function label(p: {readonly name: string; readonly email: string} | {readonly name: string}): string {return p.name;} label(account);`,
      output: `${CONSUMER_PREFIX}function label(p: {readonly name: string}): string {return p.name;} label(account);`, errors: [{messageId: "redundant"}]},
    {name: "annotation comments remain manual", filename: "probe.tsx", code: `${PREFIX}function label(p: Dog /* retain rationale */ | Animal): string {return p.name;} label(account);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "preexisting invalid identifier argument remains rejected", filename: "probe.tsx", code: `${UNION_DECLARATIONS}const value = {name: 42, email: 'a'}; function label(p: Dog | Animal): string {return p.name;} label(value); export {};`, output: null, errors: [{messageId: "redundant"}]},
    ...["any", "unknown"].map((type) => ({name: "unsafe relevant caller type remains manual " + type, filename: "probe.tsx",
      code: `${PREFIX}declare const value: {name: ${type}; email: string}; function label(p: Dog | Animal): string {return p.name;} label(value);`, output: null, errors: [{messageId: "redundant" as const}]})),
    {name: "unresolved error caller field remains manual", filename: "probe.tsx", code: `${PREFIX}declare const value: {name: Missing; email: string}; function label(p: Dog | Animal): string {return p.name;} label(value);`, output: null, errors: [{messageId: "redundant"}]},
    {name: "TypeScript suppressions stay manual", filename: "probe.tsx", code: `${PREFIX}function label(p: Dog | Animal): string {return p.name;} // @ts-ignore preserve the authored checking boundary\nlabel(account);`, output: null, errors: [{messageId: "redundant"}]},
  ],
});
