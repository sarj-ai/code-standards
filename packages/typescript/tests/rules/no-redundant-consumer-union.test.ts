import rule from "../../src/rules/no-redundant-consumer-union.js";
import { CONSUMER_PREFIX, PRIVATE_CONSUMER_TESTER, UNION_DECLARATIONS, runPrivateConsumerBoundaries } from "../private-consumer-cases.js";

const PREFIX = `${CONSUMER_PREFIX}${UNION_DECLARATIONS}`;
const NULLABLE_PREFIX = `${CONSUMER_PREFIX}interface Animal {readonly name: string | null} interface Dog extends Animal {readonly email: string}`;
const OPTIONAL_DECLARATIONS = "interface Name {readonly name: string} interface Full extends Name {readonly email?: string}";
const OPTIONAL_CALLER = "const input = {name: 'Ada', email: 42};";
const OPTIONAL_PREFIX = `export {}; ${OPTIONAL_DECLARATIONS} export type KeptFull = Full; ${OPTIONAL_CALLER}`;
const SCALAR_FUNCTION_HELPER = "function formatName(value: string): string {return '[' + value + ']';} ";
const SCALAR_ARROW_HELPER = "const formatName = (value: string): string => '[' + value + ']'; ";

const MERGED_OPTIONAL_SOURCE = "export {};\ninterface Name {readonly name: string}\ninterface Full {readonly name: string; readonly email?: string}\ninterface Full {readonly note?: string}\nexport type KeptFull = Full;\nconst full: Full = {name: 'Ada', email: 'a'};\nconst incompatibleExtra = {name: 'Ada', email: 42};\nfunction label(p: Full | Name): string {return p.name;}\nlabel(full); label(incompatibleExtra);\n";

PRIVATE_CONSUMER_TESTER.run("no-redundant-consumer-union mutual optional surfaces", rule, {
  valid: [
    {name: "mixed exported and local fragments cannot establish one binding", filename: "probe.tsx",
      code: MERGED_OPTIONAL_SOURCE.replace("interface Full {readonly note?: string}", "export interface Full {readonly name: number; readonly note?: string}")},
    {name: "same-source-global-contract-unsupported", filename: "probe.tsx", code: "export {};\ndeclare global {interface __Pass05GlobalName {readonly name: string}}\ninterface Full extends __Pass05GlobalName {readonly email?: string}\nexport type KeptFull = Full;\nconst input = {name: 'Ada', email: 42};\nfunction label(p: Full | __Pass05GlobalName): string {return p.name;}\nlabel(input);\n"},
    {name: "defaulted-generic-alias-unsupported", filename: "probe.tsx", code: "export {};\ninterface Name {readonly name: string}\ntype Full<_Unused = unknown> = {readonly name: string; readonly email?: string};\nexport type KeptFull = Full;\nconst input = {name: 'Ada', email: 42};\nfunction label(p: Full | Name): string {return p.name;}\nlabel(input);\n"},

    {name: "imported mutual contracts remain outside the local binding proof", filename: "probe.tsx", code: "export {}; import type {ConsumerName as Name} from './consumer-index'; interface Full extends Name {readonly email?: string} export type KeptFull = Full; const input = {name: 'Ada', email: 42}; function label(p: Full | Name): string {return p.name;} label(input);"},
    {name: "malformed duplicate alias headers cannot establish mutual coverage", filename: "probe.tsx", code: "export {};\ninterface Name {readonly name: string}\ntype Ambiguous = {readonly name: string; readonly email?: string};\ntype Ambiguous = {readonly name: number; readonly email?: string};\ntype Full = Ambiguous;\nexport type KeptFull = Full;\nconst full: Full = {name: 'Ada', email: 'a'};\nconst incompatibleExtra = {name: 'Ada', email: 42};\nfunction label(p: Full | Name): string {return p.name;}\nlabel(full); label(incompatibleExtra);\n"},
    {name: "equal-key mutual contracts stay unsupported", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX.replace("interface Full extends Name {readonly email?: string}", "interface Full extends Name {}")} function label(p: Full | Name): string {return p.name;} label(input);`},
    ...["", "readonly phone?: string;"].map((extra) => ({
      name: "incomparable optional keys stay unsupported with " + (extra ? "unequal" : "equal") + " counts", filename: "probe.tsx",
      code: `export {}; interface Name {readonly name: string; readonly note?: string} interface Full {readonly name: string; readonly email?: string; ${extra}} export type KeptFull = Full; const incompatibleExtra = {name: 'Ada', email: 42}; const incompatibleRetained = {name: 'Ada', note: 42}; function label(p: Full | Name): string {return p.name;} label(incompatibleExtra); label(incompatibleRetained);`,
    })),
    {name: "implicit Object Any does not make a required extra optional", filename: "probe.tsx",
      code: "export {}; declare global {interface Object {readonly __pass05RequiredToken: any}} interface Name {readonly name: string} interface Full extends Name {readonly __pass05RequiredToken: string} export type KeptFull = Full; const input = {name: 'Ada', __pass05RequiredToken: 42}; function label(p: Full | Name): string {return p.name;} label(input);"},
    {name: "all-optional mutual surface lacks a required read", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX.replace("readonly name: string", "readonly name?: string")} function label(p: Full | Name): string {return p.name ?? '';} label(input);`},
    {name: "reading the extra surface remains unsupported", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX} function label(p: Full | Name): string {return 'email' in p ? typeof p.email : p.name;} label(input);`},
    {name: "fresh literals retain excess-property checking", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX.replace(OPTIONAL_CALLER, "")} function label(p: Full | Name): string {return p.name;} label({name: 'Ada', email: 'a'});`},
    {name: "public mutual surface remains observable", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX} export function label(p: Full | Name): string {return p.name;} label(input);`},
    {name: "a public type observes the callable union", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX} function label(p: Full | Name): string {return p.name;} export type Signature = typeof label; label(input);`},
  ],
  invalid: [
    {name: "exported disjoint fragments retain their shared native binding", filename: "probe.tsx",
      code: MERGED_OPTIONAL_SOURCE.replaceAll("interface Full", "export interface Full"),
      output: MERGED_OPTIONAL_SOURCE.replaceAll("interface Full", "export interface Full").replace("Full | Name", "Name"),
      errors: [{messageId: "redundant", data: {covered: "Full", covering: "Name"}}]},
    {name: "local-merged-default-export-and-value-shadow", filename: "probe.tsx", code: "export {};\nexport default interface Name {readonly name: string}\ninterface Full extends Name {}\ninterface Full {readonly email?: string}\nexport type KeptFull = Full;\nconst input = {name: 'Ada', email: 42};\nfunction label(Name: Full | Name): string {return Name.name;}\nlabel(input);\n", output: "export {};\nexport default interface Name {readonly name: string}\ninterface Full extends Name {}\ninterface Full {readonly email?: string}\nexport type KeptFull = Full;\nconst input = {name: 'Ada', email: 42};\nfunction label(Name: Name): string {return Name.name;}\nlabel(input);\n", errors: [{messageId: "redundant", data: {covered: "Full", covering: "Name"}}]},
    ...["Full | Name", "Name | Full"].map((contract) => {
      const code = `${OPTIONAL_PREFIX} function label(p: ${contract}): string {return p.name;} label(input);`;
      return {name: "retain smaller Name despite an incompatible extra identifier: " + contract, filename: "probe.tsx", code,
        output: code.replace(contract, "Name"), errors: [{messageId: "redundant" as const, data: {covered: "Full", covering: "Name"}}]};
    }),
    ...([
      ["local alias", "FullAlias | Name", "FullAlias", `export {}; ${OPTIONAL_DECLARATIONS} type FullAlias = Full; export type KeptFull = FullAlias; ${OPTIONAL_CALLER} function label(p: FullAlias | Name): string {return p.name;} label(input);`],

      ["shared nullable and optional fields", "Full | Name", "Full", `export {}; interface Name {readonly name: string | null; readonly note?: string | undefined} interface Full extends Name {readonly email?: string | null} export type KeptFull = Full; ${OPTIONAL_CALLER} function label(p: Full | Name): string {return p.name ?? p.note ?? '';} label(input);`],
    ] as const).map(([name, contract, covered, code]) => ({name: "mutual optional surface with " + name, filename: "probe.tsx", code,
      output: code.replace(contract, "Name"), errors: [{messageId: "redundant" as const, data: {covered, covering: "Name"}}]})),
    {name: "without a public removed-type anchor the finding stays manual", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX.replace("export type KeptFull = Full;", "")} function label(p: Full | Name): string {return p.name;} label(input);`,
      output: null, errors: [{messageId: "redundant", data: {covered: "Full", covering: "Name"}}]},
    {name: "comments inside the mutual annotation keep the finding manual", filename: "probe.tsx",
      code: `${OPTIONAL_PREFIX} function label(p: Full /* keep reviewed domain note */ | Name): string {return p.name;} label(input);`,
      output: null, errors: [{messageId: "redundant", data: {covered: "Full", covering: "Name"}}]},
  ],
});

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

PRIVATE_CONSUMER_TESTER.run("no-redundant-consumer-union local scalar helpers", rule, {
  valid: [
    {name: "whole-object helper arguments remain unsupported", filename: "probe.tsx",
      code: `${PREFIX}function formatAnimal(value: Animal): string {return value.name;} function label(p: Dog | Animal): string {return formatAnimal(p);} label(account);`},
    {name: "ambient helper identity remains unsupported", filename: "probe.tsx",
      code: `${PREFIX}declare function formatName(value: string): string; function label(p: Dog | Animal): string {return formatName(p.name);} label(account);`},
    {name: "scalar helper permission does not enable auxiliary consumer parameters", filename: "probe.tsx",
      code: `${PREFIX}${SCALAR_FUNCTION_HELPER}function label(p: Dog | Animal, suffix: string): string {return formatName(p.name) + suffix;} label(account, '!');`},
    {name: "scalar helper cannot replace a required object-field read", filename: "probe.tsx",
      code: `export {}; interface Name {readonly name?: string} interface Full extends Name {readonly email?: string} export type KeptFull = Full; const input = {email: 'a'}; ${SCALAR_FUNCTION_HELPER}function label(p: Full | Name): string {return formatName(p.name ?? '');} label(input);`},
    {name: "original invalid caller fails the helper's native checked-source proof", filename: "probe.tsx",
      code: `${UNION_DECLARATIONS}const input = {name: 42, email: 'a'}; ${SCALAR_FUNCTION_HELPER}function label(p: Dog | Animal): string {return formatName(p.name);} label(input); export {};`},
  ],
  invalid: [
    ...([
      ["Dog | Animal", SCALAR_FUNCTION_HELPER],
      ["Dog | Animal", SCALAR_ARROW_HELPER],
      ["Animal | Dog", SCALAR_FUNCTION_HELPER],
      ["Animal | Dog", SCALAR_ARROW_HELPER],
    ] as const).map(([contract, helper]) => {
      const code = `${PREFIX}export type KeptDog = Dog; ${helper}function label(p: ${contract}): string {return formatName(p.name);} label(account);`;
      return {name: "local scalar helper retains Animal: " + contract + " " + (helper === SCALAR_FUNCTION_HELPER ? "function" : "arrow"), filename: "probe.tsx", code,
        output: code.replace(contract, "Animal"), errors: [{messageId: "redundant" as const, data: {covered: "Dog", covering: "Animal"}}]};
    }),
    ...["Full | Name", "Name | Full"].map((contract) => {
      const code = `${OPTIONAL_PREFIX}${SCALAR_FUNCTION_HELPER}function label(p: ${contract}): string {return formatName(p.name);} label(input);`;
      return {name: "local scalar helper preserves the native covering caller contract: " + contract, filename: "probe.tsx", code,
        output: code.replace(contract, "Name"), errors: [{messageId: "redundant" as const, data: {covered: "Full", covering: "Name"}}]};
    }),
    {name: "local scalar helper does not bypass removed-type retention", filename: "probe.tsx",
      code: `${PREFIX}${SCALAR_FUNCTION_HELPER}function label(p: Dog | Animal): string {return formatName(p.name);} label(account);`,
      output: null, errors: [{messageId: "redundant"}]},
  ],
});
