import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export interface CliOption {
  kind: 'option' | 'positional';
  names: string[];
  metavar: string | null;
  summary: string;
  choices: string[];
  required: boolean;
  repeatable: boolean;
}

export interface CliCommand {
  name: string;
  path: string[];
  usage: string;
  summary: string;
  options: CliOption[];
  commands: CliCommand[];
}

export interface CliReference {
  schemaVersion: 1;
  program: string;
  summary: string;
  epilog: string | null;
  globalOptions: CliOption[];
  commands: CliCommand[];
}

const referencePath = resolve(
  process.cwd(),
  '../../packages/standards/src/sarj_standards/configs/cli-reference.v1.json',
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireText(value: unknown, label: string, allowEmpty = false): asserts value is string {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0)) {
    throw new TypeError(`${label} must be ${allowEmpty ? 'a string' : 'a non-empty string'}.`);
  }
}

function validateOption(value: unknown, label: string): asserts value is CliOption {
  if (!isRecord(value)) throw new TypeError(`${label} must be an object.`);
  if (value.kind !== 'option' && value.kind !== 'positional') throw new TypeError(`${label}.kind is invalid.`);
  if (!Array.isArray(value.names) || !value.names.every((name) => typeof name === 'string')) {
    throw new TypeError(`${label}.names must be a string array.`);
  }
  requireText(value.summary, `${label}.summary`, true);
  if (value.metavar !== null && typeof value.metavar !== 'string') throw new TypeError(`${label}.metavar is invalid.`);
  if (!Array.isArray(value.choices) || !value.choices.every((choice) => typeof choice === 'string')) {
    throw new TypeError(`${label}.choices must be a string array.`);
  }
  if (typeof value.required !== 'boolean' || typeof value.repeatable !== 'boolean') {
    throw new TypeError(`${label} required and repeatable must be booleans.`);
  }
}

function validateCommand(value: unknown, label: string): asserts value is CliCommand {
  if (!isRecord(value)) throw new TypeError(`${label} must be an object.`);
  requireText(value.name, `${label}.name`);
  requireText(value.usage, `${label}.usage`);
  requireText(value.summary, `${label}.summary`, true);
  if (!Array.isArray(value.path) || !value.path.every((part) => typeof part === 'string')) {
    throw new TypeError(`${label}.path must be a string array.`);
  }
  if (!Array.isArray(value.options) || !Array.isArray(value.commands)) {
    throw new TypeError(`${label} options and commands must be arrays.`);
  }
  value.options.forEach((option, index) => validateOption(option, `${label}.options[${index}]`));
  value.commands.forEach((command, index) => validateCommand(command, `${label}.commands[${index}]`));
}

function loadReference(): CliReference {
  let source: string;
  try {
    source = readFileSync(referencePath, 'utf8');
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') {
      throw new Error(`Generated CLI reference is missing at ${referencePath}. Generate it before building apps/docs.`, {
        cause: error,
      });
    }
    throw error;
  }
  let value: unknown;
  try {
    value = JSON.parse(source) as unknown;
  } catch (error) {
    throw new Error(`Generated CLI reference is not valid JSON at ${referencePath}.`, { cause: error });
  }
  if (!isRecord(value) || value.schemaVersion !== 1) throw new TypeError('CLI reference must use schemaVersion 1.');
  requireText(value.program, 'CLI reference program');
  requireText(value.summary, 'CLI reference summary');
  if (value.epilog !== null && typeof value.epilog !== 'string') throw new TypeError('CLI reference epilog is invalid.');
  if (!Array.isArray(value.globalOptions) || !Array.isArray(value.commands)) {
    throw new TypeError('CLI reference globalOptions and commands must be arrays.');
  }
  value.globalOptions.forEach((option, index) => validateOption(option, `globalOptions[${index}]`));
  value.commands.forEach((command, index) => validateCommand(command, `commands[${index}]`));
  return value as unknown as CliReference;
}

export const cliReference = loadReference();

export function invocation(command: CliCommand): string {
  return [cliReference.program, ...command.path].join(' ');
}

export function flattenCommands(commands: CliCommand[] = cliReference.commands): CliCommand[] {
  return commands.flatMap((command) => [command, ...flattenCommands(command.commands)]);
}

export function commandAnchor(command: CliCommand): string {
  return command.path.join('-');
}

export function optionLabel(option: CliOption): string {
  if (option.kind === 'positional') return option.metavar ?? option.names[0] ?? '';
  return `${option.names.join(', ')}${option.metavar ? ` ${option.metavar}` : ''}`;
}
